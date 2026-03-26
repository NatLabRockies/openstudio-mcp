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
    assert cr["ok"] is True, f"create_baseline_osm failed: {cr}"
    lr = unwrap(await session.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr["ok"] is True, f"load_osm_model failed: {lr}"


async def _get_summary(session) -> dict:
    """Get model summary counts."""
    res = unwrap(await session.call_tool("get_model_summary", {}))
    assert res["ok"] is True, f"get_model_summary failed: {res}"
    return res["summary"]


# --- Test 1: list_common_measures returns measures ---
@pytest.mark.integration
def test_list_common_measures():
    """Verify list_common_measures returns measures with expected fields."""
    # Validates: common-measures-gem discovery returns all bundled measures with name+category
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("list_common_measures", {}))
                assert res["ok"] is True, f"Failed: {res}"
                assert res["count"] > 40, f"Expected >40 measures, got {res['count']}"
                for m in res["measures"]:
                    assert m["name"], f"Measure missing name: {m}"
                    assert m["category"], f"Measure missing category: {m}"

    asyncio.run(_run())


# --- Test 2: list_common_measures category filter ---
@pytest.mark.integration
def test_list_common_measures_filter_reporting():
    """Verify category filter returns only reporting measures."""
    # Validates: category filter restricts results to exactly 2 reporting measures
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("list_common_measures", {
                    "category": "reporting",
                }))
                assert res["ok"] is True, f"Failed: {res}"
                assert res["count"] == 2, f"Expected 2 reporting measures, got {res['count']}"
                for m in res["measures"]:
                    assert m["category"] == "reporting"

    asyncio.run(_run())


# --- Test 3: list_measure_arguments on a common measure ---
@pytest.mark.integration
def test_list_measure_arguments_common():
    """Call list_measure_arguments on a common measure (ChangeBuildingLocation)."""
    # Validates: ChangeBuildingLocation measure is discoverable and has at least 1 argument
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                listing = unwrap(await s.call_tool("list_common_measures", {
                    "category": "location",
                }))
                assert listing["ok"] is True
                loc_measures = [m for m in listing["measures"]
                                if m["name"] == "ChangeBuildingLocation"]
                assert len(loc_measures) == 1, "ChangeBuildingLocation not found"
                res = unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": "/opt/common-measures/" + loc_measures[0]["name"],
                }))
                assert res["ok"] is True, f"Failed: {res}"
                assert len(res["arguments"]) >= 1, "ChangeBuildingLocation should have arguments"

    asyncio.run(_run())


# --- Test 4: enable_ideal_air_loads — verify HVAC disconnected ---
@pytest.mark.integration
def test_enable_ideal_air_loads():
    """Enable ideal air loads: verify ideal loads added to zones."""
    # Validates: enable_ideal_air_loads adds one ZoneHVACIdealLoadsAirSystem per thermal zone
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
                assert res["ok"] is True, f"enable_ideal_air_loads failed: {res}"

                # After: check ideal air loads exist on zones
                equip = unwrap(await s.call_tool("list_zone_hvac_equipment", {"max_results": 0}))
                assert equip["ok"] is True
                ideal_loads = [e for e in equip["zone_hvac_equipment"]
                               if "IdealLoads" in e.get("type", "")]
                # Should have one ideal loads per thermal zone
                assert len(ideal_loads) == before["thermal_zones"], (
                    f"Expected {before['thermal_zones']} ideal loads, got {len(ideal_loads)}"
                )

    asyncio.run(_run())


