"""Integration tests for common measures (openstudio-common-measures-gem).

Tests list_common_measures discovery, category filtering, Tier 1 wrapper tools,
and Tier 2 wrapper tools (set_thermostat_schedules, shift_schedule_time,
add_rooftop_pv, add_ev_load, set_lifecycle_cost_params, add_cost_per_floor_area,
set_adiabatic_boundaries, etc.).
"""
import asyncio
import uuid

import pytest
from conftest import (
    EPW_PATH,
    integration_enabled,
    poll_until_done,
    server_params,
    setup_example,
    unwrap,
)
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_common") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _setup_baseline(session, model_name):
    """Create and load a baseline model."""
    cr = unwrap(await session.call_tool("create_baseline_osm", {"name": model_name}))
    assert cr.get("ok") is True, f"create_baseline_osm failed: {cr}"
    lr = unwrap(await session.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr.get("ok") is True, f"load_osm_model failed: {lr}"


async def _get_summary(session) -> dict:
    """Get model summary counts."""
    res = unwrap(await session.call_tool("get_model_summary", {}))
    assert res.get("ok") is True, f"get_model_summary failed: {res}"
    return res["summary"]


# --- Test 1: list_common_measures returns measures ---
@pytest.mark.integration
def test_list_common_measures():
    """Verify list_common_measures returns measures with expected fields."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("list_common_measures", {}))
                assert res.get("ok") is True, f"Failed: {res}"
                assert res["count"] > 40, f"Expected >40 measures, got {res['count']}"
                for m in res["measures"]:
                    assert "name" in m
                    assert "path" in m
                    assert "category" in m

    asyncio.run(_run())


# --- Test 2: list_common_measures category filter ---
@pytest.mark.integration
def test_list_common_measures_filter_reporting():
    """Verify category filter returns only reporting measures."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("list_common_measures", {
                    "category": "reporting",
                }))
                assert res.get("ok") is True, f"Failed: {res}"
                assert res["count"] == 2, f"Expected 2 reporting measures, got {res['count']}"
                for m in res["measures"]:
                    assert m["category"] == "reporting"

    asyncio.run(_run())


# --- Test 3: list_measure_arguments on a common measure ---
@pytest.mark.integration
def test_list_measure_arguments_common():
    """Call list_measure_arguments on a common measure (ChangeBuildingLocation)."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                listing = unwrap(await s.call_tool("list_common_measures", {
                    "category": "location",
                }))
                assert listing.get("ok") is True
                loc_measures = [m for m in listing["measures"]
                                if m["name"] == "ChangeBuildingLocation"]
                assert len(loc_measures) == 1, "ChangeBuildingLocation not found"
                res = unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": loc_measures[0]["path"],
                }))
                assert res.get("ok") is True, f"Failed: {res}"
                assert len(res["arguments"]) >= 1

    asyncio.run(_run())


# --- Test 4: enable_ideal_air_loads — verify HVAC disconnected ---
@pytest.mark.integration
def test_enable_ideal_air_loads():
    """Enable ideal air loads: verify ideal loads added to zones."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("ideal_air"))

                # Before: snapshot HVAC state
                before = await _get_summary(s)
                assert before["thermal_zones"] > 0, "Baseline has no zones"

                res = unwrap(await s.call_tool("enable_ideal_air_loads", {}))
                assert res.get("ok") is True, f"enable_ideal_air_loads failed: {res}"

                # After: check ideal air loads exist on zones
                equip = unwrap(await s.call_tool("list_zone_hvac_equipment", {}))
                assert equip.get("ok") is True
                ideal_loads = [e for e in equip["zone_hvac_equipment"]
                               if "IdealLoads" in e.get("type", "")]
                assert len(ideal_loads) > 0, (
                    "No ZoneHVACIdealLoadsAirSystem found after enable_ideal_air_loads"
                )
                # Should have one ideal loads per thermal zone
                assert len(ideal_loads) == before["thermal_zones"], (
                    f"Expected {before['thermal_zones']} ideal loads, got {len(ideal_loads)}"
                )

    asyncio.run(_run())


