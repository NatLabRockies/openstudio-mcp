"""End-to-end workflow tests matching README examples.

Each test exercises a multi-step workflow that a real user would perform
through an MCP host. These verify that tool sequences compose correctly.

Tests 1 and 7 run actual EnergyPlus simulations (several minutes each).
Test 5 uses a minimal custom measure from tests/assets/measures/set_building_name/.
"""
import asyncio
import uuid

import pytest
from conftest import EPW_PATH, integration_enabled, poll_until_done, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_wf") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


MEASURE_DIR = "/repo/tests/assets/measures/set_building_name"


# ---------------------------------------------------------------------------
# Example 1: Baseline Model Creation + Weather + Simulation
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_workflow_baseline_with_weather():
    """Example 1: Create baseline model, set weather, run simulation, extract metrics."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("baseline_wf")

                # Step 1: Create baseline model (System 3 = PSZ-AC)
                cr = unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "03",
                }))
                assert cr.get("ok") is True, cr

                # Step 2: Load model
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # Step 3: Set weather + design days + climate zone
                wr = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW_PATH,
                }))
                assert wr.get("ok") is True

                # Step 4: Verify weather info
                wi = unwrap(await s.call_tool("get_weather_info", {}))
                assert wi.get("ok") is True
                assert wi["weather_file"]["city"] != ""

                # Step 5: Add design days (required for HVAC sizing)
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

                # Step 6: Save model
                save_path = f"/runs/{name}_with_weather.osm"
                sr = unwrap(await s.call_tool("save_osm_model", {
                    "osm_path": save_path,
                }))
                assert sr.get("ok") is True

                # Step 7: Run EnergyPlus simulation
                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": save_path,
                    "epw_path": EPW_PATH,
                }))
                assert sim.get("ok") is True, sim
                run_id = sim["run_id"]

                # Step 8: Poll until done
                status = await poll_until_done(s, run_id)
                state = status["run"]["status"]
                assert state == "success", f"Simulation {state}: {status}"

                # Step 9: Extract metrics (may be None if no RunPeriod — sizing-only)
                metrics = unwrap(await s.call_tool("extract_summary_metrics", {
                    "run_id": run_id,
                }))
                assert metrics.get("ok") is True

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Example 2: HVAC Design Exploration (DOAS + component tuning)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_workflow_hvac_design_exploration():
    """Example 2: DOAS system with plant loop sizing adjustments."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("doas_wf")

                # Step 1: Create baseline model (gives us zones)
                cr = unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "07",
                }))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # Step 2: Get zone names
                zones = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                assert zones.get("ok") is True
                zone_names = [z["name"] for z in zones["thermal_zones"][:3]]

                # Step 3: List plant loops (System 7 has chilled water + hot water)
                pl = unwrap(await s.call_tool("list_plant_loops", {}))
                assert pl.get("ok") is True
                assert pl["count"] >= 2

                # Step 4: Get plant loop details
                for loop in pl["plant_loops"][:2]:
                    details = unwrap(await s.call_tool("get_plant_loop_details", {
                        "plant_loop_name": loop["name"],
                    }))
                    assert details.get("ok") is True

                # Step 5: List HVAC components to find a boiler
                comps = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "BoilerHotWater", "max_results": 0,
                }))
                assert comps.get("ok") is True
                # All results are boilers (filtered by object_type)
                boilers = comps["objects"]
                if boilers:
                    # Step 6: Get and modify boiler properties
                    bp = unwrap(await s.call_tool("get_component_properties", {
                        "component_name": boilers[0]["name"],
                    }))
                    assert bp.get("ok") is True

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Example 3: Envelope Retrofit (materials + constructions + assignment)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_workflow_envelope_retrofit():
    """Example 3: Create insulation material, build construction, assign to wall."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("envelope_wf")

                # Step 1: Create and load example model
                cr = unwrap(await s.call_tool("create_example_osm", {"name": name}))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
                assert lr.get("ok") is True

                # Step 2: List current constructions
                cons = unwrap(await s.call_tool("list_constructions", {"max_results": 0}))
                assert cons.get("ok") is True

                # Step 3: List surfaces to find an exterior wall
                surfs = unwrap(await s.call_tool("list_surfaces", {"max_results": 0}))
                assert surfs.get("ok") is True
                walls = [s for s in surfs["surfaces"] if s.get("surface_type") == "Wall"
                         and s.get("outside_boundary_condition") == "Outdoors"]
                # If no exterior walls, use any wall
                if not walls:
                    walls = [s for s in surfs["surfaces"] if s.get("surface_type") == "Wall"]
                assert len(walls) > 0, "No walls found"
                wall_name = walls[0]["name"]

                # Step 4: Create insulation material
                mat = unwrap(await s.call_tool("create_standard_opaque_material", {
                    "name": "R20_Insulation",
                    "thickness_m": 0.089,
                    "conductivity_w_m_k": 0.04,
                    "density_kg_m3": 30.0,
                    "specific_heat_j_kg_k": 1000.0,
                }))
                assert mat.get("ok") is True

                # Step 5: Create construction using the material
                con = unwrap(await s.call_tool("create_construction", {
                    "name": "High_R_Wall",
                    "material_names": ["R20_Insulation"],
                }))
                assert con.get("ok") is True

                # Step 6: Assign to the wall
                assign = unwrap(await s.call_tool("assign_construction_to_surface", {
                    "surface_name": wall_name,
                    "construction_name": "High_R_Wall",
                }))
                assert assign.get("ok") is True

                # Step 7: Verify assignment via surface details
                detail = unwrap(await s.call_tool("get_surface_details", {
                    "surface_name": wall_name,
                }))
                assert detail.get("ok") is True
                assert detail["surface"]["construction"] == "High_R_Wall"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Example 4: Internal Loads Setup
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_workflow_internal_loads():
    """Example 4: Add people, lights, equipment to a space with schedule."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("loads_wf")

                # Step 1: Create and load example model
                cr = unwrap(await s.call_tool("create_example_osm", {"name": name}))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
                assert lr.get("ok") is True

                # Find a space
                spaces = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                space_name = spaces["spaces"][0]["name"]

                # Step 2: Create occupancy schedule
                sched = unwrap(await s.call_tool("create_schedule_ruleset", {
                    "name": "Office_Occ",
                    "schedule_type": "Fractional",
                    "default_value": 0.5,
                }))
                assert sched.get("ok") is True

                # Step 3: Create people load
                people = unwrap(await s.call_tool("create_people_definition", {
                    "name": "Office People",
                    "space_name": space_name,
                    "people_per_area": 0.059,
                    "schedule_name": "Office_Occ",
                }))
                assert people.get("ok") is True

                # Step 4: Create lights
                lights = unwrap(await s.call_tool("create_lights_definition", {
                    "name": "Office Lights",
                    "space_name": space_name,
                    "watts_per_area": 10.76,
                }))
                assert lights.get("ok") is True

                # Step 5: Create electric equipment
                equip = unwrap(await s.call_tool("create_electric_equipment", {
                    "name": "Office Plugs",
                    "space_name": space_name,
                    "watts_per_area": 1.076,
                }))
                assert equip.get("ok") is True

                # Step 6: Verify loads are present
                pl = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "People", "max_results": 0,
                }))
                assert pl.get("ok") is True
                assert any("Office People" in p.get("name", "") for p in pl["objects"])

                ll = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "Lights", "max_results": 0,
                }))
                assert ll.get("ok") is True
                assert any("Office Lights" in l.get("name", "") for l in ll["objects"])

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Example 5: Apply Measure
# Uses tests/assets/measures/set_building_name/ — a minimal custom Ruby
# measure created for testing (Phase 6D). It has one String argument
# "building_name" and calls model.getBuilding.setName() in measure.rb.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_workflow_apply_measure():
    """Example 5: List measure arguments, apply with custom value, verify."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("measure_wf")

                # Step 1: Create and load model
                cr = unwrap(await s.call_tool("create_example_osm", {"name": name}))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
                assert lr.get("ok") is True

                # Step 2: List measure arguments
                args = unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": MEASURE_DIR,
                }))
                assert args.get("ok") is True
                assert len(args["arguments"]) >= 1

                # Step 3: Apply measure with custom building name
                new_name = f"Workflow Test {uuid.uuid4().hex[:6]}"
                apply = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                    "arguments": {"building_name": new_name},
                }))
                assert apply.get("ok") is True

                # Step 4: Verify building name changed
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg.get("ok") is True
                assert bldg["building"]["name"] == new_name

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Example 6: Model Cleanup (rename + delete)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_workflow_model_cleanup():
    """Example 6: Rename zone, delete space, verify changes."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("cleanup_wf")

                # Step 1: Create and load model
                cr = unwrap(await s.call_tool("create_example_osm", {"name": name}))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
                assert lr.get("ok") is True

                # Step 2: Rename the thermal zone
                zones = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                old_zone = zones["thermal_zones"][0]["name"]
                rename = unwrap(await s.call_tool("rename_object", {
                    "object_name": old_zone,
                    "new_name": "Renamed Zone WF",
                }))
                assert rename.get("ok") is True

                # Step 3: Create a temporary space and delete it
                unwrap(await s.call_tool("create_space", {"name": "TempSpace"}))
                spaces_before = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                count_before = spaces_before["count"]

                delete = unwrap(await s.call_tool("delete_object", {
                    "object_name": "TempSpace",
                }))
                assert delete.get("ok") is True

                # Step 4: Verify
                spaces_after = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                assert spaces_after["count"] == count_before - 1

                zones_after = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                assert any(z["name"] == "Renamed Zone WF" for z in zones_after["thermal_zones"])

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Example 7: Full Building — baseline + loads + weather + simulation
# Uses baseline model (has geometry+zones) then adds loads, weather,
# design days, and runs actual EnergyPlus simulation.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_workflow_full_building():
    """Example 7: Baseline model + loads + weather + design days + simulation."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("full_wf")

                # Step 1: Create baseline model with HVAC (System 5 = Packaged VAV)
                cr = unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "05",
                }))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
                assert lr.get("ok") is True

                # Step 2: Find existing spaces (baseline has geometry+zones)
                spaces = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                assert spaces.get("ok") is True
                space_name = spaces["spaces"][0]["name"]

                # Step 3: Add people to a space
                people = unwrap(await s.call_tool("create_people_definition", {
                    "name": "Office People",
                    "space_name": space_name,
                    "people_per_area": 0.059,
                }))
                assert people.get("ok") is True

                # Step 4: Add lights
                lights = unwrap(await s.call_tool("create_lights_definition", {
                    "name": "Office Lights",
                    "space_name": space_name,
                    "watts_per_area": 10.76,
                }))
                assert lights.get("ok") is True

                # Step 5: Set weather + design days + climate zone
                wf = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW_PATH,
                }))
                assert wf.get("ok") is True

                # Step 6: Save the complete model
                save_path = f"/runs/{name}_complete.osm"
                save = unwrap(await s.call_tool("save_osm_model", {
                    "osm_path": save_path,
                }))
                assert save.get("ok") is True

                # Step 8: Verify model state before simulation
                loops = unwrap(await s.call_tool("list_air_loops", {}))
                assert loops.get("ok") is True
                assert loops["count"] >= 1

                weather = unwrap(await s.call_tool("get_weather_info", {}))
                assert weather.get("ok") is True
                assert weather["weather_file"]["city"] != ""

                # Step 9: Run EnergyPlus simulation
                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": save_path,
                    "epw_path": EPW_PATH,
                }))
                assert sim.get("ok") is True, sim
                run_id = sim["run_id"]

                # Step 10: Poll until done
                status = await poll_until_done(s, run_id)
                state = status["run"]["status"]
                assert state == "success", f"Simulation {state}: {status}"

                # Step 11: Extract metrics (may be None if no RunPeriod — sizing-only)
                metrics = unwrap(await s.call_tool("extract_summary_metrics", {
                    "run_id": run_id,
                }))
                assert metrics.get("ok") is True

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Example 8: Geometry from Scratch
# Build a two-zone model using floor-print extrusion, add a window,
# assign thermal zones, and verify the geometry is correct.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_workflow_geometry_from_scratch():
    """Example 8: Create spaces from floor prints, add window, assign zones."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("geom_wf")

                # Step 1: Create and load a blank-ish example model
                cr = unwrap(await s.call_tool("create_example_osm", {"name": name}))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # Step 2: Create two thermal zones
                z1 = unwrap(await s.call_tool("create_thermal_zone", {
                    "name": "Zone West",
                }))
                assert z1.get("ok") is True
                z2 = unwrap(await s.call_tool("create_thermal_zone", {
                    "name": "Zone East",
                }))
                assert z2.get("ok") is True

                # Step 3: Create west zone — 10x10m, 3m tall
                sp1 = unwrap(await s.call_tool("create_space_from_floor_print", {
                    "name": "West Office",
                    "floor_vertices": [[0, 0], [10, 0], [10, 10], [0, 10]],
                    "floor_to_ceiling_height": 3.0,
                    "thermal_zone_name": "Zone West",
                }))
                assert sp1.get("ok") is True
                assert sp1["num_surfaces"] == 6  # 4 walls + floor + ceiling
                assert sp1["surface_types"]["Wall"] == 4

                # Step 4: Create east zone — adjacent, 10x10m, 3m tall
                sp2 = unwrap(await s.call_tool("create_space_from_floor_print", {
                    "name": "East Office",
                    "floor_vertices": [[10, 0], [20, 0], [20, 10], [10, 10]],
                    "floor_to_ceiling_height": 3.0,
                    "thermal_zone_name": "Zone East",
                }))
                assert sp2.get("ok") is True
                assert sp2["num_surfaces"] == 6

                # Step 5: Match surfaces — shared wall at x=10 becomes interior
                match = unwrap(await s.call_tool("match_surfaces", {}))
                assert match.get("ok") is True
                assert match["matched_surfaces"] >= 2  # shared wall pair

                # Step 6: List all surfaces — verify interior boundaries
                surfs = unwrap(await s.call_tool("list_surfaces", {"detailed": True, "max_results": 0}))
                assert surfs.get("ok") is True
                new_surfs = [sf for sf in surfs["surfaces"]
                             if sf["space"] in ("West Office", "East Office")]
                interior = [sf for sf in new_surfs
                            if sf["outside_boundary_condition"] == "Surface"]
                assert len(interior) >= 2  # matched pair

                # Step 7: Find an exterior wall on West Office to add glazing
                ext_walls = [sf for sf in new_surfs
                             if sf["space"] == "West Office"
                             and sf["surface_type"] == "Wall"
                             and sf["outside_boundary_condition"] == "Outdoors"]
                assert len(ext_walls) >= 1
                target_wall = ext_walls[0]["name"]

                # Step 8: Add 40% glazing using window-to-wall ratio
                wwr = unwrap(await s.call_tool("set_window_to_wall_ratio", {
                    "surface_name": target_wall,
                    "ratio": 0.4,
                }))
                assert wwr.get("ok") is True
                assert wwr["num_subsurfaces"] >= 1

                # Step 9: Verify subsurface exists
                subs = unwrap(await s.call_tool("list_subsurfaces", {"max_results": 0}))
                assert subs.get("ok") is True
                assert subs["count"] >= 1

                # Step 10: Configure simulation control for the new model
                sc = unwrap(await s.call_tool("set_simulation_control", {
                    "do_zone_sizing": True,
                    "do_system_sizing": True,
                    "run_for_sizing_periods": True,
                }))
                assert sc.get("ok") is True

                # Step 11: Set a short run period (Jan only)
                rp = unwrap(await s.call_tool("set_run_period", {
                    "begin_month": 1, "begin_day": 1,
                    "end_month": 1, "end_day": 31,
                    "name": "January Only",
                }))
                assert rp.get("ok") is True

                # Step 12: Verify model summary
                summary = unwrap(await s.call_tool("get_model_summary", {}))
                assert summary.get("ok") is True

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Example 9: Fenestration by Orientation
# Apply different window-to-wall ratios per orientation on a baseline
# model — 40% south, 25% north, 30% east/west. Common real workflow.
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_workflow_fenestration_by_orientation():
    """Example 9: Apply WWR per cardinal direction on a baseline model."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = _unique("wwr_wf")

                # Step 1: Create 10-zone baseline (has geometry already)
                cr = unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "03",
                }))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # Step 2: List all surfaces, filter to exterior walls
                surfs = unwrap(await s.call_tool("list_surfaces", {"detailed": True, "max_results": 0}))
                assert surfs.get("ok") is True
                ext_walls = [sf for sf in surfs["surfaces"]
                             if sf["surface_type"] == "Wall"
                             and sf["outside_boundary_condition"] == "Outdoors"]
                assert len(ext_walls) >= 4, f"Expected exterior walls, got {len(ext_walls)}"

                # Step 3: Bin walls by orientation (azimuth)
                # South ~180°, North ~0/360°, East ~90°, West ~270°
                def _orientation(az):
                    if 135 <= az < 225:
                        return "south"
                    elif az < 45 or az >= 315:
                        return "north"
                    elif 45 <= az < 135:
                        return "east"
                    else:
                        return "west"

                by_orient = {"south": [], "north": [], "east": [], "west": []}
                for w in ext_walls:
                    orient = _orientation(w["azimuth_deg"])
                    by_orient[orient].append(w["name"])

                # Step 4: Apply different WWR per orientation
                ratios = {"south": 0.4, "north": 0.25, "east": 0.3, "west": 0.3}
                total_windows = 0
                for orient, wall_names in by_orient.items():
                    for wn in wall_names:
                        res = unwrap(await s.call_tool("set_window_to_wall_ratio", {
                            "surface_name": wn,
                            "ratio": ratios[orient],
                        }))
                        assert res.get("ok") is True, f"WWR failed on {wn}: {res}"
                        total_windows += res["num_subsurfaces"]

                assert total_windows >= 4, f"Expected >= 4 windows, got {total_windows}"

                # Step 5: Verify subsurfaces created
                subs = unwrap(await s.call_tool("list_subsurfaces", {"max_results": 0}))
                assert subs.get("ok") is True
                assert subs["count"] == total_windows

                # Step 6: Spot-check a south wall has ~40% glazing
                if by_orient["south"]:
                    detail = unwrap(await s.call_tool("get_surface_details", {
                        "surface_name": by_orient["south"][0],
                    }))
                    assert detail.get("ok") is True
                    sf = detail["surface"]
                    # net_area = gross - window, so window ~ 0.4 * gross
                    if sf["gross_area_m2"] > 0:
                        actual_ratio = 1.0 - (sf["net_area_m2"] / sf["gross_area_m2"])
                        assert 0.35 < actual_ratio < 0.45, f"South WWR {actual_ratio:.2f}, expected ~0.40"

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Example 10: Standards-Based Typical Building via ComStock
# Apply 90.1-2019 constructions, loads, HVAC, and schedules to a model
# with geometry using the create_typical_building tool.
# ---------------------------------------------------------------------------

# ComStock bundled test assets
COMSTOCK_TEST_OSM = "/opt/comstock-measures/create_typical_building_from_model/tests/SmallOffice.osm"
COMSTOCK_TEST_EPW = (
    "/opt/comstock-measures/ChangeBuildingLocation"
    "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
)


@pytest.mark.integration
def test_workflow_comstock_typical_building():
    """Example 10: Apply 90.1-2019 typical building template, verify HVAC + constructions."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                # Step 1: Browse available ComStock setup measures
                measures = unwrap(await s.call_tool("list_comstock_measures", {
                    "category": "setup",
                }))
                assert measures.get("ok") is True, measures
                names = [m["name"] for m in measures["measures"]]
                assert "create_typical_building_from_model" in names

                # Step 2: Load ComStock bundled SmallOffice model
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": COMSTOCK_TEST_OSM,
                }))
                assert lr.get("ok") is True, lr

                # Step 3: Set weather + design days + climate zone
                wr = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": COMSTOCK_TEST_EPW,
                }))
                assert wr.get("ok") is True, wr

                # Step 4: Apply 90.1-2019 typical building template
                tb = unwrap(await s.call_tool("create_typical_building", {
                    "climate_zone": "ASHRAE 169-2013-2A",
                }))
                assert tb.get("ok") is True, tb

                # Step 5: Verify model has HVAC
                summary = unwrap(await s.call_tool("get_model_summary", {}))
                assert summary.get("ok") is True
                counts = summary.get("counts", summary.get("summary", {}))
                total_hvac = counts.get("air_loops", 0) + counts.get("zone_hvac_equipment", 0)
                assert total_hvac > 0, f"Expected HVAC, got counts: {counts}"

                # Step 6: List air loops
                loops = unwrap(await s.call_tool("list_air_loops", {}))
                assert loops.get("ok") is True
                assert loops["count"] > 0, "Expected air loops after typical building"

                # Step 7: List constructions
                cons = unwrap(await s.call_tool("list_constructions", {"max_results": 0}))
                assert cons.get("ok") is True
                assert cons["count"] > 0, "Expected constructions after typical building"

                # Step 8: Save model
                save_path = f"/runs/typical_office_{uuid.uuid4().hex[:8]}.osm"
                sr = unwrap(await s.call_tool("save_osm_model", {
                    "osm_path": save_path,
                }))
                assert sr.get("ok") is True

    asyncio.run(_run())
