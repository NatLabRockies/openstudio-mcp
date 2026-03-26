"""Integration test for /retrofit skill workflow.

Exercises: create baseline → simulate → record EUI → apply ECM
(thermostat setpoint adjustment) → re-simulate → compare EUI.
"""
import asyncio
import uuid

import pytest
from conftest import EPW_PATH, integration_enabled, poll_until_done, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


async def _setup_and_simulate(s, name: str) -> tuple[str, str]:
    """Create baseline, add weather, save, simulate. Returns (save_path, run_id)."""
    cr = unwrap(await s.call_tool("create_baseline_osm", {
        "name": name, "ashrae_sys_num": "03",
    }))
    assert cr["ok"] is True
    lr = unwrap(await s.call_tool("load_osm_model", {
        "osm_path": cr["osm_path"],
    }))
    assert lr["ok"] is True
    wr = unwrap(await s.call_tool("change_building_location", {"weather_file": EPW_PATH}))
    assert wr["ok"] is True

    save_path = f"/runs/{name}.osm"
    sr = unwrap(await s.call_tool("save_osm_model", {"osm_path": save_path}))
    assert sr["ok"] is True
    sim = unwrap(await s.call_tool("run_simulation", {
        "osm_path": save_path, "epw_path": EPW_PATH,
    }))
    assert sim["ok"] is True
    run_id = sim["run_id"]
    status = await poll_until_done(s, run_id)
    assert status["run"]["status"] == "success", status
    return save_path, run_id


@pytest.mark.integration
def test_skill_retrofit_workflow():
    """/retrofit: baseline sim → apply thermostat ECM → re-sim → compare."""
    # Validates: full retrofit workflow — baseline sim, thermostat ECM, re-sim, both extract ok
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_retro_{uuid.uuid4().hex[:8]}"

                # 1. Baseline simulation
                _, baseline_run_id = await _setup_and_simulate(s, name)
                baseline_metrics = unwrap(await s.call_tool(
                    "extract_summary_metrics", {"run_id": baseline_run_id},
                ))
                assert baseline_metrics["ok"] is True

                # 2. Apply ECM: widen thermostat deadband
                ecm = unwrap(await s.call_tool("adjust_thermostat_setpoints", {
                    "cooling_offset_f": 2.0,
                    "heating_offset_f": -2.0,
                }))
                assert ecm["ok"] is True, ecm

                # 3. Re-simulate with retrofit
                retro_path = f"/runs/{name}_retrofit.osm"
                sr = unwrap(await s.call_tool("save_osm_model", {
                    "osm_path": retro_path,
                }))
                assert sr["ok"] is True
                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": retro_path, "epw_path": EPW_PATH,
                }))
                assert sim["ok"] is True
                retro_run_id = sim["run_id"]
                status = await poll_until_done(s, retro_run_id)
                assert status["run"]["status"] == "success", status

                # 4. Extract retrofit results
                retro_metrics = unwrap(await s.call_tool(
                    "extract_summary_metrics", {"run_id": retro_run_id},
                ))
                assert retro_metrics["ok"] is True

                # 5. Compare energy — thermostat deadband widening should change energy
                assert baseline_metrics["ok"] is True, f"Baseline extraction failed: {baseline_metrics}"
                assert retro_metrics["ok"] is True, f"Retrofit extraction failed: {retro_metrics}"

                b_metrics = baseline_metrics.get("metrics", baseline_metrics)
                r_metrics = retro_metrics.get("metrics", retro_metrics)
                for key in ["total_site_energy_GJ", "eui_MJ_m2", "total_energy_GJ"]:
                    if key in b_metrics and key in r_metrics:
                        assert b_metrics[key] > 0, f"Baseline {key} should be positive"
                        assert r_metrics[key] > 0, f"Retrofit {key} should be positive"
                        assert b_metrics[key] != pytest.approx(r_metrics[key], rel=0.001), (
                            f"ECM should change {key}: baseline={b_metrics[key]}, retrofit={r_metrics[key]}"
                        )
                        break
                else:
                    pytest.fail(
                        f"No common energy metric found. "
                        f"Baseline keys: {list(b_metrics.keys())}, "
                        f"Retrofit keys: {list(r_metrics.keys())}",
                    )

    asyncio.run(_run())
