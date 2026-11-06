"""A file on the user's machine: instructions and path errors name the next step.

Integration tier: real server process, real MCP client, nothing mocked.

Session 2026-11-04 (remote HTTP server): asked about a model in the user's local folder, the
agent called list_files and load_osm_model on the server, got bare "not allowed" errors and
parsed the OSM with local scripts instead of uploading it.
"""
from __future__ import annotations

import asyncio

import pytest
from conftest import http_server, http_session, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.integration

WIN_PATH = r"C:\projects\test\assets\SystemD_baseline.osm"
HTTP_HINT = (
    "Paths are on the server, not the user's machine. If this file is on the user's "
    "machine, upload it with request_upload, then use the path get_upload returns."
)
HTTP_WIN_HINT = (
    f"{WIN_PATH} looks like a path on the user's machine; the server cannot read it. "
    "Upload the file with request_upload, then use the path get_upload returns."
)
STDIO_HINT = (
    "Paths are on the server, not the user's machine. Files from the user's mounted "
    "folder are under /inputs; list_files shows them."
)


def _skip_unless_integration():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")


def test_http_path_failures_carry_an_upload_hint():
    # Regression: over HTTP, list_files("/assets"), load_osm_model("C:\...") and
    # inspect_osm_summary("/assets/...") failed with no next step, so the agent never
    # uploaded the user's local model (session 2026-11-04)
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                # --- Act ---
                listed = unwrap(await s.call_tool(
                    "list_files", {"directory": "/assets", "pattern": "SystemD*osm"}))
                loaded = unwrap(await s.call_tool("load_osm_model", {"osm_path": WIN_PATH}))
                inspected = unwrap(await s.call_tool(
                    "inspect_osm_summary", {"osm_path": "/assets/SystemD_baseline.osm"}))
                unmatched = unwrap(await s.call_tool(
                    "list_files", {"pattern": "NoSuchModel_7f3a*.osm"}))

                # --- Assert ---
                assert listed["ok"] is False
                assert listed["error"] == (
                    "Directory not allowed: /assets. list_files is restricted to /inputs and /runs."
                ), "list_files error text must stay as it was; guidance goes in hint"
                assert listed["hint"] == HTTP_HINT

                assert loaded["ok"] is False
                assert loaded["error"].startswith("OSM file not found: "), loaded
                assert loaded["error"].endswith(WIN_PATH), loaded
                assert loaded["hint"] == HTTP_WIN_HINT

                assert inspected["ok"] is False
                assert inspected["error"] == "OSM path is not allowed: /assets/SystemD_baseline.osm"
                assert inspected["hint"] == HTTP_HINT

                assert unmatched["ok"] is True
                assert unmatched["count"] == 0
                assert unmatched["hint"] == (
                    "No matching file on the server. If the file is on the user's machine, "
                    "upload it with request_upload, then use the path get_upload returns."
                ), "an empty server listing must point at the user's machine"

        asyncio.run(_run())


def test_http_instructions_and_tool_text_stop_pointing_at_the_server_first():
    # Regression: the HTTP server's instructions said "If a file path is given, use it
    # directly ... call list_files once", and request_upload said "Check first with
    # list_files"; both sent the agent to the server for a file on the user's machine
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(url) as (read, write, _sid):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    tools = {t.name: t.description for t in (await session.list_tools()).tools}

            instructions = init.instructions or ""
            assert (
                "a file the user names is usually on the user's machine instead. Unless the "
                "path came from a tool result, starts with /runs/ or /inputs/, or the user says "
                "it is on the server, look for it on the user's machine with your own file tools "
                "first (ask the user if you have none), then upload it with request_upload and "
                "use the path get_upload returns."
            ) in instructions
            assert "If a file path is given, use it directly" not in instructions
            assert "Check first with list_files" not in tools["request_upload"]
            assert "user-provided models" not in tools["list_files"]
            assert "on the SERVER" in tools["list_files"], tools["list_files"]

        asyncio.run(_run())


def test_stdio_keeps_mounted_folder_guidance():
    # Validates: on stdio the user's folder is mounted into the server, so the instructions
    # keep "use it directly" and a failed path hints at list_files, never at request_upload
    _skip_unless_integration()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()

                # --- Act ---
                loaded = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": "/assets/SystemD_baseline.osm"}))
                unmatched = unwrap(await session.call_tool(
                    "list_files", {"pattern": "NoSuchModel_7f3a*.osm"}))

                # --- Assert ---
                assert "If a file path is given, use it directly." in (init.instructions or "")
                assert loaded["ok"] is False
                assert loaded["error"] == "OSM path is not allowed: /assets/SystemD_baseline.osm"
                assert loaded["hint"] == STDIO_HINT
                assert unmatched["ok"] is True
                assert unmatched["count"] == 0
                assert "hint" not in unmatched, unmatched

    asyncio.run(_run())
