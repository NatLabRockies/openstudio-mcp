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
    # Validates: DOAS with ERV creates air loop with ERV at 0.75 sensible effectiveness
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

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
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

                assert system_data["ok"] is True
                assert system_data["system"]["type"] == "DOAS"
                assert system_data["system"]["energy_recovery"] is True
                assert "ERV" in system_data["system"]["erv_name"], (
                    f"ERV name should contain 'ERV': {system_data['system']['erv_name']}"
                )
                assert system_data["system"]["sensible_effectiveness"] == pytest.approx(0.75)

                # Independent readback — verify ERV effectiveness in the model
                erv_name = system_data["system"]["erv_name"]
                erv_fields = unwrap(await session.call_tool("get_object_fields", {
                    "object_type": "HeatExchangerAirToAirSensibleAndLatent",
                    "object_name": erv_name,
                }))
                assert erv_fields["ok"] is True
                erv_eff = erv_fields["properties"]["sensibleEffectivenessat100HeatingAirFlow"]["value"]
                assert erv_eff == pytest.approx(0.75), \
                    f"ERV sensible effectiveness should be 0.75, got {erv_eff}"

                # Independent query verification
                alr = await session.call_tool("list_air_loops", {})
                ald = unwrap(alr)
                assert any("DOAS ERV Test" in lp["name"] for lp in ald["air_loops"])

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_without_erv():
    """Verify DOAS without ERV still creates valid system."""
    # Validates: DOAS without ERV has erv_name=None and no ERV effectiveness
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

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
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

                assert system_data["ok"] is True
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
    # Validates: DOAS+FanCoil creates CHW+HW loops with ZoneHVACFourPipeFanCoil per zone
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

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
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

                assert system_data["ok"] is True
                assert system_data["system"]["zone_equipment_type"] == "FanCoil"
                assert system_data["system"]["chilled_water_loop"], "CHW loop should be created"
                assert system_data["system"]["hot_water_loop"], "HW loop should be created"
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
    # Validates: DOAS+Radiant creates CHW+HW loops with ZoneHVACLowTempRadiantVarFlow
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

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
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

                assert system_data["ok"] is True
                assert system_data["system"]["zone_equipment_type"] == "Radiant"
                assert system_data["system"]["chilled_water_loop"], "CHW loop should be created"
                assert system_data["system"]["hot_water_loop"], "HW loop should be created"

                # Verify radiant equipment
                for equip in system_data["system"]["zone_equipment"]:
                    assert equip["type"] == "ZoneHVACLowTempRadiantVarFlow"

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_chiller_beams():
    """Verify DOAS with chilled beam zone equipment."""
    # Validates: DOAS+ChilledBeams creates CHW loop with cooled beam terminals
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

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
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

                assert system_data["ok"] is True
                assert system_data["system"]["zone_equipment_type"] == "ChilledBeams"
                assert system_data["system"]["chilled_water_loop"], "CHW loop should be created"

                # Verify chilled beam equipment
                for equip in system_data["system"]["zone_equipment"]:
                    assert equip["type"] == "AirTerminalSingleDuctConstantVolumeCooledBeam"

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_four_pipe_beam():
    """Verify DOAS with 4-pipe beam zone equipment creates CHW+HW loops."""
    # Validates: DOAS+FourPipeBeam creates CHW+HW loops with 4-pipe beam terminals
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

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
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

                assert system_data["ok"] is True
                assert system_data["system"]["zone_equipment_type"] == "FourPipeBeam"
                assert system_data["system"]["chilled_water_loop"], "CHW loop should be created"
                assert system_data["system"]["hot_water_loop"], "HW loop should be created"

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
    # Validates: DOAS air loop serves all requested zones
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

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
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

                assert system_data["ok"] is True

                # Verify DOAS loop exists and serves zones
                air_loops_resp = await session.call_tool("list_air_loops", {})
                air_loops_data = unwrap(air_loops_resp)

                doas_loop = None
                for loop in air_loops_data["air_loops"]:
                    if "DOAS OA Test" in loop["name"]:
                        doas_loop = loop
                        break

                assert doas_loop, "DOAS air loop should exist in model"
                assert doas_loop["num_thermal_zones"] == len(zone_names)

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_multi_zone_baseline():
    """Verify DOAS with fan coils on 10-zone baseline model."""
    # Validates: DOAS+FanCoil on 10-zone baseline creates 10 zone equipment + air loop
    import uuid
    name = f"test_doas_bl_{uuid.uuid4().hex[:8]}"

    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
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

                assert system_data["ok"] is True
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
                assert doas_loop, "DOAS air loop should exist in model"
                assert doas_loop["num_thermal_zones"] == 10

    asyncio.run(_run())


