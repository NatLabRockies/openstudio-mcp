"""Integration tests for Radiant heating/cooling system template.

Tests verify:
- Radiant surface types (floor, ceiling, walls)
- Low-temperature plant loops (120°F HW, 58°F CHW)
- DOAS integration for ventilation
- Radiant equipment in zones
"""
from __future__ import annotations

import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


@pytest.mark.integration
def test_radiant_floor():
    """Verify radiant floor system with low-temp loops."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_radiant_floor"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create radiant floor system
                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Radiant Floor",
                    "radiant_type": "Floor",
                    "ventilation_system": "None",
                })
                system_data = unwrap(system_resp)

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
                pld = unwrap(plr)
                assert any("Low-Temp HW" in lp["name"] for lp in pld["plant_loops"])
                assert any("Low-Temp CHW" in lp["name"] for lp in pld["plant_loops"])

    asyncio.run(_run())


@pytest.mark.integration
def test_radiant_ceiling():
    """Verify radiant ceiling panels."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_radiant_ceiling"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create radiant ceiling system
                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Radiant Ceiling",
                    "radiant_type": "Ceiling",
                    "ventilation_system": "None",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["radiant_type"] == "Ceiling"

                # Verify ceiling radiant equipment
                for equip in system_data["system"]["radiant_equipment"]:
                    assert equip["type"] == "Ceiling"

                plr = await session.call_tool("list_plant_loops", {})
                pld = unwrap(plr)
                assert any("Low-Temp" in lp["name"] for lp in pld["plant_loops"])

    asyncio.run(_run())


@pytest.mark.integration
def test_radiant_with_doas():
    """Verify radiant system integrated with DOAS for ventilation."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_radiant_doas"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create radiant with DOAS
                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Radiant DOAS",
                    "radiant_type": "Floor",
                    "ventilation_system": "DOAS",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["ventilation_system"] == "DOAS"
                assert system_data["system"]["doas_loop"] is not None
                assert "DOAS" in system_data["system"]["doas_loop"]

                # Verify DOAS air loop exists
                air_loops_resp = await session.call_tool("list_air_loops", {})
                air_loops_data = unwrap(air_loops_resp)

                doas_exists = any("Radiant DOAS Ventilation" in loop["name"]
                                 for loop in air_loops_data["air_loops"])
                assert doas_exists

    asyncio.run(_run())


@pytest.mark.integration
def test_radiant_without_doas():
    """Verify radiant system without DOAS (ventilation handled separately)."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_radiant_no_doas"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create radiant without DOAS
                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Radiant Only",
                    "radiant_type": "Floor",
                    "ventilation_system": "None",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["ventilation_system"] == "None"
                assert system_data["system"]["doas_loop"] is None

    asyncio.run(_run())


@pytest.mark.integration
def test_radiant_loop_temps():
    """Verify radiant system uses low-temperature plant loops."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_radiant_temps"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create radiant system
                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Radiant Temps",
                    "radiant_type": "Floor",
                    "ventilation_system": "None",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True

                # Verify low-temp specifications
                assert system_data["system"]["hw_supply_temp_f"] == 120  # Low-temp heating
                assert system_data["system"]["chw_supply_temp_f"] == 58  # High-temp cooling

                # Verify plant loops exist
                loops_resp = await session.call_tool("list_plant_loops", {})
                loops_data = unwrap(loops_resp)

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

                system_resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Baseline Radiant",
                    "radiant_type": "Floor",
                    "ventilation_system": "DOAS",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "Radiant"
                assert len(system_data["system"]["radiant_equipment"]) == 10
                assert system_data["system"]["ventilation_system"] == "DOAS"
                assert system_data["system"]["doas_loop"] is not None

                # Verify plant loops
                loops_resp = await session.call_tool("list_plant_loops", {})
                loops_data = unwrap(loops_resp)
                assert any("Low-Temp HW" in lp["name"] for lp in loops_data["plant_loops"])
                assert any("Low-Temp CHW" in lp["name"] for lp in loops_data["plant_loops"])

    asyncio.run(_run())
