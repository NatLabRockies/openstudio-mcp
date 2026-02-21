"""Integration test for /add-hvac skill workflow.

Exercises: create model → load → list zones → add_baseline_system →
verify with list_air_loops + list_zone_hvac_equipment.
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
def test_skill_add_hvac_workflow():
    """/add-hvac skill: inspect model → add system → verify equipment."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_hvac_{uuid.uuid4().hex[:8]}"

                # 1. Create baseline (gives us zones, no HVAC yet via example)
                cr = _unwrap(await s.call_tool("create_example_osm", {
                    "name": name,
                }))
                assert cr.get("ok") is True
                lr = _unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # 2. Understand current model
                info = _unwrap(await s.call_tool("get_building_info", {}))
                assert info.get("ok") is True

                zones = _unwrap(await s.call_tool("list_thermal_zones", {}))
                assert zones.get("ok") is True
                assert zones["count"] > 0
                zone_names = [z["name"] for z in zones["thermal_zones"]]

                # 3. Add HVAC system (System 3 = PSZ-AC for small building)
                hvac = _unwrap(await s.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": zone_names,
                    "heating_fuel": "NaturalGas",
                }))
                assert hvac.get("ok") is True, hvac

                # 4. Verify air loops created
                loops = _unwrap(await s.call_tool("list_air_loops", {}))
                assert loops.get("ok") is True
                assert loops["count"] > 0

                # 5. Verify zone equipment
                equip = _unwrap(await s.call_tool("list_zone_hvac_equipment", {}))
                assert equip.get("ok") is True

    asyncio.run(_run())
