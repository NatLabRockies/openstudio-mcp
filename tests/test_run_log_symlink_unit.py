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
    for mod in (sim_ops, results_ops, retention):
        monkeypatch.setattr(mod, "user_run_root", lambda: root)
    monkeypatch.setattr(sim_ops, "user_key", lambda: "local")
    monkeypatch.setattr(retention, "user_key", lambda: "local")
    sim_ops._RUNS.clear()
    yield root
    sim_ops._RUNS.clear()


def _sleeper(argv_path: Path) -> subprocess.Popen:
    """A child whose argv names `argv_path`, the way a real launch names its staged OSW."""
    return subprocess.Popen(  # noqa: S603 - fixed argv
        [sys.executable, "-c", "import sys, time; time.sleep(60)", str(argv_path / "workflow.osw")],
    )


def _stop(*procs: subprocess.Popen) -> None:
    for proc in procs:
        proc.kill()
        proc.wait(timeout=10)


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
def test_loaded_record_drops_pid_that_is_not_this_runs_child(run_root):
    # Regression: a forged pid in the record was handed to _kill_process_group (as root) by
    # cancel_run; only a process whose argv names this run dir can be the run's own
    run_dir = run_root / "run_a"
    run_dir.mkdir()
    stranger = _sleeper(run_root / "run_other")
    own = _sleeper(run_dir)
    try:
        time.sleep(0.2)
        assert sim_ops._pid_is_runs_child(own.pid, run_dir) is True
        assert sim_ops._pid_is_runs_child(stranger.pid, run_dir) is False
        assert sim_ops._pid_is_runs_child(2**22 - 1, run_dir) is None
        _write_record(run_dir, status="running", pid=stranger.pid)
        assert sim_ops._load_run_record_from_disk("run_a").pid is None
        _write_record(run_dir, status="running", pid=own.pid)
        assert sim_ops._load_run_record_from_disk("run_a").pid == own.pid
        _write_record(run_dir, status="running", pid=stranger.pid)
        res = sim_ops.cancel_run("run_a")
        assert res == {"ok": True, "run_id": "run_a", "cancelled": True}
        assert stranger.poll() is None, "cancel_run must not kill a process outside the run"
    finally:
        _stop(stranger, own)


@posix_only
def test_uninspectable_live_pid_is_kept_but_never_signalled(run_root, monkeypatch):
    # Regression: an identity check that could not inspect the process (AccessDenied) was
    # treated as "not ours", the pid was dropped, _refresh_status saw no out.osw and marked a
    # live run failed, and retention could then delete it
    run_dir = run_root / "run_a"
    run_dir.mkdir()
    alive = _sleeper(run_root / "run_other")
    try:
        time.sleep(0.2)
        monkeypatch.setattr(sim_ops, "_pid_is_runs_child", lambda *_a: None)
        monkeypatch.setattr(retention, "_pid_is_runs_child", lambda *_a: None)
        _write_record(run_dir, status="running", pid=alive.pid)
        assert sim_ops._load_run_record_from_disk("run_a").pid == alive.pid
        assert sim_ops.get_run_status("run_a")["run"]["status"] == "running"
        assert retention._is_active(run_dir) is True
        res = sim_ops.cancel_run("run_a")
        assert res["ok"] is False and "not this run's process" in res["error"], res
        assert alive.poll() is None
    finally:
        _stop(alive)


def test_dead_pid_in_record_is_dropped_and_run_classified(run_root):
    # Validates: a pid that no longer exists is dropped on reload and the run is classified
    # from its artifacts (no out.osw -> failed) rather than left running
    run_dir = run_root / "run_a"
    _write_record(run_dir, status="running", pid=2**22 - 1)
    assert sim_ops._load_run_record_from_disk("run_a").pid is None
    assert sim_ops.get_run_status("run_a")["run"]["status"] == "failed"


