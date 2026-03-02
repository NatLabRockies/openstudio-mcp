import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_get_versions_reports_openstudio_versions():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resp = await session.call_tool("get_versions", {})
                versions = unwrap(resp)

                print("get_versions result:", versions)

                assert isinstance(versions, dict)
                assert versions.get("ok") is True, f"versions ok!=true: {versions}"

                # These keys come from mcp_server/server_tools.py
                assert versions.get("openstudio") == "3.11.0", f"Expected pinned openstudio=3.11.0, got: {versions.get('openstudio')}"
                py_ver = versions.get("openstudio_python")
                assert py_ver, f"Missing openstudio_python: {versions}"
                assert str(py_ver).startswith("3.11."), f"Expected openstudio_python to start with 3.11., got: {py_ver}"

    asyncio.run(_run())
