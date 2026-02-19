"""Integration tests for Radiant heating/cooling system template.

Tests verify:
- Radiant surface types (floor, ceiling, walls)
- Low-temperature plant loops (120°F HW, 58°F CHW)
- DOAS integration for ventilation
- Radiant equipment in zones
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
def test_radiant_floor():
    """Verify radiant floor system with low-temp loops."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_radiant_floor"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create radiant floor system
                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Radiant Floor",
                    "radiant_type": "Floor",
                    "ventilation_system": "None"
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "Radiant"
                assert system_data["system"]["radiant_type"] == "Floor"
                assert system_data["system"]["hw_supply_temp_f"] == 120
                assert system_data["system"]["chw_supply_temp_f"] == 58
                assert system_data["system"]["hot_water_loop"] is not None
                assert system_data["system"]["chilled_water_loop"] is not None
                assert len(system_data["system"]["radiant_equipment"]) == len(zone_names)

                # Verify floor radiant equipment
                for equip in system_data["system"]["radiant_equipment"]:
                    assert equip["type"] == "Floor"

                # Independent query verification
                plr = await session.call_tool("list_plant_loops", {})
                pld = _unwrap(plr)
                assert any("Low-Temp HW" in lp["name"] for lp in pld["plant_loops"])
                assert any("Low-Temp CHW" in lp["name"] for lp in pld["plant_loops"])

    asyncio.run(_run())


@pytest.mark.integration
def test_radiant_ceiling():
    """Verify radiant ceiling panels."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_radiant_ceiling"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create radiant ceiling system
                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Radiant Ceiling",
                    "radiant_type": "Ceiling",
                    "ventilation_system": "None"
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["radiant_type"] == "Ceiling"

                # Verify ceiling radiant equipment
                for equip in system_data["system"]["radiant_equipment"]:
                    assert equip["type"] == "Ceiling"

                plr = await session.call_tool("list_plant_loops", {})
                pld = _unwrap(plr)
                assert any("Low-Temp" in lp["name"] for lp in pld["plant_loops"])

    asyncio.run(_run())


@pytest.mark.integration
def test_radiant_with_doas():
    """Verify radiant system integrated with DOAS for ventilation."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_radiant_doas"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create radiant with DOAS
                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Radiant DOAS",
                    "radiant_type": "Floor",
                    "ventilation_system": "DOAS"
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["ventilation_system"] == "DOAS"
                assert system_data["system"]["doas_loop"] is not None
                assert "DOAS" in system_data["system"]["doas_loop"]

                # Verify DOAS air loop exists
                air_loops_resp = await session.call_tool("list_air_loops", {})
                air_loops_data = _unwrap(air_loops_resp)

                doas_exists = any("Radiant DOAS Ventilation" in loop["name"]
                                 for loop in air_loops_data["air_loops"])
                assert doas_exists

    asyncio.run(_run())


@pytest.mark.integration
def test_radiant_without_doas():
    """Verify radiant system without DOAS (ventilation handled separately)."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_radiant_no_doas"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create radiant without DOAS
                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Radiant Only",
                    "radiant_type": "Floor",
                    "ventilation_system": "None"
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["ventilation_system"] == "None"
                assert system_data["system"]["doas_loop"] is None

    asyncio.run(_run())


@pytest.mark.integration
def test_radiant_loop_temps():
    """Verify radiant system uses low-temperature plant loops."""
    async def _run():
        server_params = _get_server_params()
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_radiant_temps"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create radiant system
                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Radiant Temps",
                    "radiant_type": "Floor",
                    "ventilation_system": "None"
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True

                # Verify low-temp specifications
                assert system_data["system"]["hw_supply_temp_f"] == 120  # Low-temp heating
                assert system_data["system"]["chw_supply_temp_f"] == 58  # High-temp cooling

                # Verify plant loops exist
                loops_resp = await session.call_tool("list_plant_loops", {})
                loops_data = _unwrap(loops_resp)

                hw_loop_exists = any("Low-Temp HW" in loop["name"]
                                    for loop in loops_data["plant_loops"])
                chw_loop_exists = any("Low-Temp CHW" in loop["name"]
                                     for loop in loops_data["plant_loops"])

                assert hw_loop_exists
                assert chw_loop_exists

    asyncio.run(_run())


@pytest.mark.integration
def test_radiant_multi_zone_baseline():
    """Verify radiant floor + DOAS on 10-zone baseline model."""
    import uuid
    name = f"test_rad_bl_{uuid.uuid4().hex[:8]}"

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

                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Baseline Radiant",
                    "radiant_type": "Floor",
                    "ventilation_system": "DOAS"
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "Radiant"
                assert len(system_data["system"]["radiant_equipment"]) == 10
                assert system_data["system"]["ventilation_system"] == "DOAS"
                assert system_data["system"]["doas_loop"] is not None

                # Verify plant loops
                loops_resp = await session.call_tool("list_plant_loops", {})
                loops_data = _unwrap(loops_resp)
                assert any("Low-Temp HW" in lp["name"] for lp in loops_data["plant_loops"])
                assert any("Low-Temp CHW" in lp["name"] for lp in loops_data["plant_loops"])

    asyncio.run(_run())
