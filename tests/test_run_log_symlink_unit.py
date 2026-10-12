"""Run dirs and run_record.json are written by untrusted (sandboxed) code: read-back must
refuse symlinks, and nothing persisted in the record may redirect a read, a write or a
kill outside the run (#179 + run-record trust)."""
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import mcp_server.skills.results.operations as results_ops
import mcp_server.skills.simulation.operations as sim_ops
from mcp_server.skills.simulation import retention

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks/processes")


def _write_record(path: Path, **override) -> dict:
    run_dir = path
    run_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "run_id": run_dir.name, "user_key": "local", "name": "x", "status": "failed",
        "created_at": 1.0, "started_at": 1.5, "ended_at": 2.0, "pid": None,
        "run_dir": str(run_dir), "osw_path": str(run_dir / "workflow.osw"), "epw_path": None,
        "exit_code": 1, "error": None,
    }
    data.update(override)
    (run_dir / "run_record.json").write_text(json.dumps(data), encoding="utf-8")
    return data


@pytest.fixture
def run_root(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setattr(sim_ops, "user_run_root", lambda: root)
    monkeypatch.setattr(sim_ops, "user_key", lambda: "local")
    monkeypatch.setattr(results_ops, "user_run_root", lambda: root)
    sim_ops._RUNS.clear()
    yield root
    sim_ops._RUNS.clear()


def _sleeper(cwd: Path) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], cwd=str(cwd))  # noqa: S603 - fixed argv


# --- #179: bounded, symlink-refusing readers -------------------------------------------


def test_tail_text_reads_regular_file(tmp_path):
    # Validates: the tail reader returns the last N lines of an ordinary log
    log = tmp_path / "openstudio.log"
    log.write_text("a\nb\nc\n")
    assert sim_ops._tail_text(log, 2) == "b\nc"


@posix_only
def test_tail_text_refuses_symlink(tmp_path):
    # Regression: a measure could swap openstudio.log for a symlink and read any host file back
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    log = tmp_path / "openstudio.log"
    log.symlink_to(secret)
    assert sim_ops._tail_text(log, 10) is None


def test_tail_text_missing_log_is_empty(tmp_path):
    # Validates: an absent log is "" (nothing yet), distinct from a refused one (None)
    assert sim_ops._tail_text(tmp_path / "openstudio.log", 10) == ""


@posix_only
def test_extract_errors_refuses_symlinked_err(tmp_path, monkeypatch):
    # Regression: extract_simulation_errors read eplusout.err through a planted symlink
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


def test_extract_errors_oversize_err_is_truncated_not_dropped(tmp_path, monkeypatch):
    # Regression: the 16 MB cap made warning-heavy runs lose the whole error report; the head
    # is parsed and the result says it was truncated
    run_dir = tmp_path / "r1"
    (run_dir / "run").mkdir(parents=True)
    (run_dir / "run" / "eplusout.err").write_text("** Severe  ** boom\n" + ("** Warning ** w\n" * 200))
    monkeypatch.setattr(results_ops, "resolve_run_dir", lambda *_a, **_k: run_dir)
    monkeypatch.setattr(results_ops, "user_run_root", lambda: tmp_path)
    monkeypatch.setattr(results_ops, "MAX_ERR_READ_BYTES", 1024, raising=False)
    res = results_ops.extract_simulation_errors_op("r1")
    assert res["ok"] is True
    assert res["truncated"] is True
    assert len(res["severe"]) == 1


@posix_only
def test_get_run_status_err_symlink_is_refused(run_root):
    # Regression: get_run_status parsed eplusout.err through a planted symlink into error_summary
    run_dir = run_root / "run_a"
    _write_record(run_dir, status="failed")
    secret = run_root.parent / "secret.err"
    secret.write_text("** Fatal  ** TOPSECRET\n")
    (run_dir / "run").mkdir()
    (run_dir / "run" / "eplusout.err").symlink_to(secret)
    res = sim_ops.get_run_status("run_a")
    assert res["ok"] is True
    assert "error_summary" not in res["run"]
    assert "TOPSECRET" not in str(res)


def test_get_run_status_oversize_err_gives_truncated_summary(run_root, monkeypatch):
    # Regression: an err file over the cap silently dropped error_summary on a failed run
    run_dir = run_root / "run_a"
    _write_record(run_dir, status="failed")
    (run_dir / "run").mkdir()
    (run_dir / "run" / "eplusout.err").write_text("** Severe  ** boom\n" + ("** Warning ** w\n" * 200))
    monkeypatch.setattr(sim_ops, "MAX_ERR_READ_BYTES", 1024)
    res = sim_ops.get_run_status("run_a")
    summary = res["run"]["error_summary"]
    assert summary["severe_count"] == 1
    assert summary["truncated"] is True


@posix_only
def test_get_run_logs_reports_refused_symlink(run_root):
    # Regression: a refused log came back as ok:true with empty text, indistinguishable from
    # "nothing logged yet", so tampering was invisible
    run_dir = run_root / "run_a"
    _write_record(run_dir)
    secret = run_root.parent / "secret.txt"
    secret.write_text("TOPSECRET")
    (run_dir / "openstudio.log").symlink_to(secret)
    res = sim_ops.get_run_logs("run_a", tail=10)
    assert res["ok"] is False
    assert "symlink" in res["error"]
    assert "TOPSECRET" not in str(res)


