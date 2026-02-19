"""Integration tests for copy_run_artifact tool."""
import asyncio
import json
import os
import shlex
import uuid

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _integration_enabled() -> bool:
    return os.environ.get("RUN_OPENSTUDIO_INTEGRATION", "").strip() in ("1", "true", "TRUE", "yes", "YES")


def _unwrap(res):
    if isinstance(res, dict):
        return res
    content = getattr(res, "content", None)
    if not content:
        return res
    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        return str(first)
    t = text.strip()
    if not t:
        return t
    try:
        return json.loads(t)
    except Exception:
        return t


def _unique(prefix: str = "pytest_copy") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.mark.integration
def test_copy_run_artifact():
    """copy_run_artifact copies a file from a run dir to /runs/exports/."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    run_id = _unique()

    async def _run():
        server_params = StdioServerParameters(command=server_cmd, args=server_args, env=os.environ.copy())
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create example model, load it, then save to a flat run dir
                cr = await session.call_tool("create_example_osm", {"name": run_id})
                cd = _unwrap(cr)
                assert cd.get("ok") is True, cd

                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert _unwrap(lr).get("ok") is True

                # Save to /runs/<run_id>/model.osm — creates a flat run dir
                save_path = f"/runs/{run_id}/model.osm"
                sr = await session.call_tool("save_osm_model", {"save_path": save_path})
                assert _unwrap(sr).get("ok") is True

                # Now copy the artifact
                resp = await session.call_tool("copy_run_artifact", {
                    "run_id": run_id,
                    "path": "model.osm",
                })
                result = _unwrap(resp)
                print("copy_run_artifact:", result)
                assert result.get("ok") is True, result
                assert "destination" in result
                assert result["size_bytes"] > 0

    asyncio.run(_run())


@pytest.mark.integration
def test_copy_run_artifact_not_found():
    """copy_run_artifact returns error for missing run_id."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    async def _run():
        server_params = StdioServerParameters(command=server_cmd, args=server_args, env=os.environ.copy())
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resp = await session.call_tool("copy_run_artifact", {
                    "run_id": "nonexistent_run_12345",
                    "path": "foo.txt",
                })
                result = _unwrap(resp)
                print("copy not found:", result)
                assert result.get("ok") is False
                assert "run_not_found" in result.get("error", "")

    asyncio.run(_run())
