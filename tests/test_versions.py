import asyncio
import json
import os
import shlex

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _integration_enabled() -> bool:
    return os.environ.get("RUN_OPENSTUDIO_INTEGRATION", "").strip() in ("1", "true", "TRUE", "yes", "YES")


def _unwrap_mcp_result(res):
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


@pytest.mark.integration
def test_get_versions_reports_openstudio_versions():
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    async def _run():
        server_params = StdioServerParameters(
            command=server_cmd,
            args=server_args,
            env=os.environ.copy(),
        )

        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            resp = await session.call_tool("get_versions", {})
            versions = _unwrap_mcp_result(resp)

            print("get_versions result:", versions)

            assert isinstance(versions, dict)
            assert versions.get("ok") is True, f"versions ok!=true: {versions}"

            # These keys come from mcp_server/server_tools.py
            assert versions.get("openstudio") == "3.11.0", (
                f"Expected pinned openstudio=3.11.0, got: {versions.get('openstudio')}"
            )
            py_ver = versions.get("openstudio_python")
            assert py_ver, f"Missing openstudio_python: {versions}"
            assert str(py_ver).startswith("3.11."), f"Expected openstudio_python to start with 3.11., got: {py_ver}"

    asyncio.run(_run())