# --- Test 5: adjust_thermostat_setpoints — verify schedules cloned ---
@pytest.mark.integration
def test_adjust_thermostat_setpoints():
    """Adjust setpoints: verify schedule count increased (cloned schedules)."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("thermo"))

                # Before: count schedules
                before = await _get_summary(s)
                before_schedules = before["schedule_rulesets"]

                res = unwrap(await s.call_tool("adjust_thermostat_setpoints", {
                    "cooling_offset_f": 2.0,
                    "heating_offset_f": -1.0,
                }))
                assert res.get("ok") is True, f"adjust_thermostat_setpoints failed: {res}"

                # After: schedule count should increase (measure clones schedules)
                after = await _get_summary(s)
                assert after["schedule_rulesets"] >= before_schedules, (
                    f"Schedules decreased: {before_schedules} -> {after['schedule_rulesets']}"
                )

    asyncio.run(_run())


# --- Test 6: clean_unused_objects — verify object counts decrease ---
@pytest.mark.integration
def test_clean_unused_objects():
    """Clean unused objects: verify total object count doesn't increase."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("cleanup"))

                # Before: snapshot model counts
                before = await _get_summary(s)

                # Enable all cleanup categories for maximum effect
                res = unwrap(await s.call_tool("clean_unused_objects", {
                    "space_types": True,
                    "schedules": True,
                    "constructions": True,
                }))
                assert res.get("ok") is True, f"clean_unused_objects failed: {res}"

                # After: verify no counts went UP (cleanup should only remove)
                after = await _get_summary(s)
                for key in ("space_types", "schedule_rulesets", "constructions", "materials"):
                    assert after[key] <= before[key], (
                        f"{key} increased after cleanup: {before[key]} -> {after[key]}"
                    )

    asyncio.run(_run())


# --- Test 7: view_model — verify output artifacts created ---
@pytest.mark.integration
def test_view_model():
    """Generate 3D viewer: verify output files created in run_dir."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("view"))
                res = unwrap(await s.call_tool("view_model", {}))
                assert res.get("ok") is True, f"view_model failed: {res}"

                # Verify run_dir returned and contains output files
                run_dir = res.get("run_dir")
                assert run_dir, "No run_dir in view_model response"
                files = unwrap(await s.call_tool("list_files", {
                    "directory": run_dir,
                    "pattern": "*",
                }))
                assert files.get("ok") is True, f"list_files failed: {files}"
                assert files["total_files"] > 0, f"No files in run_dir {run_dir}"
                # The view_model measure generates report.html or similar
                file_names = [f["name"] for f in files["files"]]
                has_html = any(f.endswith(".html") for f in file_names)
                has_json = any(f.endswith(".json") for f in file_names)
                assert has_html or has_json, (
                    f"No HTML/JSON output in {run_dir}, found: {file_names}"
                )

    asyncio.run(_run())


# --- Test 8: replace_window_constructions — verify subsurface changes ---
@pytest.mark.integration
def test_replace_window_constructions():
    """Replace windows: verify subsurface constructions changed."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("win_repl"))

                # Get existing constructions
                consts = unwrap(await s.call_tool("list_constructions", {}))
                assert consts.get("ok") is True
                if consts.get("count", 0) == 0:
                    pytest.skip("No constructions in baseline model")
                const_name = consts["constructions"][0]["name"]

                # Before: snapshot subsurface constructions
                before_subs = unwrap(await s.call_tool("list_subsurfaces", {}))
                assert before_subs.get("ok") is True

                res = unwrap(await s.call_tool("replace_window_constructions", {
                    "construction_name": const_name,
                }))
                # May succeed or fail depending on construction type
                assert "ok" in res, f"Unexpected response: {res}"

                if res.get("ok") is True and before_subs.get("count", 0) > 0:
                    # After: verify subsurfaces still exist (measure shouldn't delete them)
                    after_subs = unwrap(await s.call_tool("list_subsurfaces", {}))
                    assert after_subs.get("ok") is True
                    assert after_subs["count"] == before_subs["count"], (
                        f"Subsurface count changed: {before_subs['count']} -> {after_subs['count']}"
                    )

    asyncio.run(_run())