def test_cancel_run_leaves_reloaded_terminal_record_alone(run_root):
    # Regression: a reloaded terminal record has no pid, and the pid-is-None branch marked it
    # cancelled (and persisted that) before the terminal guard ran
    run_dir = run_root / "run_a"
    _write_record(run_dir, status="success", pid=None)
    res = sim_ops.cancel_run("run_a")
    assert res == {"ok": True, "run_id": "run_a", "cancelled": False, "status": "success"}
    assert json.loads((run_dir / "run_record.json").read_text())["status"] == "success"


@posix_only
def test_regular_file_inside_rejects_planted_parent_link(tmp_path):
    # Regression: the staging copies and SDK loads checked only the leaf, so run/ planted as a
    # symlink to another tenant's run made run/in.osm look like a regular file of this run
    from mcp_server.util import is_regular_file_inside

    outside = tmp_path / "outside" / "run"
    outside.mkdir(parents=True)
    (outside / "in.osm").write_text("x")
    run_dir = tmp_path / "run_a"
    run_dir.mkdir()
    (run_dir / "run").symlink_to(outside, target_is_directory=True)
    assert is_regular_file_inside(run_dir / "run" / "in.osm", run_dir) is False
    (run_dir / "run").unlink()
    (run_dir / "run").mkdir()
    (run_dir / "run" / "in.osm").write_text("x")
    assert is_regular_file_inside(run_dir / "run" / "in.osm", run_dir) is True
    (run_dir / "run" / "in.idf").symlink_to(outside / "in.osm")
    assert is_regular_file_inside(run_dir / "run" / "in.idf", run_dir) is False


@posix_only
@pytest.mark.parametrize("identity", [False, None])
def test_timeout_enforcement_never_signals_unverified_pid(run_root, monkeypatch, identity):
    # Regression: _enforce_timeouts killed an expired record's pid on liveness alone, so a
    # reused or uninspectable pid could be signalled as root on timeout
    run_dir = run_root / "run_a"
    run_dir.mkdir()
    stranger = _sleeper(run_root / "run_other")
    try:
        time.sleep(0.2)
        if identity is None:
            monkeypatch.setattr(sim_ops, "_pid_is_runs_child", lambda *_a: None)
        monkeypatch.setattr(sim_ops, "SIM_TIMEOUT_SECONDS", 1)
        rec = sim_ops.RunRecord(
            run_id="run_a", user_key="local", name="x", status="running", created_at=1.0,
            started_at=1.0, ended_at=None, pid=stranger.pid, run_dir=run_dir,
            osw_path=run_dir / "workflow.osw", epw_path=None, exit_code=None, error=None,
        )
        sim_ops._RUNS["run_a"] = rec
        sim_ops._enforce_timeouts()
        assert stranger.poll() is None
        assert rec.status == "running"
    finally:
        _stop(stranger)


@posix_only
def test_cancel_run_refuses_foreign_pid_on_cached_record(run_root):
    # Regression: an in-memory record whose pid had been reused by another process was
    # signalled as root; the identity check now runs right before the kill
    run_dir = run_root / "run_a"
    run_dir.mkdir()
    stranger = _sleeper(run_root / "run_other")
    try:
        time.sleep(0.2)
        rec = sim_ops.RunRecord(
            run_id="run_a", user_key="local", name="x", status="running", created_at=1.0,
            started_at=1.0, ended_at=None, pid=stranger.pid, run_dir=run_dir,
            osw_path=run_dir / "workflow.osw", epw_path=None, exit_code=None, error=None,
        )
        sim_ops._RUNS["run_a"] = rec
        res = sim_ops.cancel_run("run_a")
        assert res["ok"] is False
        assert "not this run's process" in res["error"], res
        assert stranger.poll() is None
    finally:
        _stop(stranger)


@posix_only
def test_retention_ignores_forged_running_pid(run_root):
    # Regression: a record claiming status=running with someone else's live pid kept the run
    # dir out of retention GC forever; a pid that cannot be inspected is still kept
    run_dir = run_root / "run_a"
    stranger = _sleeper(run_root / "run_other")
    try:
        time.sleep(0.2)
        _write_record(run_dir, status="running", pid=stranger.pid)
        assert retention._is_active(run_dir) is False
        _write_record(run_dir, status="running", pid=2**22 - 1)
        assert retention._is_active(run_dir) is False  # not alive at all
    finally:
        _stop(stranger)


