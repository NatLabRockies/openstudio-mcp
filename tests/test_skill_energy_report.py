"""Integration test for /energy-report skill workflow.

Exercises: create baseline → weather → simulate → extract all 6 result
categories (summary, end-use, envelope, HVAC sizing, zone, component).
"""
import asyncio
import uuid

import pytest
from conftest import EPW_PATH, integration_enabled, poll_until_done, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_skill_energy_report_workflow():
    """/energy-report skill: simulate then extract all 6 result categories."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_report_{uuid.uuid4().hex[:8]}"

                # Setup: create baseline, weather, simulate
                cr = unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "03",
                }))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True
                wr = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW_PATH,
                }))
                assert wr.get("ok") is True

                save_path = f"/runs/{name}.osm"
                sr = unwrap(await s.call_tool("save_osm_model", {
                    "save_path": save_path,
                }))
                assert sr.get("ok") is True
                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": save_path, "epw_path": EPW_PATH,
                }))
                assert sim.get("ok") is True
                run_id = sim["run_id"]
                status = await poll_until_done(s, run_id)
                assert status["run"]["status"] == "success", status

                # Extract all 6 result categories
                extractors = [
                    "extract_summary_metrics",
                    "extract_end_use_breakdown",
                    "extract_envelope_summary",
                    "extract_hvac_sizing",
                    "extract_zone_summary",
                    "extract_component_sizing",
                ]
                for tool_name in extractors:
                    result = unwrap(await s.call_tool(tool_name, {
                        "run_id": run_id,
                    }))
                    assert result.get("ok") is True, (
                        f"{tool_name} failed: {result}"
                    )

    asyncio.run(_run())
