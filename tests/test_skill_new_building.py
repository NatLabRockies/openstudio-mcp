"""Integration test for /new-building skill workflow.

Exercises: create model → geometry → zones → envelope → loads →
schedules → HVAC → weather → save → simulate → extract results.
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


@pytest.mark.integration
def test_skill_new_building_workflow():
    """/new-building: full model creation → simulate → results."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_newbldg_{uuid.uuid4().hex[:8]}"

                # 1. Create baseline model (has geometry, zones, HVAC)
                cr = _unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "03",
                }))
                assert cr.get("ok") is True
                lr = _unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # 2. Get existing zones and spaces
                zones = _unwrap(await s.call_tool("list_thermal_zones", {}))
                assert zones.get("ok") is True
                assert zones["count"] > 0
                zone_names = [z["name"] for z in zones["thermal_zones"]]

                spaces = _unwrap(await s.call_tool("list_spaces", {}))
                assert spaces.get("ok") is True
                space_name = spaces["spaces"][0]["name"]

                # 3. Add glazing to an exterior wall
                surfaces = _unwrap(await s.call_tool("list_surfaces", {}))
                assert surfaces.get("ok") is True
                ext_walls = [sf for sf in surfaces["surfaces"]
                             if sf.get("surface_type") == "Wall"
                             and sf.get("outside_boundary_condition") == "Outdoors"]
                if ext_walls:
                    wwr = _unwrap(await s.call_tool("set_window_to_wall_ratio", {
                        "surface_name": ext_walls[0]["name"],
                        "ratio": 0.4,
                    }))
                    assert wwr.get("ok") is True

                # 4. Create schedule
                sched = _unwrap(await s.call_tool("create_schedule_ruleset", {
                    "name": "Occ Schedule",
                    "schedule_type": "Fractional",
                    "default_value": 0.5,
                }))
                assert sched.get("ok") is True

                # 5. Add loads to first space
                people = _unwrap(await s.call_tool("create_people_definition", {
                    "name": "Office People",
                    "space_name": space_name,
                    "people_per_area": 0.059,
                    "schedule_name": "Occ Schedule",
                }))
                assert people.get("ok") is True

                lights = _unwrap(await s.call_tool("create_lights_definition", {
                    "name": "Office Lights",
                    "space_name": space_name,
                    "watts_per_area": 10.76,
                }))
                assert lights.get("ok") is True

                equip = _unwrap(await s.call_tool("create_electric_equipment", {
                    "name": "Office Plugs",
                    "space_name": space_name,
                    "watts_per_area": 1.076,
                }))
                assert equip.get("ok") is True

                # 6. Verify HVAC (already present from baseline)
                hvac = _unwrap(await s.call_tool("list_air_loops", {}))
                assert hvac.get("ok") is True
                assert hvac["count"] > 0

                # 8. Weather + design days
                wr = _unwrap(await s.call_tool("set_weather_file", {
                    "epw_path": EPW_PATH,
                }))
                assert wr.get("ok") is True
                dd1 = _unwrap(await s.call_tool("add_design_day", {
                    "name": "Htg 99.6%", "day_type": "WinterDesignDay",
                    "month": 1, "day": 21,
                    "dry_bulb_max_c": -20.6, "dry_bulb_range_c": 0.0,
                }))
                assert dd1.get("ok") is True
                dd2 = _unwrap(await s.call_tool("add_design_day", {
                    "name": "Clg 0.4%", "day_type": "SummerDesignDay",
                    "month": 7, "day": 21,
                    "dry_bulb_max_c": 33.3, "dry_bulb_range_c": 10.7,
                }))
                assert dd2.get("ok") is True

                # 9. Save and simulate
                save_path = f"/runs/{name}.osm"
                sr = _unwrap(await s.call_tool("save_osm_model", {
                    "save_path": save_path,
                }))
                assert sr.get("ok") is True

                sim = _unwrap(await s.call_tool("run_simulation", {
                    "osm_path": save_path, "epw_path": EPW_PATH,
                }))
                assert sim.get("ok") is True
                run_id = sim["run_id"]

                status = await _poll_until_done(s, run_id)
                assert status["run"]["status"] == "success", status

                # 10. Extract results
                metrics = _unwrap(await s.call_tool("extract_summary_metrics", {
                    "run_id": run_id,
                }))
                assert metrics.get("ok") is True

    asyncio.run(_run())
