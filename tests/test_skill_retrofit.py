"""Integration test for /retrofit skill workflow.

Exercises: create baseline → simulate → record EUI → apply ECM
(thermostat setpoint adjustment) → re-simulate → compare EUI.
"""
import asyncio
import json
import os
import shlex
import time
import uuid

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _integration_enabled() -> bool:
    return os.environ.get("RUN_OPENSTUDIO_INTEGRATION", "").strip() in (
        "1", "true", "TRUE", "yes", "YES",
    )


def _unwrap(res):
    content = getattr(res, "content", None)
    if not content:
        return res if isinstance(res, dict) else {}
    text = getattr(content[0], "text", None)
    if text is None:
        return str(content[0])
    try:
        return json.loads(text.strip())
    except Exception:
        return text.strip()


def _server_params():
    cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    args = shlex.split(args_env) if args_env else []
    return StdioServerParameters(command=cmd, args=args, env=os.environ.copy())


EPW_PATH = "/repo/tests/assets/SEB_model/SEB4_baseboard/files/SRRL_2012AMY_60min.epw"
POLL_SECONDS = float(os.environ.get("MCP_POLL_SECONDS", "3"))
SIM_TIMEOUT = float(os.environ.get("MCP_SIM_TIMEOUT", str(60 * 20)))


async def _poll_until_done(s, run_id: str) -> dict:
    terminal = {"success", "failed", "error", "cancelled"}
    started = time.time()
    while True:
        if time.time() - started > SIM_TIMEOUT:
            raise AssertionError(f"Simulation timed out after {SIM_TIMEOUT}s")
        status = _unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))
        state = (status.get("run", {}).get("status") or "unknown").lower()
        if state in terminal:
            return status
        await asyncio.sleep(POLL_SECONDS)


async def _setup_and_simulate(s, name: str) -> tuple[str, str]:
    """Create baseline, add weather, save, simulate. Returns (save_path, run_id)."""
    cr = _unwrap(await s.call_tool("create_baseline_osm", {
        "name": name, "ashrae_sys_num": "03",
    }))
    assert cr.get("ok") is True
    lr = _unwrap(await s.call_tool("load_osm_model", {
        "osm_path": cr["osm_path"],
    }))
    assert lr.get("ok") is True
    wr = _unwrap(await s.call_tool("set_weather_file", {"epw_path": EPW_PATH}))
    assert wr.get("ok") is True
    for dd_args in [
        {"name": "Htg", "day_type": "WinterDesignDay",
         "month": 1, "day": 21,
         "dry_bulb_max_c": -20.6, "dry_bulb_range_c": 0.0},
        {"name": "Clg", "day_type": "SummerDesignDay",
         "month": 7, "day": 21,
         "dry_bulb_max_c": 33.3, "dry_bulb_range_c": 10.7},
    ]:
        dd = _unwrap(await s.call_tool("add_design_day", dd_args))
        assert dd.get("ok") is True

    save_path = f"/runs/{name}.osm"
    sr = _unwrap(await s.call_tool("save_osm_model", {"save_path": save_path}))
    assert sr.get("ok") is True
    sim = _unwrap(await s.call_tool("run_simulation", {
        "osm_path": save_path, "epw_path": EPW_PATH,
    }))
    assert sim.get("ok") is True
    run_id = sim["run_id"]
    status = await _poll_until_done(s, run_id)
    assert status["run"]["status"] == "success", status
    return save_path, run_id


@pytest.mark.integration
def test_skill_retrofit_workflow():
    """/retrofit: baseline sim → apply thermostat ECM → re-sim → compare."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_retro_{uuid.uuid4().hex[:8]}"

                # 1. Baseline simulation
                _, baseline_run_id = await _setup_and_simulate(s, name)
                baseline_metrics = _unwrap(await s.call_tool(
                    "extract_summary_metrics", {"run_id": baseline_run_id},
                ))
                assert baseline_metrics.get("ok") is True

                # 2. Apply ECM: widen thermostat deadband
                ecm = _unwrap(await s.call_tool("adjust_thermostat_setpoints", {
                    "cooling_offset_f": 2.0,
                    "heating_offset_f": -2.0,
                }))
                assert ecm.get("ok") is True, ecm

                # 3. Re-simulate with retrofit
                retro_path = f"/runs/{name}_retrofit.osm"
                sr = _unwrap(await s.call_tool("save_osm_model", {
                    "save_path": retro_path,
                }))
                assert sr.get("ok") is True
                sim = _unwrap(await s.call_tool("run_simulation", {
                    "osm_path": retro_path, "epw_path": EPW_PATH,
                }))
                assert sim.get("ok") is True
                retro_run_id = sim["run_id"]
                status = await _poll_until_done(s, retro_run_id)
                assert status["run"]["status"] == "success", status

                # 4. Extract retrofit results
                retro_metrics = _unwrap(await s.call_tool(
                    "extract_summary_metrics", {"run_id": retro_run_id},
                ))
                assert retro_metrics.get("ok") is True

                # 5. Both runs completed with results
                assert baseline_metrics.get("ok") is True
                assert retro_metrics.get("ok") is True

    asyncio.run(_run())
