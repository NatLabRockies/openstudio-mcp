"""export_hint: the sentence that tells an agent how to get a server file to the user.

Issue #167: report tools told HTTP agents to find the file "on the host at
runs/exports/..."; over HTTP there is no host mount and the agent gave up.
"""
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


REPORT = Path("/runs/u/r/reports/x.html")  # str(REPORT) differs on Windows; interpolate it


@pytest.mark.parametrize(("transport", "expect", "forbid"), [
    ("http", f'request_download(path="{REPORT}")', "copy_file"),
    ("streamable-http", "request_download(", "runs/exports"),
    ("stdio", f'copy_file(file_path="{REPORT}")', "request_download"),
    ("", "copy_file(", "runs/exports"),
])
def test_export_hint_follows_transport(monkeypatch, transport, expect, forbid):
    # Regression: one stdio-only sentence ("find it on the host at runs/exports/...") was
    # given on every transport; HTTP agents have no mount (issue #167)
    from mcp_server.export_hint import export_hint
    if transport:
        monkeypatch.setenv("MCP_TRANSPORT", transport)
    else:
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    msg = export_hint(REPORT, "Report")
    assert msg.startswith(f"Report written to {REPORT}. "), msg
    assert expect in msg, msg
    assert forbid not in msg, msg


def test_export_hint_http_names_download_ttl(monkeypatch):
    # Validates: the HTTP hint states how long the download URL lives, from config
    from mcp_server import export_hint as eh
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setattr("mcp_server.config.OSMCP_DOWNLOAD_URL_TTL", 1234)
    assert "valid for 1234 s" in eh.export_hint(Path("/runs/a.html"))


def test_spill_message_uses_transport_hint(monkeypatch, tmp_path):
    # Regression: the oversized-response spill told HTTP agents to use copy_file, the same
    # stdio-only hint as the report tools (issue #167, D5)
    from mcp_server import response_guard
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.setattr("mcp_server.response_guard.user_run_root", lambda: tmp_path)
    big = '{"ok": true, "data": "' + "x" * 500 + '"}'
    rep = response_guard.build_replacement("list_things", big, cap=100)
    assert rep["response_truncated"] is True
    assert 'request_download(path="' + rep["spilled_path"] + '")' in rep["user_message"], rep
    assert "copy_file" not in rep["user_message"], rep
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")
    rep = response_guard.build_replacement("list_things", big, cap=100)
    assert 'copy_file(file_path="' + rep["spilled_path"] + '")' in rep["user_message"], rep
