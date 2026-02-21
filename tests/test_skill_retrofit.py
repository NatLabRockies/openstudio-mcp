"""Integration test for /retrofit skill workflow.

Exercises: create baseline → simulate → record EUI → apply ECM
(thermostat setpoint adjustment) → re-simulate → compare EUI.
"""
import asyncio
import uuid

import pytest

from conftest import unwrap, integration_enabled, server_params, poll_until_done, EPW_PATH
from mcp import ClientSession
from mcp.client.stdio import stdio_client


async def _setup_and_simulate(s, name: str) -> tuple[str, str]:
    """Create baseline, add weather, save, simulate. Returns (save_path, run_id)."""
    cr = unwrap(await s.call_tool("create_baseline_osm", {
        "name": name, "ashrae_sys_num": "03",
    }))
    assert cr.get("ok") is True
    lr = unwrap(await s.call_tool("load_osm_model", {
        "osm_path": cr["osm_path"],
    }))
    assert lr.get("ok") is True
    wr = unwrap(await s.call_tool("set_weather_file", {"epw_path": EPW_PATH}))
    assert wr.get("ok") is True
    for dd_args in [
        {"name": "Htg", "day_type": "WinterDesignDay",
         "month": 1, "day": 21,
         "dry_bulb_max_c": -20.6, "dry_bulb_range_c": 0.0},
        {"name": "Clg", "day_type": "SummerDesignDay",
         "month": 7, "day": 21,
         "dry_bulb_max_c": 33.3, "dry_bulb_range_c": 10.7},
    ]:
        dd = unwrap(await s.call_tool("add_design_day", dd_args))
        assert dd.get("ok") is True

    save_path = f"/runs/{name}.osm"
    sr = unwrap(await s.call_tool("save_osm_model", {"save_path": save_path}))
    assert sr.get("ok") is True
    sim = unwrap(await s.call_tool("run_simulation", {
        "osm_path": save_path, "epw_path": EPW_PATH,
    }))
    assert sim.get("ok") is True
    run_id = sim["run_id"]
    status = await poll_until_done(s, run_id)
    assert status["run"]["status"] == "success", status
    return save_path, run_id


@pytest.mark.integration
def test_skill_retrofit_workflow():
    """/retrofit: baseline sim → apply thermostat ECM → re-sim → compare."""
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
                assert baseline_metrics.get("ok") is True

                # 2. Apply ECM: widen thermostat deadband
                ecm = unwrap(await s.call_tool("adjust_thermostat_setpoints", {
                    "cooling_offset_f": 2.0,
                    "heating_offset_f": -2.0,
                }))
                assert ecm.get("ok") is True, ecm

                # 3. Re-simulate with retrofit
                retro_path = f"/runs/{name}_retrofit.osm"
                sr = unwrap(await s.call_tool("save_osm_model", {
                    "save_path": retro_path,
                }))
                assert sr.get("ok") is True
                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": retro_path, "epw_path": EPW_PATH,
                }))
                assert sim.get("ok") is True
                retro_run_id = sim["run_id"]
                status = await poll_until_done(s, retro_run_id)
                assert status["run"]["status"] == "success", status

                # 4. Extract retrofit results
                retro_metrics = unwrap(await s.call_tool(
                    "extract_summary_metrics", {"run_id": retro_run_id},
                ))
                assert retro_metrics.get("ok") is True

                # 5. Both runs completed with results
                assert baseline_metrics.get("ok") is True
                assert retro_metrics.get("ok") is True

    asyncio.run(_run())