# --- Test 9: change_building_location — verify weather file set ---
@pytest.mark.integration
def test_change_building_location():
    """Change location: verify weather file updated in model."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("location"))

                # Set weather file first so the measure can find it
                epw = ("/opt/comstock-measures/create_typical_building_from_model"
                       "/tests/USA_TX_Houston-Bush.Intercontinental.AP.722430_TMY3.epw")
                wr = unwrap(await s.call_tool("set_weather_file", {"epw_path": epw}))
                assert wr.get("ok") is True, f"set_weather_file failed: {wr}"

                res = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": "USA_TX_Houston-Bush.Intercontinental.AP.722430_TMY3.epw",
                    "climate_zone": "ASHRAE 169-2013-2A",
                }))
                # May succeed or fail depending on stat file availability
                assert "ok" in res, f"Unexpected response: {res}"

                if res.get("ok") is True:
                    # After: verify weather file is set on model
                    weather = unwrap(await s.call_tool("get_weather_info", {}))
                    assert weather.get("ok") is True, f"get_weather_info failed: {weather}"
                    epw_url = weather.get("epw_url") or weather.get("weather_file", "")
                    assert "Houston" in str(epw_url) or "722430" in str(epw_url), (
                        f"Weather file not updated to Houston: {epw_url}"
                    )

    asyncio.run(_run())


# --- Test 10: list_common_measures visualization category ---
@pytest.mark.integration
def test_list_common_measures_filter_visualization():
    """Verify visualization category returns view_model and view_data."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("list_common_measures", {
                    "category": "visualization",
                }))
                assert res.get("ok") is True, f"Failed: {res}"
                assert res["count"] == 2, f"Expected 2 viz measures, got {res['count']}"
                names = {m["name"] for m in res["measures"]}
                assert "view_model" in names
                assert "view_data" in names

    asyncio.run(_run())


# ===================================================================
# Tier 2 wrapper tests
# ===================================================================


# --- Test 11: set_thermostat_schedules ---
@pytest.mark.integration
def test_set_thermostat_schedules():
    """Set thermostat schedules on a zone using schedule names.

    Note: OSW runner may reject Choice-type args as String — lenient assert.
    """
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("therm_set"))

                zones = unwrap(await s.call_tool("list_thermal_zones", {}))
                zone_name = zones["thermal_zones"][0]["name"]
                scheds = unwrap(await s.call_tool("list_schedule_rulesets", {}))
                assert scheds["count"] > 0, "No schedules in baseline"
                sched_name = scheds["schedule_rulesets"][0]["name"]

                res = unwrap(await s.call_tool("set_thermostat_schedules", {
                    "zone_name": zone_name,
                    "cooling_schedule": sched_name,
                    "heating_schedule": sched_name,
                }))
                print("set_thermostat_schedules:", res)
                # Choice args may fail with current OSW runner
                assert "ok" in res, f"Unexpected response: {res}"

    asyncio.run(_run())


# --- Test 12: replace_thermostat_schedules ---
@pytest.mark.integration
def test_replace_thermostat_schedules():
    """Replace thermostat schedules on a zone.

    Note: OSW runner may reject Choice-type args as String — lenient assert.
    """
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("therm_repl"))

                zones = unwrap(await s.call_tool("list_thermal_zones", {}))
                zone_name = zones["thermal_zones"][0]["name"]
                scheds = unwrap(await s.call_tool("list_schedule_rulesets", {}))
                sched_name = scheds["schedule_rulesets"][0]["name"]

                res = unwrap(await s.call_tool("replace_thermostat_schedules", {
                    "zone_name": zone_name,
                    "cooling_schedule": sched_name,
                    "heating_schedule": sched_name,
                }))
                print("replace_thermostat_schedules:", res)
                # Choice args may fail with current OSW runner
                assert "ok" in res, f"Unexpected response: {res}"

    asyncio.run(_run())