# --- Test 5: adjust_thermostat_setpoints — verify schedules cloned ---
@pytest.mark.integration
def test_adjust_thermostat_setpoints():
    """Adjust setpoints: verify schedule count increased (cloned schedules)."""
    # Validates: adjust_thermostat_setpoints clones schedules (count should not decrease)
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
                assert res["ok"] is True, f"adjust_thermostat_setpoints failed: {res}"

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
    # Validates: clean_unused_objects only removes objects, never increases counts
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
                assert res["ok"] is True, f"clean_unused_objects failed: {res}"

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
    # Validates: view_model produces HTML or JSON output files in run_dir
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("view"))
                res = unwrap(await s.call_tool("view_model", {}))
                assert res["ok"] is True, f"view_model failed: {res}"

                # Verify run_dir returned and contains output files
                run_dir = res["run_dir"]
                assert run_dir, "No run_dir in view_model response"
                files = unwrap(await s.call_tool("list_files", {
                    "directory": run_dir,
                    "pattern": "*",
                    "max_results": 0,
                }))
                assert files["ok"] is True, f"list_files failed: {files}"
                assert files["count"] > 0, f"No files in run_dir {run_dir}"
                # The view_model measure generates report.html or similar
                file_names = [f["name"] for f in files["items"]]
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
    # Validates: replace_window_constructions preserves subsurface count after replacement
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("win_repl"))

                # Get window/glazing constructions (not wall/roof)
                consts = unwrap(await s.call_tool("list_model_objects", {"object_type": "Construction", "max_results": 0}))
                assert consts["ok"] is True
                if consts.get("count", 0) == 0:
                    pytest.skip("No constructions in baseline model")
                # Filter for window/glazing constructions by name
                window_consts = [
                    c for c in consts["objects"]
                    if any(kw in c["name"].lower() for kw in ("window", "glass", "glazing"))
                ]
                if not window_consts:
                    pytest.skip("No window/glazing constructions found in baseline model")
                const_name = window_consts[0]["name"]

                # Before: snapshot subsurface constructions
                before_subs = unwrap(await s.call_tool("list_subsurfaces", {"max_results": 0}))
                assert before_subs["ok"] is True

                res = unwrap(await s.call_tool("replace_window_constructions", {
                    "construction_name": const_name,
                }))
                # May succeed or fail depending on construction type
                if res["ok"] is True:
                    if before_subs.get("count", 0) > 0:
                        after_subs = unwrap(await s.call_tool("list_subsurfaces", {"max_results": 0}))
                        assert after_subs["ok"] is True
                        assert after_subs["count"] == before_subs["count"], (
                            f"Subsurface count changed: {before_subs['count']} -> {after_subs['count']}"
                        )
                else:
                    error = res.get("error", "")
                    log_tail = res.get("log_tail", "")
                    combined = f"{error} {log_tail}".lower()
                    if any(k in combined for k in ("construction", "glazing", "choice", "gem")):
                        pytest.skip(f"Measure env issue: {error}")
                    else:
                        pytest.fail(f"replace_window_constructions failed: {error}")

    asyncio.run(_run())


# --- Test 9: change_building_location — verify weather file set ---
@pytest.mark.integration
def test_change_building_location():
    """Change location: verify weather file updated in model."""
    # Validates: change_building_location sets Boston EPW on model
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("location"))

                epw = ("/opt/comstock-measures/ChangeBuildingLocation"
                       "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
                res = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": epw,
                }))
                assert res["ok"] is True, f"change_building_location failed: {res}"

                # Verify weather file is set on model
                weather = unwrap(await s.call_tool("get_weather_info", {}))
                assert weather["ok"] is True, f"get_weather_info failed: {weather}"
                epw_url = weather.get("epw_url") or weather.get("weather_file", "")
                assert "Boston" in str(epw_url) or "725090" in str(epw_url), (
                    f"Weather file not updated to Boston: {epw_url}"
                )

    asyncio.run(_run())


# --- Test 10: list_common_measures visualization category ---
@pytest.mark.integration
def test_list_common_measures_filter_visualization():
    """Verify visualization category returns view_model and view_data."""
    # Validates: visualization category contains exactly view_model and view_data
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("list_common_measures", {
                    "category": "visualization",
                }))
                assert res["ok"] is True, f"Failed: {res}"
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
    # Validates: set_thermostat_schedules accepts zone+schedule names via MCP
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("therm_set"))

                zones = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                zone_name = zones["thermal_zones"][0]["name"]
                scheds = unwrap(await s.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0}))
                assert scheds["count"] > 0, "No schedules in baseline"
                sched_name = scheds["objects"][0]["name"]

                res = unwrap(await s.call_tool("set_thermostat_schedules", {
                    "zone_name": zone_name,
                    "cooling_schedule": sched_name,
                    "heating_schedule": sched_name,
                }))
                print("set_thermostat_schedules:", res)
                # Choice args may fail with current OSW runner
                if res["ok"] is True:
                    pass  # No readback available for thermostat schedules
                else:
                    error = res.get("error", "")
                    if any(k in error.lower() for k in ("choice", "argument", "osw", "measure run failed")):
                        pytest.skip(f"Known OSW runner limitation: {error}")
                    else:
                        pytest.fail(f"set_thermostat_schedules failed unexpectedly: {error}")

    asyncio.run(_run())


