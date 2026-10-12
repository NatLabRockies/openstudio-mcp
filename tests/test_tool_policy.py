"""Tool policy and fail-closed sandbox over a real HTTP server (issue #180).

Integration tier: real server process, real MCP client, nothing mocked.
"""
from __future__ import annotations

import asyncio

import pytest
from conftest import http_server, http_session, integration_enabled, unwrap

pytestmark = pytest.mark.integration

CODE_TOOLS = {
    "create_measure", "edit_measure", "create_python_plugin",
    "edit_python_plugin", "install_plugin_packages",
}


def _skip_unless_integration():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")


async def _initialize(url):
    """Open a session and return (InitializeResult, session) inside one async block."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (read, write, _sid):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            return init.instructions or "", tools


def test_http_hides_code_tools_and_says_so():
    # Validates: on a default HTTP server the five code-authoring tools are absent from
    # list_tools, a call to one is refused, the server instructions no longer tell the
    # agent to "ALWAYS use create_measure", and list_skills carries the policy note
    _skip_unless_integration()
    # conftest enables the code tools for the suite; this test wants the shipped default
    with http_server({"MCP_AUTH": "none", "OSMCP_ENABLE_CODE_TOOLS": "false"}) as (url, _proc):
        async def _run():
            instructions, tools = await _initialize(url)
            assert CODE_TOOLS.isdisjoint(tools), f"hidden tools advertised: {CODE_TOOLS & tools}"
            assert {"apply_measure", "run_osw", "test_measure", "list_skills"} <= tools
            assert "create_measure" not in instructions, instructions
            assert "disabled on this server" in instructions, instructions
            async with http_session(url) as s:
                res = await s.call_tool("create_measure", {
                    "name": "policy_probe", "description": "x",
                    "run_body": "    runner.registerInfo('x')", "language": "Ruby",
                })
                assert res.isError is True, res
                skills = unwrap(await s.call_tool("list_skills", {}))
                assert skills["ok"] is True
                assert "disabled on this server" in skills["policy_note"], skills

        asyncio.run(_run())


def test_http_enable_code_tools_restores_authoring():
    # Validates: OSMCP_ENABLE_CODE_TOOLS=true is the operator opt-in: the tools are listed
    # again, the instructions name create_measure, and list_skills carries no policy note
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none", "OSMCP_ENABLE_CODE_TOOLS": "true"}) as (url, _proc):
        async def _run():
            instructions, tools = await _initialize(url)
            assert CODE_TOOLS <= tools, f"missing: {CODE_TOOLS - tools}"
            assert "ALWAYS use create_measure" in instructions
            async with http_session(url) as s:
                skills = unwrap(await s.call_tool("list_skills", {}))
                assert "policy_note" not in skills, skills

        asyncio.run(_run())


def test_deny_listed_create_measure_is_not_advertised():
    # Regression: the instructions keyed on the HTTP code-tools flag, so with the code tools
    # enabled but create_measure deny-listed the agent was still told to "ALWAYS use
    # create_measure" (Codex review); guidance must follow the tool's actual exposure
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none", "OSMCP_ENABLE_CODE_TOOLS": "true",
                      "OSMCP_TOOLS_DENY": "create_measure"}) as (url, _proc):
        async def _run():
            instructions, tools = await _initialize(url)
            assert "create_measure" not in tools and "edit_measure" in tools
            assert "create_measure" not in instructions, instructions
            assert "disabled on this server" in instructions
            async with http_session(url) as s:
                skills = unwrap(await s.call_tool("list_skills", {}))
                assert skills["policy_note"].count("create_measure") == 1, skills["policy_note"]

        asyncio.run(_run())


def test_http_refuses_to_start_without_full_sandbox():
    # Validates: an HTTP server with OSMCP_SANDBOX=off and no OSMCP_ALLOW_UNSANDBOXED
    # override exits 3 with the confinement message on stderr instead of serving
    # tenants with measures running as the server user (and no traceback)
    _skip_unless_integration()
    with pytest.raises(RuntimeError, match=r"exited \(code 3\)[\s\S]*full sandbox confinement") as ei:
        with http_server({"MCP_AUTH": "none", "OSMCP_SANDBOX": "off"}):
            pass
    assert "Traceback" not in str(ei.value), str(ei.value)


def test_http_refuses_unknown_policy_entry():
    # Regression: a typo in OSMCP_TOOLS_DENY hid nothing and logged nothing; the server
    # must refuse to start and name the bad entry
    _skip_unless_integration()
    with pytest.raises(RuntimeError, match=r"exited \(code 3\)[\s\S]*OSMCP_TOOLS_DENY[\s\S]*'run_simulaton'"):
        with http_server({"MCP_AUTH": "none", "OSMCP_TOOLS_DENY": "run_simulaton,run_osw"}):
            pass


def test_http_code_mode_synthetic_tools_follow_policy():
    # Regression: with OSMCP_CODE_MODE=1 the synthetic search/get_schema/execute tools were
    # added after the policy filter, so a denied discovery tool was still listed
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none", "OSMCP_CODE_MODE": "1",
                      "OSMCP_TOOLS_DENY": "search"}) as (url, _proc):
        async def _run():
            _instructions, tools = await _initialize(url)
            assert tools == {"get_schema", "execute"}, tools

        asyncio.run(_run())