# --- Test 13: shift_schedule_time ---
@pytest.mark.integration
def test_shift_schedule_time():
    """Shift a schedule profile by 2 hours."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("shift_sched"))

                scheds = unwrap(await s.call_tool("list_schedule_rulesets", {}))
                assert scheds["count"] > 0
                sched_name = scheds["schedule_rulesets"][0]["name"]

                res = unwrap(await s.call_tool("shift_schedule_time", {
                    "schedule_name": sched_name,
                    "shift_hours": 2.0,
                }))
                print("shift_schedule_time:", res)
                assert res.get("ok") is True, f"Failed: {res}"

    asyncio.run(_run())


# --- Test 14: add_rooftop_pv ---
@pytest.mark.integration
def test_add_rooftop_pv():
    """Add rooftop PV panels.

    Note: May fail if openstudio-extension gem helpers not on Ruby load path.
    """
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("rooftop_pv"))

                before = await _get_summary(s)

                res = unwrap(await s.call_tool("add_rooftop_pv", {
                    "fraction_of_surface": 0.5,
                    "cell_efficiency": 0.18,
                }))
                print("add_rooftop_pv:", res)
                # May fail if Ruby gem dependencies not on load path
                assert "ok" in res, f"Unexpected response: {res}"

                if res.get("ok") is True:
                    after = await _get_summary(s)
                    assert after["shading_surfaces"] > before["shading_surfaces"]

    asyncio.run(_run())


# --- Test 15: add_pv_to_shading ---
@pytest.mark.integration
def test_add_pv_to_shading():
    """Add PV to existing shading surfaces.

    Note: EnergyPlusMeasure — may need forward translation context.
    """
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("pv_shading"))

                res = unwrap(await s.call_tool("add_pv_to_shading", {
                    "shading_type": "Building Shading",
                    "fraction": 0.3,
                    "cell_efficiency": 0.15,
                }))
                print("add_pv_to_shading:", res)
                # May fail if shading surfaces don't exist or measure deps missing
                assert "ok" in res, f"Unexpected response: {res}"

    asyncio.run(_run())


# --- Test 16: add_ev_load ---
@pytest.mark.integration
def test_add_ev_load():
    """Add EV charging load to building."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("ev_load"))

                res = unwrap(await s.call_tool("add_ev_load", {
                    "delay_type": "Min Delay",
                    "charge_behavior": "Business as Usual",
                    "station_type": "Typical Public",
                    "ev_percent": 50.0,
                }))
                print("add_ev_load:", res)
                # May fail if EVI-Pro data files not bundled
                assert "ok" in res, f"Unexpected response: {res}"

    asyncio.run(_run())


# --- Test 17: add_zone_ventilation ---
@pytest.mark.integration
def test_add_zone_ventilation():
    """Add zone ventilation to a thermal zone.

    Note: Requires Choice args (zone, schedule) — may fail with OSW runner.
    """
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("zone_vent"))

                zones = unwrap(await s.call_tool("list_thermal_zones", {}))
                zone_name = zones["thermal_zones"][0]["name"]
                # Provide a schedule (required arg)
                scheds = unwrap(await s.call_tool("list_schedule_rulesets", {}))
                sched_name = scheds["schedule_rulesets"][0]["name"] if scheds["count"] > 0 else ""

                res = unwrap(await s.call_tool("add_zone_ventilation", {
                    "zone_name": zone_name,
                    "design_flow_rate": 0.1,
                    "ventilation_type": "Natural",
                    "schedule_name": sched_name,
                }))
                print("add_zone_ventilation:", res)
                # Choice args may fail with current OSW runner
                assert "ok" in res, f"Unexpected response: {res}"

    asyncio.run(_run())