def test_reloaded_running_record_without_pid_classifies_from_out_osw(run_root):
    # Regression: a run that finished while the server was down reloads with no trusted pid
    # and stayed "running" forever (and held a concurrency slot)
    run_dir = run_root / "run_a"
    _write_record(run_dir, status="running", pid=None)
    (run_dir / "out.osw").write_text(json.dumps({"completed_status": "Success", "pad": "x" * 70_000}))
    res = sim_ops.get_run_status("run_a")
    assert res["run"]["status"] == "success"


def test_unreadable_out_osw_is_reported_not_silently_failed(run_root):
    # Regression: an out.osw over the record cap became {} and the run was marked failed
    # with no explanation
    run_dir = run_root / "run_a"
    _write_record(run_dir, status="running", pid=None)
    (run_dir / "out.osw").write_text("{not json")
    res = sim_ops.get_run_status("run_a")
    assert res["run"]["status"] == "failed"
    assert "Failed to parse out.osw" in res["run"]["error"]


def test_malformed_record_fields_never_raise(run_root):
    # Regression: a record with status={"bad": 1} reached `status in _TERMINAL` and raised
    # TypeError through MCP; other fields were not coerced either
    run_dir = run_root / "run_a"
    _write_record(run_dir, status={"bad": 1}, created_at="soon", pid="abc", exit_code=[1], run_id="../x")
    res = sim_ops.get_run_status("run_a")
    assert res["ok"] is True
    assert res["run"]["run_id"] == "run_a"
    assert res["run"]["status"] == "unknown"
    assert res["run"]["pid"] is None and res["run"]["exit_code"] is None


@posix_only
def test_get_run_logs_refuses_symlinked_parent_dir(run_root):
    # Regression: O_NOFOLLOW only covers the leaf; run/ planted as a symlink to another dir
    # made the energyplus stream read that dir's eplusout.err
    run_dir = run_root / "run_a"
    _write_record(run_dir)
    outside = run_root.parent / "outside" / "run"
    outside.mkdir(parents=True)
    (outside / "eplusout.err").write_text("** Fatal  ** TOPSECRET\n")
    (run_dir / "run").symlink_to(outside, target_is_directory=True)
    res = sim_ops.get_run_logs("run_a", stream="energyplus")
    assert res["ok"] is False
    assert "TOPSECRET" not in str(res)


@posix_only
def test_pin_run_never_writes_through_symlink(run_root):
    # Regression: pin_run used write_text on run_dir/.pinned, which followed a planted link
    run_dir = run_root / "run_a"
    run_dir.mkdir()
    victim = run_root.parent / "victim.txt"
    victim.write_text("keep")
    (run_dir / ".pinned").symlink_to(victim)
    res = retention.pin_run("run_a")
    assert res["ok"] is False
    assert victim.read_text() == "keep"


@posix_only
def test_get_run_artifacts_skips_symlinks(run_root):
    # Regression: get_run_artifacts listed through a symlinked run/ dir (names and sizes of
    # files outside the run)
    run_dir = run_root / "run_a"
    _write_record(run_dir)
    (run_dir / "openstudio.log").write_text("ok")
    outside = run_root.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x")
    (run_dir / "run").symlink_to(outside, target_is_directory=True)
    res = sim_ops.get_run_artifacts("run_a")
    assert [a["name"] for a in res["artifacts"]] == ["openstudio.log"]


@posix_only
def test_bundle_zip_refuses_symlinked_reports_dir(tmp_path):
    # Regression: the signed bundle download zipped a symlinked reports/ dir, i.e. files
    # outside the run
    import zipfile

    from mcp_server.skills.file_transfer import routes

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.html").write_text("x")
    run_dir = tmp_path / "run_a"
    run_dir.mkdir()
    (run_dir / "ok.txt").write_text("ok")
    (run_dir / "reports").symlink_to(outside, target_is_directory=True)
    response = routes._zip_bundle(run_dir)
    with zipfile.ZipFile(response.path) as zf:
        assert zf.namelist() == ["ok.txt"]


