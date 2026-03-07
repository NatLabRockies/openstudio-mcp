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

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


@pytest.mark.integration
def test_vrf_heat_recovery():
    """Verify VRF with heat recovery mode creates correct system."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_vrf_hr"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create VRF with heat recovery
                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "VRF HR",
                    "heat_recovery": True,
                    "outdoor_unit_capacity_w": None,  # Autosize
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "VRF"
                assert system_data["system"]["heat_recovery"] is True
                assert "HR" in system_data["system"]["outdoor_unit"]
                assert system_data["system"]["capacity_w"] == "autosized"
                assert len(system_data["system"]["terminals"]) == len(zone_names)

                # Independent query verification
                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = unwrap(ze)
                equip_types = [eq["type"] for eq in zd.get("zone_hvac_equipment", [])]
                assert any("VRF" in t or "Terminal" in t for t in equip_types)

    asyncio.run(_run())


@pytest.mark.integration
def test_vrf_heat_pump():
    """Verify VRF heat pump mode (no heat recovery)."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_vrf_hp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create VRF without heat recovery
                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "VRF HP",
                    "heat_recovery": False,
                    "outdoor_unit_capacity_w": None,
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["heat_recovery"] is False
                assert "HR" not in system_data["system"]["outdoor_unit"]
                assert len(system_data["system"]["terminals"]) == len(zone_names)

                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = unwrap(ze)
                equip_types = [eq["type"] for eq in zd.get("zone_hvac_equipment", [])]
                assert any("VRF" in t or "Terminal" in t for t in equip_types)

    asyncio.run(_run())


@pytest.mark.integration
def test_vrf_multi_zone():
    """Verify VRF serves multiple zones with 1 outdoor unit."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_vrf_multi"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Create VRF serving all zones
                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "VRF Multi",
                    "heat_recovery": True,
                    "outdoor_unit_capacity_w": None,
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["num_zones"] == len(zone_names)
                assert len(system_data["system"]["terminals"]) == len(zone_names)

                # Verify each zone has terminal
                terminal_zones = [t["zone"] for t in system_data["system"]["terminals"]]
                for zone_name in zone_names:
                    assert zone_name in terminal_zones

                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = unwrap(ze)
                equip_zones = [eq.get("thermal_zone") for eq in zd.get("zone_hvac_equipment", [])]
                for zn in zone_names:
                    assert zn in equip_zones

    asyncio.run(_run())


@pytest.mark.integration
def test_vrf_capacity_autosize():
    """Verify VRF autosizes when capacity is None."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_vrf_auto"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create VRF with autosizing
                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "VRF Auto",
                    "heat_recovery": True,
                    "outdoor_unit_capacity_w": None,
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["capacity_w"] == "autosized"

                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = unwrap(ze)
                assert len(zd.get("zone_hvac_equipment", [])) > 0

    asyncio.run(_run())


@pytest.mark.integration
def test_vrf_capacity_explicit():
    """Verify VRF uses explicit capacity when provided."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_vrf_cap"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create VRF with explicit capacity
                capacity = 50000.0  # 50 kW
                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "VRF Fixed",
                    "heat_recovery": True,
                    "outdoor_unit_capacity_w": capacity,
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["capacity_w"] == capacity

                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = unwrap(ze)
                assert len(zd.get("zone_hvac_equipment", [])) > 0

    asyncio.run(_run())


@pytest.mark.integration
def test_vrf_multi_zone_baseline():
    """Verify VRF with heat recovery on 10-zone baseline model."""
    import uuid
    name = f"test_vrf_bl_{uuid.uuid4().hex[:8]}"

    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]
                assert len(zone_names) == 10

                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Baseline VRF",
                    "heat_recovery": True,
                    "outdoor_unit_capacity_w": None,
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "VRF"
                assert system_data["system"]["num_zones"] == 10
                assert len(system_data["system"]["terminals"]) == 10
                assert system_data["system"]["heat_recovery"] is True

    asyncio.run(_run())


def test_vrf_json_string_zones():
    """Test add_vrf_system accepts thermal_zone_names as JSON string."""
    import json

    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": "test_vrf_json"})
                create_data = unwrap(create_resp)
                await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zone_name = unwrap(zones_resp)["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_vrf_system", {
                    "thermal_zone_names": json.dumps([zone_name]),
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True, (
                    f"JSON-string zone names failed: {system_data.get('error')}"
                )

    asyncio.run(_run())