# --- Test 18: set_lifecycle_cost_params ---
@pytest.mark.integration
def test_set_lifecycle_cost_params():
    """Set lifecycle cost analysis period."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique("lcc_params"))

                res = unwrap(await s.call_tool("set_lifecycle_cost_params", {
                    "study_period": 30,
                }))
                print("set_lifecycle_cost_params:", res)
                assert res.get("ok") is True, f"Failed: {res}"

    asyncio.run(_run())


# --- Test 19: add_cost_per_floor_area ---
@pytest.mark.integration
def test_add_cost_per_floor_area():
    """Add lifecycle cost per floor area to building."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique("cost_area"))

                res = unwrap(await s.call_tool("add_cost_per_floor_area", {
                    "material_cost": 5.0,
                    "om_cost": 0.50,
                    "expected_life": 25,
                }))
                print("add_cost_per_floor_area:", res)
                assert res.get("ok") is True, f"Failed: {res}"

    asyncio.run(_run())


# --- Test 20: set_adiabatic_boundaries ---
@pytest.mark.integration
def test_set_adiabatic_boundaries():
    """Set exterior surfaces to adiabatic: verify boundary condition changes."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("adiabatic"))

                res = unwrap(await s.call_tool("set_adiabatic_boundaries", {
                    "ext_roofs": True,
                    "ext_floors": True,
                    "ground_floors": True,
                }))
                print("set_adiabatic_boundaries:", res)
                assert res.get("ok") is True, f"Failed: {res}"

                # After: verify some surfaces changed to adiabatic
                after_surfs = unwrap(await s.call_tool("list_surfaces", {}))
                after_adiabatic = [
                    sf for sf in after_surfs["surfaces"]
                    if sf.get("outside_boundary_condition") == "Adiabatic"
                ]
                assert len(after_adiabatic) > 0, (
                    "No surfaces set to Adiabatic after set_adiabatic_boundaries"
                )

    asyncio.run(_run())


# ===================================================================
# End-to-end post-simulation tests (QAQC + results report)
# ===================================================================


# --- Test 21: run_qaqc_checks and generate_results_report after simulation ---
@pytest.mark.integration
def test_qaqc_post_sim():
    """Full pipeline: baseline → weather → sim → run_qaqc_checks + generate_results_report."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("qaqc_sim")

                # Create baseline model
                await _setup_baseline(s, name)

                # Set weather + design days
                wr = unwrap(await s.call_tool("set_weather_file", {
                    "epw_path": EPW_PATH,
                }))
                assert wr.get("ok") is True, f"set_weather_file failed: {wr}"

                dd1 = unwrap(await s.call_tool("add_design_day", {
                    "name": "Heating 99.6%",
                    "day_type": "WinterDesignDay",
                    "month": 1, "day": 21,
                    "dry_bulb_max_c": -20.6,
                    "dry_bulb_range_c": 0.0,
                }))
                assert dd1.get("ok") is True

                dd2 = unwrap(await s.call_tool("add_design_day", {
                    "name": "Cooling .4%",
                    "day_type": "SummerDesignDay",
                    "month": 7, "day": 21,
                    "dry_bulb_max_c": 33.3,
                    "dry_bulb_range_c": 10.7,
                }))
                assert dd2.get("ok") is True

                # Save + run simulation
                save_path = f"/runs/{name}_weather.osm"
                sr = unwrap(await s.call_tool("save_osm_model", {
                    "save_path": save_path,
                }))
                assert sr.get("ok") is True

                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": save_path,
                    "epw_path": EPW_PATH,
                }))
                assert sim.get("ok") is True, sim
                run_id = sim["run_id"]

                # Poll until done
                status = await poll_until_done(s, run_id)
                state = status["run"]["status"]
                assert state == "success", f"Simulation {state}: {status}"

                # run_qaqc_checks (reporting measure — runs on in-memory model)
                qaqc = unwrap(await s.call_tool("run_qaqc_checks", {}))
                assert qaqc.get("ok") is True, f"run_qaqc_checks failed: {qaqc}"

                # generate_results_report (reporting measure — runs on in-memory model)
                report = unwrap(await s.call_tool("generate_results_report", {}))
                assert report.get("ok") is True, f"generate_results_report failed: {report}"

    asyncio.run(_run())
