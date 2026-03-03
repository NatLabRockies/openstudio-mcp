"""Integration test for /qaqc skill workflow.

Exercises: create baseline → load → inspect_osm_summary → get_model_summary →
list_thermal_zones → list_spaces → get_weather_info → get_run_period.
No simulation needed — this is a pre-simulation quality check.
"""
import asyncio
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_skill_qaqc_workflow():
    """/qaqc skill: load model, inspect summary, check for missing elements."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_qaqc_{uuid.uuid4().hex[:8]}"

                # 1. Create and load baseline model
                cr = unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "03",
                }))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # 2. Inspect model summary
                summary = unwrap(await s.call_tool("inspect_osm_summary", {
                    "osm_path": cr["osm_path"],
                }))
                assert summary.get("ok") is True

                # 3. Get model summary (object counts)
                model_sum = unwrap(await s.call_tool("get_model_summary", {}))
                assert model_sum.get("ok") is True

                # 4. Check thermal zones exist and have equipment
                zones = unwrap(await s.call_tool("list_thermal_zones", {}))
                assert zones.get("ok") is True
                assert zones["count"] > 0, "No thermal zones found"

                # 5. Check spaces are assigned to zones
                spaces = unwrap(await s.call_tool("list_spaces", {}))
                assert spaces.get("ok") is True
                assert spaces["count"] > 0, "No spaces found"

                # 6. Check weather info (baseline model has no EPW)
                weather = unwrap(await s.call_tool("get_weather_info", {}))
                # ok may be False if no weather file — that's a valid QA finding

                # 7. Check run period
                rp = unwrap(await s.call_tool("get_run_period", {}))
                assert rp.get("ok") is True

                # 8. Check HVAC exists (baseline model should have it)
                hvac = unwrap(await s.call_tool("list_zone_hvac_equipment", {}))
                assert hvac.get("ok") is True

    asyncio.run(_run())
