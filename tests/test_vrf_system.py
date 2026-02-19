"""Integration tests for VRF (Variable Refrigerant Flow) template.

Tests verify:
- VRF outdoor unit creation
- VRF zone terminals (1 per zone)
- Heat recovery mode vs heat pump mode
- Capacity autosizing vs explicit capacity
- Multi-zone operation
"""
from __future__ import annotations

import asyncio
import json
import os
import shlex

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Test configuration
INTEGRATION_ENV_VAR = "RUN_OPENSTUDIO_INTEGRATION"
SERVER_CMD_VAR = "MCP_SERVER_CMD"

# Skip if integration tests not enabled
pytestmark = pytest.mark.skipif(
    os.getenv(INTEGRATION_ENV_VAR) != "1",
    reason=f"{INTEGRATION_ENV_VAR} not set to 1"
)


def _unwrap(result) -> dict:
    """Unwrap MCP tool result from TextContent."""
    if hasattr(result, 'content') and len(result.content) > 0:
        text_content = result.content[0]
        if hasattr(text_content, 'text'):
            return json.loads(text_content.text)
    return {}


def _get_server_params():
    """Get server parameters with proper env setup."""
    server_cmd = os.environ.get(SERVER_CMD_VAR, "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    return StdioServerParameters(
        command=server_cmd,
        args=server_args,
        env=os.environ.copy()
    )


@pytest.mark.integration
def test_vrf_heat_recovery():
    """Verify VRF with heat recovery mode creates correct system."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_vrf_hr"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create VRF with heat recovery
                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "VRF HR",
                    "heat_recovery": True,
                    "outdoor_unit_capacity_w": None  # Autosize
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "VRF"
                assert system_data["system"]["heat_recovery"] is True
                assert "HR" in system_data["system"]["outdoor_unit"]
                assert system_data["system"]["capacity_w"] == "autosized"
                assert len(system_data["system"]["terminals"]) == len(zone_names)

                # Independent query verification
                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = _unwrap(ze)
                equip_types = [eq["type"] for eq in zd.get("zone_hvac_equipment", [])]
                assert any("VRF" in t or "Terminal" in t for t in equip_types)

    asyncio.run(_run())


@pytest.mark.integration
def test_vrf_heat_pump():
    """Verify VRF heat pump mode (no heat recovery)."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_vrf_hp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create VRF without heat recovery
                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "VRF HP",
                    "heat_recovery": False,
                    "outdoor_unit_capacity_w": None
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["heat_recovery"] is False
                assert "HR" not in system_data["system"]["outdoor_unit"]
                assert len(system_data["system"]["terminals"]) == len(zone_names)

                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = _unwrap(ze)
                equip_types = [eq["type"] for eq in zd.get("zone_hvac_equipment", [])]
                assert any("VRF" in t or "Terminal" in t for t in equip_types)

    asyncio.run(_run())


@pytest.mark.integration
def test_vrf_multi_zone():
    """Verify VRF serves multiple zones with 1 outdoor unit."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_vrf_multi"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Create VRF serving all zones
                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "VRF Multi",
                    "heat_recovery": True,
                    "outdoor_unit_capacity_w": None
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["num_zones"] == len(zone_names)
                assert len(system_data["system"]["terminals"]) == len(zone_names)

                # Verify each zone has terminal
                terminal_zones = [t["zone"] for t in system_data["system"]["terminals"]]
                for zone_name in zone_names:
                    assert zone_name in terminal_zones

                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = _unwrap(ze)
                equip_zones = [eq.get("thermal_zone") for eq in zd.get("zone_hvac_equipment", [])]
                for zn in zone_names:
                    assert zn in equip_zones

    asyncio.run(_run())


@pytest.mark.integration
def test_vrf_capacity_autosize():
    """Verify VRF autosizes when capacity is None."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_vrf_auto"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create VRF with autosizing
                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "VRF Auto",
                    "heat_recovery": True,
                    "outdoor_unit_capacity_w": None
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["capacity_w"] == "autosized"

                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = _unwrap(ze)
                assert len(zd.get("zone_hvac_equipment", [])) > 0

    asyncio.run(_run())


@pytest.mark.integration
def test_vrf_capacity_explicit():
    """Verify VRF uses explicit capacity when provided."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_vrf_cap"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create VRF with explicit capacity
                capacity = 50000.0  # 50 kW
                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "VRF Fixed",
                    "heat_recovery": True,
                    "outdoor_unit_capacity_w": capacity
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["capacity_w"] == capacity

                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = _unwrap(ze)
                assert len(zd.get("zone_hvac_equipment", [])) > 0

    asyncio.run(_run())


@pytest.mark.integration
def test_vrf_multi_zone_baseline():
    """Verify VRF with heat recovery on 10-zone baseline model."""
    import uuid
    name = f"test_vrf_bl_{uuid.uuid4().hex[:8]}"

    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = _unwrap(cr)
                assert cd.get("ok") is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert _unwrap(lr).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]
                assert len(zone_names) == 10

                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Baseline VRF",
                    "heat_recovery": True,
                    "outdoor_unit_capacity_w": None
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "VRF"
                assert system_data["system"]["num_zones"] == 10
                assert len(system_data["system"]["terminals"]) == 10
                assert system_data["system"]["heat_recovery"] is True

    asyncio.run(_run())
