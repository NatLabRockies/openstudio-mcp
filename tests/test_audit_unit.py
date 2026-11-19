"""Unit tests for AuditMiddleware's tool_call line: outcome and error capture.
No server, no openstudio — fake ToolResult objects through the real middleware.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from mcp_server import audit

pytestmark = pytest.mark.unit


def _run_call(monkeypatch, call_next):
    """Run one tool call through AuditMiddleware; return (outcome, recorded fields)."""
    recorded = []
    monkeypatch.setattr(audit, "_ENABLED", True)
    monkeypatch.setattr(audit, "audit", lambda event, **f: recorded.append({"event": event, **f}))
    ctx = SimpleNamespace(message=SimpleNamespace(name="load_osm_model",
                                                  arguments={"osm_path": "/assets/x.osm"}))
    try:
        out = asyncio.run(audit.AuditMiddleware().on_call_tool(ctx, call_next))
    except Exception as e:  # the raised case is under test
        out = e
    assert len(recorded) == 1 and recorded[0]["event"] == "tool_call", recorded
    return out, recorded[0]


def _text_result(payload: dict):
    return SimpleNamespace(structured_content=None,
                           content=[SimpleNamespace(text=json.dumps(payload))])


def test_returned_error_is_recorded(monkeypatch):
    # Regression: tools returning {"ok": false, "error": ...} were audited with ok=false
    # but no reason, so failures that left nothing on disk could not be diagnosed (#230).
    async def call_next(_ctx):
        return _text_result({"ok": False, "error": "OSM path is not allowed: /assets/x.osm"})

    _, rec = _run_call(monkeypatch, call_next)
    assert rec["ok"] is False
    assert rec["error"] == "OSM path is not allowed: /assets/x.osm"


def test_returned_error_from_structured_content_is_truncated(monkeypatch):
    # Validates: the error is read from structured_content too and truncated like args (300 chars).
    async def call_next(_ctx):
        return SimpleNamespace(structured_content={"ok": False, "error": "x" * 500}, content=[])

    _, rec = _run_call(monkeypatch, call_next)
    assert rec["ok"] is False
    assert rec["error"] == "x" * 300 + "..."


def test_success_has_no_error(monkeypatch):
    # Validates: successful calls are unchanged — no error recorded even if the dict has one.
    async def call_next(_ctx):
        return _text_result({"ok": True, "error": "ignored", "osm_path": "/runs/a.osm"})

    _, rec = _run_call(monkeypatch, call_next)
    assert rec["ok"] is True
    assert rec["error"] is None


def test_raised_exception_is_recorded(monkeypatch):
    # Validates: a tool that raises is still audited with the exception type and message.
    async def call_next(_ctx):
        raise ValueError("boom")

    out, rec = _run_call(monkeypatch, call_next)
    assert isinstance(out, ValueError)
    assert rec["ok"] is False
    assert rec["error"] == "ValueError: boom"
