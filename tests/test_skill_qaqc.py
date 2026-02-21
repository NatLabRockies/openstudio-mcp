"""Integration test for /qaqc skill workflow.

Exercises: create baseline → load → inspect_osm_summary → get_model_summary →
list_thermal_zones → list_spaces → get_weather_info → get_run_period.
No simulation needed — this is a pre-simulation quality check.
"""
import asyncio
import json
import os
import shlex
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


@pytest.mark.integration
def test_skill_qaqc_workflow():
    """/qaqc skill: load model, inspect summary, check for missing elements."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_qaqc_{uuid.uuid4().hex[:8]}"

                # 1. Create and load baseline model
                cr = _unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "03",
                }))
                assert cr.get("ok") is True
                lr = _unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # 2. Inspect model summary
                summary = _unwrap(await s.call_tool("inspect_osm_summary", {
                    "osm_path": cr["osm_path"],
                }))
                assert summary.get("ok") is True

                # 3. Get model summary (object counts)
                model_sum = _unwrap(await s.call_tool("get_model_summary", {}))
                assert model_sum.get("ok") is True

                # 4. Check thermal zones exist and have equipment
                zones = _unwrap(await s.call_tool("list_thermal_zones", {}))
                assert zones.get("ok") is True
                assert zones["count"] > 0, "No thermal zones found"

                # 5. Check spaces are assigned to zones
                spaces = _unwrap(await s.call_tool("list_spaces", {}))
                assert spaces.get("ok") is True
                assert spaces["count"] > 0, "No spaces found"

                # 6. Check weather info (baseline model has no EPW)
                weather = _unwrap(await s.call_tool("get_weather_info", {}))
                # ok may be False if no weather file — that's a valid QA finding

                # 7. Check run period
                rp = _unwrap(await s.call_tool("get_run_period", {}))
                assert rp.get("ok") is True

                # 8. Check HVAC exists (baseline model should have it)
                hvac = _unwrap(await s.call_tool("list_zone_hvac_equipment", {}))
                assert hvac.get("ok") is True

    asyncio.run(_run())
