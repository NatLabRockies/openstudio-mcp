"""Run logs are written by untrusted code; read-back must refuse symlinks (#179)."""
import pytest

import mcp_server.skills.results.operations as results_ops
import mcp_server.skills.simulation.operations as sim_ops

pytestmark = pytest.mark.unit


def test_tail_text_reads_regular_file(tmp_path):
    log = tmp_path / "openstudio.log"
    log.write_text("a\nb\nc\n")
    assert sim_ops._tail_text(log, 2) == "b\nc"


def test_tail_text_refuses_symlink(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    log = tmp_path / "openstudio.log"
    log.symlink_to(secret)
    assert sim_ops._tail_text(log, 10) == ""


def test_extract_errors_refuses_symlinked_err(tmp_path, monkeypatch):
    run_dir = tmp_path / "r1"
    (run_dir / "run").mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("** Severe  ** TOPSECRET\n")
    (run_dir / "run" / "eplusout.err").symlink_to(secret)
    monkeypatch.setattr(results_ops, "resolve_run_dir", lambda *_a, **_k: run_dir)
    monkeypatch.setattr(results_ops, "user_run_root", lambda: tmp_path)
    res = results_ops.extract_simulation_errors_op("r1")
    assert res["ok"] is False
    assert "TOPSECRET" not in str(res)
