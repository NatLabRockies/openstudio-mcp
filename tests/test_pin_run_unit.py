"""pin_run writes its marker through the hardened writer; a non-regular entry at the marker's
name is a tool error, not an exception through MCP (rule 5; issue #190 review)."""
import os
import sys

import pytest
from test_analysis_tools import _http_tenant

from mcp_server.skills.simulation import retention

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX FIFO")


@posix_only
def test_pin_run_reports_a_fifo_at_the_marker_name_instead_of_raising(tmp_path, monkeypatch):
    # Regression: the hardened writer raises ValueError for a non-regular entry at the name;
    # pin_run caught OSError only, so a FIFO planted at .pinned (with a reader attached, so the
    # open itself succeeds) escaped as an exception instead of {"ok": False, ...}
    root = _http_tenant(monkeypatch, tmp_path)
    run_dir = root / "run_pin_1"
    run_dir.mkdir()
    fifo = run_dir / retention.PIN_MARKER
    os.mkfifo(fifo)
    reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
    try:
        res = retention.pin_run("run_pin_1")
    finally:
        os.close(reader)
    assert res["ok"] is False, res
    assert "could not write pin marker" in res["error"] and "not a regular file" in res["error"], res
    assert fifo.is_fifo()
