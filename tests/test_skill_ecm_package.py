"""Integration test for Example 20: Hackathon Deep Retrofit Package workflow.

Exercises: create baseline → simulate → apply wall insulation ECM (all exterior
walls) + thermostat widening ECM → re-simulate → compare_runs shows energy reduction.

This validates the core ECM stacking workflow described in
docs/examples/20_deep_retrofit_package.md.
"""
import asyncio
import uuid

import pytest
from conftest import EPW_PATH, integration_enabled, poll_until_done, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_skill_ecm_package_workflow():
    """Hackathon ECM package: baseline sim → wall insulation + thermostat ECMs → compare."""
    # Validates: multiple ECMs (exterior wall insulation + thermostat widening) can be
    # stacked on a baseline model and produce a measurable energy reduction vs. baseline.
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"ecm_pkg_{uuid.uuid4().hex[:8]}"

                # ----------------------------------------------------------------
                # Step 1: Create baseline model (System 3 PSZ-AC, 40% WWR)
                # ----------------------------------------------------------------
                cr = unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name,
                    "ashrae_sys_num": "03",
                    "wwr": 0.4,
                }))
                assert cr["ok"] is True, f"create_baseline_osm failed: {cr}"

                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr["ok"] is True

                # Step 2: Set weather + design days (Boston TMY3)
                wr = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW_PATH,
                }))
                assert wr["ok"] is True, f"change_building_location failed: {wr}"

                # Step 3: Save baseline and simulate
                baseline_path = f"/runs/{name}_baseline.osm"
                sr = unwrap(await s.call_tool("save_osm_model", {
                    "osm_path": baseline_path,
                }))
                assert sr["ok"] is True

                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": baseline_path,
                    "epw_path": EPW_PATH,
                }))
                assert sim["ok"] is True, f"baseline run_simulation failed: {sim}"
                baseline_run_id = sim["run_id"]

                status = await poll_until_done(s, baseline_run_id)
                assert status["run"]["status"] == "success", f"Baseline sim failed: {status}"

                # Step 4: Verify baseline has annual results (required for compare_runs)
                baseline_metrics = unwrap(await s.call_tool("extract_summary_metrics", {
                    "run_id": baseline_run_id,
                }))
                assert baseline_metrics["ok"] is True
                b_metrics = baseline_metrics.get("metrics", baseline_metrics)
                baseline_eui = b_metrics.get("eui_kBtu_ft2")
                assert baseline_eui is not None, (
                    "Baseline simulation must produce annual EUI results; "
                    f"got metrics keys: {list(b_metrics.keys())}"
                )
                assert baseline_eui > 0, f"Baseline EUI should be positive, got {baseline_eui}"

                # ----------------------------------------------------------------
                # ECM 1: High-R wall insulation
                # Create R-20 (IP) single-layer construction:
                #   R-20 IP = 3.52 m²·K/W → thickness = R×k = 3.52×0.04 = 0.141 m
                # ----------------------------------------------------------------
                mat = unwrap(await s.call_tool("create_standard_opaque_material", {
                    "name": "R20_Insulation",
                    "thickness_m": 0.141,
                    "conductivity_w_m_k": 0.04,
                    "density_kg_m3": 30.0,
                    "specific_heat_j_kg_k": 1000.0,
                }))
                assert mat["ok"] is True, f"create_standard_opaque_material failed: {mat}"

                con = unwrap(await s.call_tool("create_construction", {
                    "name": "High_R_Wall",
                    "material_names": ["R20_Insulation"],
                }))
                assert con["ok"] is True, f"create_construction failed: {con}"

                # Verify the construction R-value before applying:
                # R-20 IP = 3.52 m²·K/W → thickness=0.141 m, k=0.04 W/m·K
                con_details = unwrap(await s.call_tool("get_construction_details", {
                    "construction_name": "High_R_Wall",
                }))
                assert con_details["ok"] is True
                layers = con_details["construction"]["layers"]
                assert len(layers) == 1, f"Expected 1 layer, got {len(layers)}"
                layer = layers[0]
                assert abs(layer["thickness_m"] - 0.141) < 0.001, (
                    f"R-20 insulation thickness should be ~0.141 m, got {layer['thickness_m']}"
                )
                assert abs(layer["conductivity_w_m_k"] - 0.04) < 0.001, (
                    f"R-20 insulation conductivity should be 0.04 W/m·K, got {layer['conductivity_w_m_k']}"
                )

                # Find all exterior walls and apply new construction
                surfs = unwrap(await s.call_tool("list_surfaces", {
                    "surface_type": "Wall",
                    "boundary": "Outdoors",
                    "max_results": 0,
                }))
                assert surfs["ok"] is True
                ext_walls = surfs["surfaces"]
                assert len(ext_walls) > 0, "Baseline model must have exterior walls"

                for wall in ext_walls:
                    assign = unwrap(await s.call_tool("assign_construction_to_surface", {
                        "surface_name": wall["name"],
                        "construction_name": "High_R_Wall",
                    }))
                    assert assign["ok"] is True, (
                        f"assign_construction_to_surface failed for '{wall['name']}': {assign}"
                    )

                # Spot-check: verify the first wall's construction actually changed
                spot_check = unwrap(await s.call_tool("get_surface_details", {
                    "surface_name": ext_walls[0]["name"],
                }))
                assert spot_check["ok"] is True
                assert spot_check["surface"]["construction"] == "High_R_Wall", (
                    f"Wall '{ext_walls[0]['name']}' construction not updated: "
                    f"got '{spot_check['surface']['construction']}'"
                )

                # ----------------------------------------------------------------
                # ECM 2: Thermostat deadband widening
                # Capture cooling schedule name before and after to confirm the
                # measure cloned and modified the schedules (not a no-op).
                # ----------------------------------------------------------------
                zones_before = unwrap(await s.call_tool("list_thermal_zones", {
                    "detailed": True,
                    "max_results": 1,
                }))
                assert zones_before["ok"] is True
                assert len(zones_before["thermal_zones"]) > 0
                clg_sched_before = zones_before["thermal_zones"][0].get("cooling_setpoint_schedule")

                ecm2 = unwrap(await s.call_tool("adjust_thermostat_setpoints", {
                    "cooling_offset_f": 2.0,
                    "heating_offset_f": -2.0,
                }))
                assert ecm2["ok"] is True, f"adjust_thermostat_setpoints failed: {ecm2}"

                zones_after = unwrap(await s.call_tool("list_thermal_zones", {
                    "detailed": True,
                    "max_results": 1,
                }))
                assert zones_after["ok"] is True
                clg_sched_after = zones_after["thermal_zones"][0].get("cooling_setpoint_schedule")
                # The measure clones schedules — the name must change
                if clg_sched_before is not None:
                    assert clg_sched_after != clg_sched_before, (
                        f"Thermostat cooling schedule was not updated by ECM 2: "
                        f"schedule name unchanged ('{clg_sched_before}')"
                    )

                # ----------------------------------------------------------------
                # Step 5: Save retrofit model and simulate
                # ----------------------------------------------------------------
                retrofit_path = f"/runs/{name}_retrofit.osm"
                sr2 = unwrap(await s.call_tool("save_osm_model", {
                    "osm_path": retrofit_path,
                }))
                assert sr2["ok"] is True

                sim2 = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": retrofit_path,
                    "epw_path": EPW_PATH,
                }))
                assert sim2["ok"] is True, f"retrofit run_simulation failed: {sim2}"
                retrofit_run_id = sim2["run_id"]

                status2 = await poll_until_done(s, retrofit_run_id)
                assert status2["run"]["status"] == "success", f"Retrofit sim failed: {status2}"

                # ----------------------------------------------------------------
                # Step 6: Compare runs — ECMs should reduce energy
                # ----------------------------------------------------------------
                comparison = unwrap(await s.call_tool("compare_runs", {
                    "baseline_run_id": baseline_run_id,
                    "retrofit_run_id": retrofit_run_id,
                }))
                assert comparison["ok"] is True, f"compare_runs failed: {comparison}"
                # Verify compare_runs used the correct run IDs
                assert comparison["baseline"]["run_id"] == baseline_run_id
                assert comparison["retrofit"]["run_id"] == retrofit_run_id
                # ECM package should reduce EUI — delta must be negative
                delta_eui = comparison.get("delta_eui_kBtu_ft2")
                assert delta_eui is not None, (
                    "compare_runs must produce a delta_eui_kBtu_ft2 when both runs have annual results"
                )
                assert delta_eui < 0, (
                    f"ECM package should reduce EUI: delta_eui={delta_eui:.2f} kBtu/ft² "
                    f"(expected negative)"
                )

                # Retrofit EUI must be lower than baseline (both ECMs reduce energy)
                retro_metrics = unwrap(await s.call_tool("extract_summary_metrics", {
                    "run_id": retrofit_run_id,
                }))
                assert retro_metrics["ok"] is True
                r_metrics = retro_metrics.get("metrics", retro_metrics)
                retrofit_eui = r_metrics.get("eui_kBtu_ft2")
                assert retrofit_eui is not None, (
                    "Retrofit simulation must produce annual EUI results; "
                    f"got metrics keys: {list(r_metrics.keys())}"
                )
                # Consistent with compare_runs delta (within floating-point tolerance)
                assert retrofit_eui < baseline_eui, (
                    f"ECM package should reduce EUI: "
                    f"baseline={baseline_eui:.2f}, retrofit={retrofit_eui:.2f} kBtu/ft²"
                )

    asyncio.run(_run())