@posix_only
def test_copy_file_refuses_symlinks(run_root, monkeypatch):
    # Regression: copy_file's copytree followed a planted link inside a run dir and copy2
    # wrote through an existing destination symlink
    monkeypatch.setattr("mcp_server.config.is_path_allowed", lambda *_a, **_k: True)
    src = run_root / "run_a"
    src.mkdir()
    outside = run_root.parent / "secret.txt"
    outside.write_text("secret")
    (src / "stolen.txt").symlink_to(outside)
    res = results_ops.copy_file(str(src), str(run_root / "exports"))
    assert res["ok"] is False and res["error"] == "symlink_in_source"
    victim = run_root.parent / "victim.txt"
    victim.write_text("keep")
    (run_root / "exports").mkdir(exist_ok=True)
    (run_root / "exports" / "plain.txt").symlink_to(victim)
    (src / "plain.txt").write_text("new")
    res = results_ops.copy_file(str(src / "plain.txt"), str(run_root / "exports"))
    assert res["ok"] is False and res["error"] == "symlink_refused"
    assert victim.read_text() == "keep"


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


@posix_only
def test_launch_log_is_not_opened_through_symlink(tmp_path):
    # Regression: _launch opened openstudio.log with a truncating, symlink-following mode
    from mcp_server.util import open_nofollow_for_write

    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    (tmp_path / "openstudio.log").symlink_to(victim)
    with pytest.raises(OSError, match="symbolic link"):
        open_nofollow_for_write(tmp_path / "openstudio.log")
    assert victim.read_text() == "keep"


# ------------------------------------------------- queued runs across a restart (#175)

def test_queued_record_from_previous_server_fails_on_reload(run_root):
    # Regression: the scheduler queue is in-memory, so a record persisted as "queued" by a
    # previous server process was reloaded as queued and stayed queued forever (never
    # dispatched, never terminal); reproduced with a real restart on 2026-10-12
    run_dir = run_root / "run_a"
    _write_record(run_dir, status="queued", pid=None, started_at=None, ended_at=None, exit_code=None)
    rec = sim_ops._load_run_record_from_disk("run_a")
    assert rec.status == "failed"
    assert "restarted before this run started" in rec.error
    assert rec.ended_at is not None
    res = sim_ops.get_run_status("run_a")
    assert res["ok"] is True and res["run"]["status"] == "failed", res
    assert "restarted" in res["run"]["error"]
    on_disk = json.loads((run_dir / "run_record.json").read_text())
    assert on_disk["status"] == "failed", "the failed status must be persisted so GC can reclaim the dir"
    res = sim_ops.cancel_run("run_a")
    assert res == {"ok": True, "run_id": "run_a", "cancelled": False, "status": "failed"}


def test_retention_keeps_queued_run_only_while_this_process_queues_it(run_root):
    # Regression: retention treated any on-disk "queued" record as active, so an orphaned
    # queued run from a previous server process was never GC-eligible
    run_dir = run_root / "run_a"
    _write_record(run_dir, status="queued", pid=None, started_at=None, ended_at=None, exit_code=None)
    assert retention._is_active(run_dir) is False
    rec = sim_ops.RunRecord(
        run_id="run_a", user_key="local", name="x", status="queued", created_at=1.0,
        started_at=None, ended_at=None, pid=None, run_dir=run_dir,
        osw_path=run_dir / "workflow.osw", epw_path=None, exit_code=None, error=None,
    )
    sim_ops._RUNS["run_a"] = rec
    try:
        assert retention._is_active(run_dir) is True
        # Regression (Codex review): the dispatcher sets memory to "running" before it
        # persists, so disk still says "queued" for a run that has just launched; that
        # window must not make the dir reclaimable.
        rec.status = "running"
        assert retention._is_active(run_dir) is True
        rec.status = "failed"
        assert retention._is_active(run_dir) is False
    finally:
        sim_ops._RUNS.pop("run_a", None)