def test_doas_json_string_zones():
    """Test add_doas_system accepts thermal_zone_names as JSON string."""
    # Regression: MCP clients sent zone names as JSON string, caused TypeError
    import json

    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": "test_doas_json"})
                create_data = unwrap(create_resp)
                await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_name = unwrap(zones_resp)["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": json.dumps([zone_name]),
                })
                system_data = unwrap(system_resp)

                assert system_data["ok"] is True, (
                    f"JSON-string zone names failed: {system_data.get('error')}"
                )

    asyncio.run(_run())


@pytest.mark.integration
def test_doas_on_example_model_repairs_and_simulates():
    """Golden path: example model + add_doas_system -> repaired model runs E+."""
    # Regression: #83 — add_doas_system stole the example model's zone, leaving
    # "Air Loop HVAC 1" empty with an orphaned SPM:SingleZone:Reheat; EnergyPlus
    # then fataled at input processing ("Missing required property
    # 'control_zone_name'"). The tool must now remove the dead loop and the
    # model must simulate.
    import uuid

    from conftest import EPW_PATH, poll_until_done

    name = f"test_doas_repair_{uuid.uuid4().hex[:8]}"

    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_data = unwrap(await session.call_tool(
                    "create_example_osm", {"name": name}))
                assert create_data["ok"] is True, create_data
                lr = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": create_data["osm_path"]}))
                assert lr["ok"] is True, lr

                zones_data = unwrap(await session.call_tool(
                    "list_thermal_zones", {"max_results": 0}))
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]
                assert zone_names == ["Thermal Zone 1"]

                system_data = unwrap(await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Repair Test",
                    "zone_equipment_type": "FanCoil",
                }))
                assert system_data["ok"] is True, system_data

                # The repair must be reported: the example model's own loop
                # lost its only zone and was removed (SPM removed with it).
                repairs = system_data["repairs"]
                assert repairs == [{
                    "action": "removed_empty_air_loop",
                    "air_loop": "Air Loop HVAC 1",
                    "reason": (
                        "lost all its thermal zones to the new system; an air "
                        "loop serving zero zones fails EnergyPlus input "
                        "processing"
                    ),
                }], repairs

                # validate_model must see neither #83 fatal precursor
                v = unwrap(await session.call_tool("validate_model", {}))
                assert not any("serves no thermal zones" in e for e in v["errors"]), v
                assert not any("has no control zone" in e for e in v["errors"]), v

                rp = unwrap(await session.call_tool("set_run_period", {
                    "begin_month": 1, "begin_day": 1,
                    "end_month": 1, "end_day": 7, "name": "One Week",
                }))
                assert rp["ok"] is True, rp

                save_path = f"/runs/{name}.osm"
                sr = unwrap(await session.call_tool(
                    "save_osm_model", {"osm_path": save_path}))
                assert sr["ok"] is True, sr

                sim = unwrap(await session.call_tool("run_simulation", {
                    "osm_path": save_path, "epw_path": EPW_PATH,
                }))
                assert sim["ok"] is True, sim
                run_id = sim["run_id"]

                status = await poll_until_done(session, run_id)
                state = status["run"]["status"]
                assert state == "success", (
                    f"Simulation {state} — expected success. "
                    f"Check get_run_logs(run_id='{run_id}')"
                )

                # The #83 signatures must be gone from the E+ error file
                err_resp = unwrap(await session.call_tool("read_file", {
                    "file_path": f"/runs/{run_id}/run/eplusout.err",
                    "max_bytes": 100000,
                }))
                assert err_resp.get("ok") is True, err_resp
                err_text = err_resp.get("text", "")
                assert err_text, "eplusout.err came back empty"
                assert "Missing required property 'control_zone_name'" not in err_text
                assert "is not connected to any zone" not in err_text
                assert "**  Fatal  **" not in err_text, err_text[-2000:]

    asyncio.run(_run())
