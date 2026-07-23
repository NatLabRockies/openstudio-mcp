"""Tests for the response-size guard middleware (issue #98).

A ~19MB run_qaqc_checks response killed the stdio JSON-RPC session (server
exited 0 mid-call; the client lost the tool roster until manual reconnect).
The guard spills any oversized response to the caller's run area and returns
a small pointer response instead.
"""
import asyncio
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import integration_enabled, server_params, unwrap

from mcp_server import response_guard
from mcp_server.response_guard import (
    ResponseSizeGuard,
    max_response_bytes,
    serialize_result,
)


def _context(tool_name="fake_tool"):
    return SimpleNamespace(message=SimpleNamespace(name=tool_name, arguments={}))


def _run_guard(result, monkeypatch=None, cap_mb=None):
    if cap_mb is not None:
        os.environ["OSMCP_MAX_TOOL_RESPONSE_MB"] = cap_mb
    guard = ResponseSizeGuard()

    async def call_next(_context):
        return result

    return asyncio.run(guard.on_call_tool(_context(), call_next))


@pytest.mark.unit
def test_cap_from_env(monkeypatch):
    # Validates: OSMCP_MAX_TOOL_RESPONSE_MB controls the cap; default 1MB; junk falls back
    monkeypatch.delenv("OSMCP_MAX_TOOL_RESPONSE_MB", raising=False)
    assert max_response_bytes() == 1024 * 1024
    monkeypatch.setenv("OSMCP_MAX_TOOL_RESPONSE_MB", "0.5")
    assert max_response_bytes() == 524288
    monkeypatch.setenv("OSMCP_MAX_TOOL_RESPONSE_MB", "junk")
    assert max_response_bytes() == 1024 * 1024
    # Regression: Copilot PR#100 review — nan raised ValueError (int(nan)) and
    # inf raised OverflowError on EVERY tool call; non-positive caps flagged
    # every response as oversized. All must clamp to the default.
    for bad in ("nan", "inf", "-inf", "-1", "0"):
        monkeypatch.setenv("OSMCP_MAX_TOOL_RESPONSE_MB", bad)
        assert max_response_bytes() == 1024 * 1024, f"cap must clamp to default for {bad!r}"


@pytest.mark.unit
def test_serialize_prefers_structured_content():
    # Validates: size is measured on structured content when present, else text blocks
    structured = SimpleNamespace(structured_content={"ok": True, "n": 1}, content=None)
    assert json.loads(serialize_result(structured)) == {"ok": True, "n": 1}
    text_only = SimpleNamespace(
        structured_content=None,
        content=[SimpleNamespace(text="hello"), SimpleNamespace(text="world")],
    )
    assert serialize_result(text_only) == "hello\nworld"
    assert serialize_result(SimpleNamespace(structured_content=None, content=[])) is None


@pytest.mark.unit
def test_small_response_passes_through_unchanged(monkeypatch):
    # Validates: guard is a no-op below the cap — normal tool responses untouched
    from fastmcp.tools.tool import ToolResult

    monkeypatch.setenv("OSMCP_MAX_TOOL_RESPONSE_MB", "1")
    original = ToolResult(structured_content={"ok": True, "value": 42})
    result = _run_guard(original)
    assert result is original


@pytest.mark.unit
def test_oversized_response_spilled_to_disk(monkeypatch, tmp_path):
    # Regression: #98 — oversized payload must be replaced by a small pointer
    # response, with the full payload preserved on disk for copy_file export
    from fastmcp.tools.tool import ToolResult

    monkeypatch.setenv("OSMCP_MAX_TOOL_RESPONSE_MB", "0.0001")  # 104 bytes
    monkeypatch.setattr(response_guard, "user_run_root", lambda: tmp_path)
    payload = {"ok": True, "blob": "x" * 10_000}
    result = _run_guard(ToolResult(structured_content=payload))

    sc = result.structured_content
    assert sc["ok"] is True
    assert sc["response_truncated"] is True
    assert sc["tool"] == "fake_tool"
    assert sc["response_size_bytes"] == len(json.dumps(payload))
    assert sc["preview"].startswith('{"ok": true')
    spilled = json.loads(Path(sc["spilled_path"]).read_text(encoding="utf-8"))
    assert spilled == payload, "spill file must round-trip the full original payload"
    assert len(json.dumps(sc)) < 5_000, "replacement response must itself be small"


@pytest.mark.unit
def test_oversized_error_response_keeps_ok_false(monkeypatch, tmp_path):
    # Validates: a huge error payload is still reported as an error after replacement
    from fastmcp.tools.tool import ToolResult

    monkeypatch.setenv("OSMCP_MAX_TOOL_RESPONSE_MB", "0.0001")
    monkeypatch.setattr(response_guard, "user_run_root", lambda: tmp_path)
    result = _run_guard(ToolResult(structured_content={"ok": False, "error": "y" * 10_000}))
    assert result.structured_content["ok"] is False
    assert result.structured_content["response_truncated"] is True


@pytest.mark.unit
def test_spill_failure_still_replaces_response(monkeypatch):
    # Validates: even if spilling to disk fails, the oversized payload must NOT
    # reach the transport — that's the exact #98 failure mode
    from fastmcp.tools.tool import ToolResult

    def boom():
        raise OSError("disk full")

    monkeypatch.setenv("OSMCP_MAX_TOOL_RESPONSE_MB", "0.0001")
    monkeypatch.setattr(response_guard, "user_run_root", boom)
    result = _run_guard(ToolResult(structured_content={"ok": True, "blob": "z" * 10_000}))
    sc = result.structured_content
    assert sc["response_truncated"] is True
    assert "spilled_path" not in sc
    assert "failed" in sc["user_message"]
    assert len(json.dumps(sc)) < 5_000


@pytest.mark.integration
def test_oversized_response_does_not_kill_stdio_session():
    # Regression: #98 — a ~19MB run_qaqc_checks response crashed the stdio
    # server mid-call (exit 0, "Connection closed"); the session's tools were
    # lost until manual reconnect. With the guard, the call returns a pointer
    # response and the session keeps working.
    if not integration_enabled():
        pytest.skip("integration disabled")

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    base = server_params()
    params = StdioServerParameters(
        command=base.command,
        args=base.args,
        # ~1KB cap: list_skills always exceeds it, get_versions never does
        env={**(base.env or {}), "OSMCP_MAX_TOOL_RESPONSE_MB": "0.001"},
    )

    async def _run():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                res = unwrap(await s.call_tool("list_skills", {}))
                assert res["response_truncated"] is True, f"expected guard to trip: {str(res)[:500]}"
                assert res["ok"] is True
                assert res["tool"] == "list_skills"
                assert res["response_size_bytes"] > 1024
                assert res["spilled_path"].endswith("response.json")
                assert res["preview"], "preview must be present for agent orientation"

                # The core of #98: the session must survive the oversized call
                versions = unwrap(await s.call_tool("get_versions", {}))
                assert versions["ok"] is True, "session must stay alive after an oversized response"
                assert versions.get("response_truncated") is not True

    asyncio.run(_run())