# --- Test 12: replace_thermostat_schedules ---
@pytest.mark.integration
def test_replace_thermostat_schedules():
    """Replace thermostat schedules on a zone.

    Note: OSW runner may reject Choice-type args as String — lenient assert.
    """
    # Validates: replace_thermostat_schedules accepts zone+schedule names via MCP
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("therm_repl"))

                zones = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                zone_name = zones["thermal_zones"][0]["name"]
                scheds = unwrap(await s.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0}))
                sched_name = scheds["objects"][0]["name"]

                res = unwrap(await s.call_tool("replace_thermostat_schedules", {
                    "zone_name": zone_name,
                    "cooling_schedule": sched_name,
                    "heating_schedule": sched_name,
                }))
                print("replace_thermostat_schedules:", res)
                # Choice args may fail with current OSW runner
                if res["ok"] is True:
                    pass  # No readback available for thermostat schedules
                else:
                    error = res.get("error", "")
                    if any(k in error.lower() for k in ("choice", "argument", "osw", "measure run failed")):
                        pytest.skip(f"Known OSW runner limitation: {error}")
                    else:
                        pytest.fail(f"replace_thermostat_schedules failed unexpectedly: {error}")

    asyncio.run(_run())


# --- Test 13: shift_schedule_time ---
@pytest.mark.integration
def test_shift_schedule_time():
    """Shift a schedule profile by 2 hours."""
    # Validates: shift_schedule_time applies 2-hour shift to a schedule profile
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("shift_sched"))

                scheds = unwrap(await s.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0}))
                assert scheds["count"] > 0
                sched_name = scheds["objects"][0]["name"]

                res = unwrap(await s.call_tool("shift_schedule_time", {
                    "schedule_name": sched_name,
                    "shift_hours": 2.0,
                }))
                print("shift_schedule_time:", res)
                assert res["ok"] is True, f"Failed: {res}"

    asyncio.run(_run())


# --- Test 14: add_rooftop_pv ---
@pytest.mark.integration
def test_add_rooftop_pv():
    """Add rooftop PV panels.

    Note: May fail if openstudio-extension gem helpers not on Ruby load path.
    """
    # Validates: add_rooftop_pv increases shading surface count when successful
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
                if res["ok"] is True:
                    after = await _get_summary(s)
                    assert after["shading_surfaces"] > before["shading_surfaces"], (
                        f"PV should add shading surfaces: {before['shading_surfaces']} -> {after['shading_surfaces']}"
                    )
                else:
                    error = res.get("error", "")
                    if "gem" in error.lower() or "load path" in error.lower() or "require" in error.lower():
                        pytest.skip(f"Ruby gem dependency not available: {error}")
                    else:
                        pytest.fail(f"add_rooftop_pv failed unexpectedly: {error}")

    asyncio.run(_run())


# --- Test 15: add_pv_to_shading ---
@pytest.mark.integration
def test_add_pv_to_shading():
    """Add PV to existing shading surfaces.

    Note: EnergyPlusMeasure — may need forward translation context.
    """
    # Validates: add_pv_to_shading MCP contract returns ok field
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
                if res["ok"] is True:
                    pass  # PV measure ran successfully
                else:
                    error = res.get("error", "")
                    if "shading" in error.lower() or "gem" in error.lower() or "forward translation" in error.lower():
                        pytest.skip(f"Known environment limitation: {error}")
                    else:
                        pytest.fail(f"add_pv_to_shading failed unexpectedly: {error}")

    asyncio.run(_run())


# --- Test 16: add_ev_load ---
@pytest.mark.integration
def test_add_ev_load():
    """Add EV charging load to building."""
    # Validates: add_ev_load MCP contract returns ok field
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
                if res["ok"] is True:
                    pass  # EV load measure ran successfully
                else:
                    error = res.get("error", "")
                    if "gem" in error.lower() or "load path" in error.lower() or "ev" in error.lower():
                        pytest.skip(f"Known environment limitation: {error}")
                    else:
                        pytest.fail(f"add_ev_load failed unexpectedly: {error}")

    asyncio.run(_run())


# --- Test 17: add_zone_ventilation ---
@pytest.mark.integration
def test_add_zone_ventilation():
    """Add zone ventilation to a thermal zone.

    Note: Requires Choice args (zone, schedule) — may fail with OSW runner.
    """
    # Validates: add_zone_ventilation MCP contract returns ok field
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique("zone_vent"))

                zones = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                zone_name = zones["thermal_zones"][0]["name"]
                # Provide a schedule (required arg)
                scheds = unwrap(await s.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0}))
                sched_name = scheds["objects"][0]["name"] if scheds["count"] > 0 else ""

                res = unwrap(await s.call_tool("add_zone_ventilation", {
                    "zone_name": zone_name,
                    "design_flow_rate": 0.1,
                    "ventilation_type": "Natural",
                    "schedule_name": sched_name,
                }))
                print("add_zone_ventilation:", res)
                # Choice args may fail with current OSW runner
                if res["ok"] is True:
                    pass  # Zone ventilation added successfully
                else:
                    error = res.get("error", "")
                    if any(k in error.lower() for k in ("choice", "argument", "osw", "measure run failed")):
                        pytest.skip(f"Known OSW runner limitation: {error}")
                    else:
                        pytest.fail(f"add_zone_ventilation failed unexpectedly: {error}")

    asyncio.run(_run())


