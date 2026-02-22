"""Integration tests for copy_run_artifact tool."""
import asyncio
import uuid

import pytest

from conftest import unwrap, integration_enabled, server_params
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_copy") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.mark.integration
def test_copy_run_artifact():
    """copy_run_artifact copies a file from a run dir to /runs/exports/."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    run_id = _unique()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create example model, load it, then save to a flat run dir
                cr = await session.call_tool("create_example_osm", {"name": run_id})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd

                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr).get("ok") is True

                # Save to /runs/<run_id>/model.osm — creates a flat run dir
                save_path = f"/runs/{run_id}/model.osm"
                sr = await session.call_tool("save_osm_model", {"save_path": save_path})
                assert unwrap(sr).get("ok") is True

                # Now copy the artifact
                resp = await session.call_tool("copy_run_artifact", {
                    "run_id": run_id,
                    "path": "model.osm",
                })
                result = unwrap(resp)
                print("copy_run_artifact:", result)
                assert result.get("ok") is True, result
                assert "destination" in result
                assert result["size_bytes"] > 0

    asyncio.run(_run())


@pytest.mark.integration
def test_copy_run_artifact_not_found():
    """copy_run_artifact returns error for missing run_id."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resp = await session.call_tool("copy_run_artifact", {
                    "run_id": "nonexistent_run_12345",
                    "path": "foo.txt",
                })
                result = unwrap(resp)
                print("copy not found:", result)
                assert result.get("ok") is False
                assert "run_not_found" in result.get("error", "")

    asyncio.run(_run())
