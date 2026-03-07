"""Integration tests for DOAS (Dedicated Outdoor Air System) template.

Tests verify:
- 100% outdoor air loop creation
- Energy recovery ventilator (ERV) presence/absence
- Zone equipment types (fan coils, radiant, chilled beams)
- Plant loop creation for zone equipment
- Outdoor air flow settings
"""
from __future__ import annotations

import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


@pytest.mark.integration
def test_doas_with_erv():
    """Verify DOAS creates 100% OA loop with ERV."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_doas_erv"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Create DOAS with ERV
                system_resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS ERV Test",
                    "energy_recovery": True,
                    "sensible_effectiveness": 0.75,
                    "zone_equipment_type": "FanCoil",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "DOAS"
                assert system_data["system"]["energy_recovery"] is True
                assert system_data["system"]["erv_name"] is not None
                assert "ERV" in system_data["system"]["erv_name"]
                assert system_data["system"]["sensible_effectiveness"] == 0.75

                # Independent query verification
                alr = await session.call_tool("list_air_loops", {})
                ald = unwrap(alr)
                assert any("DOAS ERV Test" in lp["name"] for lp in ald["air_loops"])

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_without_erv():
    """Verify DOAS without ERV still creates valid system."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_doas_no_erv"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Create DOAS without ERV
                system_resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS No ERV",
                    "energy_recovery": False,
                    "zone_equipment_type": "FanCoil",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["energy_recovery"] is False
                assert system_data["system"]["erv_name"] is None
                assert system_data["system"]["sensible_effectiveness"] is None

                alr = await session.call_tool("list_air_loops", {})
                ald = unwrap(alr)
                assert any("DOAS No ERV" in lp["name"] for lp in ald["air_loops"])

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_fan_coils():
    """Verify DOAS with fan coil zone equipment creates CHW/HW loops."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_doas_fc"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones (1 in example)

                # Create DOAS with fan coils
                system_resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS FC",
                    "energy_recovery": True,
                    "zone_equipment_type": "FanCoil",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["zone_equipment_type"] == "FanCoil"
                assert system_data["system"]["chilled_water_loop"] is not None
                assert system_data["system"]["hot_water_loop"] is not None
                assert len(system_data["system"]["zone_equipment"]) == len(zone_names)

                # Verify fan coils
                for equip in system_data["system"]["zone_equipment"]:
                    assert equip["type"] == "ZoneHVACFourPipeFanCoil"

                # Independent query verification — plant loops created
                plr = await session.call_tool("list_plant_loops", {})
                pld = unwrap(plr)
                assert pld["count"] >= 2  # CHW + HW loops

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_radiant():
    """Verify DOAS with radiant zone equipment."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_doas_rad"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create DOAS with radiant
                system_resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Radiant",
                    "energy_recovery": True,
                    "zone_equipment_type": "Radiant",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["zone_equipment_type"] == "Radiant"
                assert system_data["system"]["chilled_water_loop"] is not None
                assert system_data["system"]["hot_water_loop"] is not None

                # Verify radiant equipment
                for equip in system_data["system"]["zone_equipment"]:
                    assert equip["type"] == "ZoneHVACLowTempRadiantVarFlow"

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_chiller_beams():
    """Verify DOAS with chilled beam zone equipment."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_doas_beams"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]  # Use all zones

                # Create DOAS with chilled beams
                system_resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Beams",
                    "energy_recovery": True,
                    "zone_equipment_type": "ChilledBeams",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["zone_equipment_type"] == "ChilledBeams"
                assert system_data["system"]["chilled_water_loop"] is not None

                # Verify chilled beam equipment
                for equip in system_data["system"]["zone_equipment"]:
                    assert equip["type"] == "AirTerminalSingleDuctConstantVolumeCooledBeam"

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_four_pipe_beam():
    """Verify DOAS with 4-pipe beam zone equipment creates CHW+HW loops."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_doas_4pb"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Create DOAS with four pipe beams
                system_resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS 4PB",
                    "energy_recovery": True,
                    "zone_equipment_type": "FourPipeBeam",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["zone_equipment_type"] == "FourPipeBeam"
                assert system_data["system"]["chilled_water_loop"] is not None
                assert system_data["system"]["hot_water_loop"] is not None

                # Verify four pipe beam equipment
                for equip in system_data["system"]["zone_equipment"]:
                    assert equip["type"] == "AirTerminalSingleDuctConstantVolumeFourPipeBeam"

                # Verify plant loops created (CHW + HW + condenser)
                plr = await session.call_tool("list_plant_loops", {})
                pld = unwrap(plr)
                assert pld["count"] >= 2  # CHW + HW loops

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_oa_flow():
    """Verify DOAS air loop exists and serves zones."""
    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_doas_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Create DOAS
                system_resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS OA Test",
                    "energy_recovery": True,
                    "zone_equipment_type": "FanCoil",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True

                # Verify DOAS loop exists and serves zones
                air_loops_resp = await session.call_tool("list_air_loops", {})
                air_loops_data = unwrap(air_loops_resp)

                doas_loop = None
                for loop in air_loops_data["air_loops"]:
                    if "DOAS OA Test" in loop["name"]:
                        doas_loop = loop
                        break

                assert doas_loop is not None
                assert doas_loop["num_thermal_zones"] == len(zone_names)

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_multi_zone_baseline():
    """Verify DOAS with fan coils on 10-zone baseline model."""
    import uuid
    name = f"test_doas_bl_{uuid.uuid4().hex[:8]}"

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

                system_resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Baseline DOAS",
                    "energy_recovery": True,
                    "sensible_effectiveness": 0.75,
                    "zone_equipment_type": "FanCoil",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "DOAS"
                assert len(system_data["system"]["zone_equipment"]) == 10
                assert system_data["system"]["energy_recovery"] is True

                # Verify DOAS air loop serves all 10 zones
                air_loops_resp = await session.call_tool("list_air_loops", {})
                air_loops_data = unwrap(air_loops_resp)
                doas_loop = next(
                    (lp for lp in air_loops_data["air_loops"] if "Baseline DOAS" in lp["name"]),
                    None,
                )
                assert doas_loop is not None
                assert doas_loop["num_thermal_zones"] == 10

    asyncio.run(_run())


def test_doas_json_string_zones():
    """Test add_doas_system accepts thermal_zone_names as JSON string."""
    import json

    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": "test_doas_json"})
                create_data = unwrap(create_resp)
                await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zone_name = unwrap(zones_resp)["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": json.dumps([zone_name]),
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True, (
                    f"JSON-string zone names failed: {system_data.get('error')}"
                )

    asyncio.run(_run())
