"""Integration test for /simulate skill workflow.

Exercises: create baseline → load → set weather → add design days →
save → run_simulation → poll → extract_summary_metrics + end_use_breakdown.
"""
import asyncio
import uuid

import pytest
from conftest import EPW_PATH, integration_enabled, poll_until_done, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_skill_simulate_workflow():
    """/simulate skill: baseline → weather → simulate → extract results."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_sim_{uuid.uuid4().hex[:8]}"

                # 1. Create and load baseline model
                cr = unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "03",
                }))
                assert cr.get("ok") is True, cr
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True, lr

                # 2. Set weather + design days
                wr = unwrap(await s.call_tool("set_weather_file", {
                    "epw_path": EPW_PATH,
                }))
                assert wr.get("ok") is True, wr
                dd1 = unwrap(await s.call_tool("add_design_day", {
                    "name": "Htg 99.6%", "day_type": "WinterDesignDay",
                    "month": 1, "day": 21,
                    "dry_bulb_max_c": -20.6, "dry_bulb_range_c": 0.0,
                }))
                assert dd1.get("ok") is True
                dd2 = unwrap(await s.call_tool("add_design_day", {
                    "name": "Clg 0.4%", "day_type": "SummerDesignDay",
                    "month": 7, "day": 21,
                    "dry_bulb_max_c": 33.3, "dry_bulb_range_c": 10.7,
                }))
                assert dd2.get("ok") is True

                # 3. Save model
                save_path = f"/runs/{name}.osm"
                sr = unwrap(await s.call_tool("save_osm_model", {
                    "save_path": save_path,
                }))
                assert sr.get("ok") is True

                # 4. Run simulation
                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": save_path, "epw_path": EPW_PATH,
                }))
                assert sim.get("ok") is True, sim
                run_id = sim["run_id"]

                # 5. Poll until done
                status = await poll_until_done(s, run_id)
                state = status["run"]["status"]
                assert state == "success", f"Simulation {state}: {status}"

                # 6. Extract summary metrics
                metrics = unwrap(await s.call_tool("extract_summary_metrics", {
                    "run_id": run_id,
                }))
                assert metrics.get("ok") is True, metrics
                assert "total_site_energy_gj" in metrics or "metrics" in metrics

                # 7. Extract end-use breakdown
                enduse = unwrap(await s.call_tool("extract_end_use_breakdown", {
                    "run_id": run_id,
                }))
                assert enduse.get("ok") is True, enduse

    asyncio.run(_run())