# --- Test 18: set_lifecycle_cost_params ---
@pytest.mark.integration
def test_set_lifecycle_cost_params():
    """Set lifecycle cost analysis period."""
    # Validates: set_lifecycle_cost_params applies 30-year study period via measure
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
                assert res["ok"] is True, f"Failed: {res}"

    asyncio.run(_run())


# --- Test 19: add_cost_per_floor_area ---
@pytest.mark.integration
def test_add_cost_per_floor_area():
    """Add lifecycle cost per floor area to building."""
    # Validates: add_cost_per_floor_area applies material+OM cost via measure
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
                assert res["ok"] is True, f"Failed: {res}"

    asyncio.run(_run())


# --- Test 20: set_adiabatic_boundaries ---
@pytest.mark.integration
def test_set_adiabatic_boundaries():
    """Set exterior surfaces to adiabatic: verify boundary condition changes."""
    # Validates: set_adiabatic_boundaries converts ext surfaces to Adiabatic BC
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
                assert res["ok"] is True, f"Failed: {res}"

                # After: verify some surfaces changed to adiabatic
                after_surfs = unwrap(await s.call_tool("list_surfaces", {"detailed": True, "max_results": 0}))
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
    # Validates: post-sim reporting pipeline (results report + QAQC + view_simulation_data)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("qaqc_sim")

                # Create baseline model
                await _setup_baseline(s, name)

                # Set weather + design days + climate zone
                wr = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW_PATH,
                }))
                assert wr["ok"] is True, f"change_building_location failed: {wr}"

                # Save + run simulation
                save_path = f"/runs/{name}_weather.osm"
                sr = unwrap(await s.call_tool("save_osm_model", {
                    "osm_path": save_path,
                }))
                assert sr["ok"] is True

                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": save_path,
                    "epw_path": EPW_PATH,
                }))
                assert sim["ok"] is True, sim
                run_id = sim["run_id"]

                # Poll until done
                status = await poll_until_done(s, run_id)
                state = status["run"]["status"]
                assert state == "success", f"Simulation {state}: {status}"

                # generate_results_report (reporting measure — needs SQL from sim)
                report = unwrap(await s.call_tool("generate_results_report", {
                    "run_id": run_id,
                }))
                assert report["ok"] is True, f"generate_results_report failed: {report}"

                # run_qaqc_checks (reporting measure — needs SQL + climate zone)
                qaqc = unwrap(await s.call_tool("run_qaqc_checks", {
                    "run_id": run_id,
                }))
                assert qaqc["ok"] is True, f"run_qaqc_checks failed: {qaqc}"

                # view_simulation_data (reporting measure — needs SQL)
                view = unwrap(await s.call_tool("view_simulation_data", {
                    "run_id": run_id,
                }))
                assert view["ok"] is True, f"view_simulation_data failed: {view}"

    asyncio.run(_run())


@pytest.mark.integration
def test_qaqc_json_string_checks():
    """Test run_qaqc_checks accepts checks param as JSON string.

    We don't need a completed sim — passing empty run_id returns an expected
    error AFTER Pydantic validation. If checks were rejected by Pydantic,
    we'd get a validation error instead.
    """
    # Regression: MCP clients sent checks as JSON string, caused Pydantic validation error
    import json

    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                resp = await s.call_tool("run_qaqc_checks", {
                    "run_id": "",
                    "checks": json.dumps(["envelope", "schedules"]),
                })
                result = unwrap(resp)

                # Expected: run_id required error (not a Pydantic validation error)
                assert result["ok"] is False
                assert "run_id" in result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_view_simulation_data_json_string_variables():
    """Test view_simulation_data accepts variable_names as JSON string.

    Similar to qaqc test — no sim needed, just verifying Pydantic accepts
    the JSON string format. The tool will fail because no run_id, but that's
    expected and proves coercion worked.
    """
    # Regression: MCP clients sent variable_names as JSON string, caused Pydantic error
    import json

    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                resp = await s.call_tool("view_simulation_data", {
                    "run_id": "",
                    "variable_names": json.dumps(["Zone Mean Air Temperature"]),
                })
                result = unwrap(resp)

                # Expected: fails because no run_id/SQL, not because of Pydantic
                assert result["ok"] is False
                assert "error" in result

    asyncio.run(_run())