def test_get_run_logs_missing_log_is_ok_and_empty(run_root):
    # Validates: a run that has not logged yet is ok:true with empty text
    _write_record(run_root / "run_a")
    res = sim_ops.get_run_logs("run_a", tail=10)
    assert res["ok"] is True
    assert res["text"] == ""


@posix_only
def test_find_first_existing_refuses_symlinked_results(tmp_path):
    # Regression: sqlite3.connect / the HTML reader followed a planted eplusout.sql or eplustbl
    # symlink, and the rglob fallback descended a symlinked directory
    outside = tmp_path / "outside"
    (outside / "run").mkdir(parents=True)
    (outside / "run" / "eplusout.sql").write_bytes(b"not really sqlite")
    run_dir = tmp_path / "run_a"
    (run_dir / "run").mkdir(parents=True)
    (run_dir / "run" / "eplusout.sql").symlink_to(outside / "run" / "eplusout.sql")
    assert results_ops._find_first_existing(run_dir, ["run/eplusout.sql", "eplusout.sql"]) is None
    (run_dir / "run" / "eplusout.sql").unlink()
    (run_dir / "linked").symlink_to(outside, target_is_directory=True)
    assert results_ops._find_first_existing(run_dir, ["run/eplusout.sql", "eplusout.sql"]) is None
    (run_dir / "run" / "eplusout.sql").write_bytes(b"ok")
    assert results_ops._find_first_existing(run_dir, ["run/eplusout.sql"]) == run_dir / "run" / "eplusout.sql"


# --- run-record trust ------------------------------------------------------------------


@pytest.mark.parametrize("osw_outside", [False, True])
def test_loaded_record_ignores_persisted_paths(run_root, osw_outside):
    # Regression: run_dir/osw_path were trusted from the tenant-writable record, so a forged
    # run_dir pointed every read (and the record write-back) at another tenant's run
    victim = run_root.parent / "bob" / "run_b"
    victim.mkdir(parents=True)
    osw = run_root.parent / "evil.osw" if osw_outside else run_root / "run_a" / "custom.osw"
    _write_record(run_root / "run_a", run_dir=str(victim), osw_path=str(osw))
    rec = sim_ops._load_run_record_from_disk("run_a")
    assert rec.run_dir == run_root / "run_a"
    assert rec.osw_path == (run_root / "run_a" / "workflow.osw" if osw_outside else osw)


@posix_only
def test_loaded_record_drops_pid_not_running_in_run_dir(run_root):
    # Regression: a forged pid in the record was handed to _kill_process_group (as root) by
    # cancel_run; only a process whose cwd is the run dir can be the run's own
    run_dir = run_root / "run_a"
    run_dir.mkdir()
    stranger = _sleeper(run_root.parent)
    own = _sleeper(run_dir)
    try:
        time.sleep(0.2)
        _write_record(run_dir, status="running", pid=stranger.pid)
        assert sim_ops._load_run_record_from_disk("run_a").pid is None
        _write_record(run_dir, status="running", pid=own.pid)
        assert sim_ops._load_run_record_from_disk("run_a").pid == own.pid
        _write_record(run_dir, status="running", pid=stranger.pid)
        res = sim_ops.cancel_run("run_a")
        assert res == {"ok": True, "run_id": "run_a", "cancelled": True}
        assert stranger.poll() is None, "cancel_run must not kill a process outside the run"
    finally:
        stranger.kill()
        own.kill()


@posix_only
def test_retention_ignores_forged_running_pid(run_root):
    # Regression: a record claiming status=running with someone else's live pid kept the run
    # dir out of retention GC forever
    run_dir = run_root / "run_a"
    stranger = _sleeper(run_root.parent)
    try:
        time.sleep(0.2)
        _write_record(run_dir, status="running", pid=stranger.pid)
        assert retention._is_active(run_dir) is False
    finally:
        stranger.kill()


@posix_only
def test_persist_record_never_writes_through_symlink(run_root):
    # Regression: _persist_run_record used write_text, which follows a planted
    # run_record.json symlink and overwrote the target as root
    run_dir = run_root / "run_a"
    run_dir.mkdir()
    victim = run_root.parent / "victim.json"
    victim.write_text("keep", encoding="utf-8")
    (run_dir / "run_record.json").symlink_to(victim)
    rec = sim_ops.RunRecord(
        run_id="run_a", user_key="local", name="x", status="failed", created_at=1.0,
        started_at=None, ended_at=2.0, pid=None, run_dir=run_dir,
        osw_path=run_dir / "workflow.osw", epw_path=None, exit_code=1, error=None,
    )
    sim_ops._persist_run_record(rec)
    assert victim.read_text(encoding="utf-8") == "keep"
    assert not (run_dir / "run_record.json").is_symlink()
    assert json.loads((run_dir / "run_record.json").read_text())["run_id"] == "run_a"


@posix_only
def test_symlinked_record_is_not_loaded(run_root):
    # Regression: run_record.json itself could be a symlink to another tenant's record
    run_dir = run_root / "run_a"
    run_dir.mkdir()
    other = run_root.parent / "other_record.json"
    other.write_text(json.dumps({"run_id": "run_a", "user_key": "local", "status": "failed"}))
    (run_dir / "run_record.json").symlink_to(other)
    assert sim_ops._load_run_record_from_disk("run_a") is None
    assert results_ops._run_status_from_record(run_dir) is None
    assert retention._record(run_dir) == {}
