"""Integration test for /view skill workflow.

Exercises: create baseline → load → view_model → verify output path.
"""
import asyncio
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_skill_view_workflow():
    """/view skill: load model → view_model → verify output."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                name = f"skill_view_{uuid.uuid4().hex[:8]}"

                # 1. Create and load baseline model
                cr = unwrap(await s.call_tool("create_baseline_osm", {
                    "name": name, "ashrae_sys_num": "03",
                }))
                assert cr.get("ok") is True
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": cr["osm_path"],
                }))
                assert lr.get("ok") is True

                # 2. Generate 3D visualization
                view = unwrap(await s.call_tool("view_model", {}))
                assert view.get("ok") is True, view
                assert "run_dir" in view, f"Expected run_dir in view_model response: {view}"

    asyncio.run(_run())
