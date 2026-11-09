"""Unit tests for background apply_measure's run plumbing (issue #245).

The measure side imports openstudio, so these cover the simulation-queue half:
the CLI mode flag on launch and get_run_status's one-shot on_finish hook. The
subprocess launch and the run's status refresh are the only things mocked.
"""
from pathlib import Path

import pytest

import mcp_server.skills.simulation.operations as ops

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch):
    monkeypatch.setattr(ops, "_persist_run_record", lambda _rec: None)
    monkeypatch.setattr(ops, "_ensure_dispatcher", lambda: None)
    ops._RUNS.clear()
    ops._queue.clear()
    yield
    ops._RUNS.clear()
    ops._queue.clear()


def _running_rec(run_dir: Path, on_finish=None) -> ops.RunRecord:
    rec = ops.RunRecord(
        run_id="measure_x_0123456789ab", user_key="local", name="x", status="running",
        created_at=0.0, started_at=1.0, ended_at=None, pid=None,
        run_dir=run_dir, osw_path=run_dir / "workflow.osw",
        epw_path=None, exit_code=None, error=None, on_finish=on_finish,
    )
    ops._RUNS[rec.run_id] = rec
    return rec


def test_build_run_cmd_places_run_flag_before_workflow():
    # Validates: a background measure launches `openstudio run --measures_only -w <osw>`, not a full simulation
    cmd = ops._build_run_cmd(Path("/runs/m/workflow.osw"), "--measures_only")
    assert cmd[-4:] == ["run", "--measures_only", "-w", "/runs/m/workflow.osw"]
    assert ops._build_run_cmd(Path("/runs/s/w.osw"))[-3:] == ["run", "-w", "/runs/s/w.osw"]


def test_queue_staged_run_launches_through_dispatcher_with_flag(monkeypatch, tmp_path):
    # Validates: queue_staged_run uses the shared queue and launch path, carrying the measure's run flag
    launched: list[ops.RunRecord] = []

    def fake_launch(rec):
        launched.append(rec)
        rec.status = "running"
        rec.pid = 4242

    monkeypatch.setattr(ops, "_launch", fake_launch)
    rec = ops.queue_staged_run("measure_x_0123456789ab", tmp_path, tmp_path / "workflow.osw", "x",
                               run_flag="--postprocess_only")
    assert launched == [rec]
    assert ops._RUNS["measure_x_0123456789ab"] is rec
    assert (rec.status, rec.run_flag, rec.user_key) == ("running", "--postprocess_only", "local")
    assert list(ops._queue) == []


def test_on_finish_runs_once_when_terminal_and_result_is_kept(monkeypatch, tmp_path):
    # Validates: the measure output is adopted exactly once, on the first poll that sees the run finished
    monkeypatch.setattr(ops, "_refresh_status", lambda rec: rec)
    seen: list[str] = []

    def on_finish(snap):
        seen.append(snap.status)
        return {"ok": True, "arguments_applied": {"building_name": "B"}}

    rec = _running_rec(tmp_path, on_finish)
    first = ops.get_run_status(rec.run_id)
    assert seen == []
    assert "measure_result" not in first

    rec.status = "success"
    done = ops.get_run_status(rec.run_id)
    again = ops.get_run_status(rec.run_id)
    assert seen == ["success"]
    assert done["measure_result"] == {"ok": True, "arguments_applied": {"building_name": "B"}}
    assert again["measure_result"] == done["measure_result"]


def test_on_finish_declining_leaves_hook_for_next_poll(monkeypatch, tmp_path):
    # Validates: a poll from another session (hook returns None) does not consume the adoption
    monkeypatch.setattr(ops, "_refresh_status", lambda rec: rec)
    answers = iter([None, {"ok": False, "error": "Measure run failed (exit code 1)"}])
    rec = _running_rec(tmp_path, lambda _snap: next(answers))
    rec.status = "failed"
    rec.exit_code = 1

    declined = ops.get_run_status(rec.run_id)
    assert "measure_result" not in declined
    assert rec.on_finish is not None
    adopted = ops.get_run_status(rec.run_id)
    assert adopted["measure_result"] == {"ok": False, "error": "Measure run failed (exit code 1)"}
    assert rec.on_finish is None


def test_simulation_status_has_no_measure_result(monkeypatch, tmp_path):
    # Validates: get_run_status for an ordinary simulation keeps its response shape
    monkeypatch.setattr(ops, "_refresh_status", lambda rec: rec)
    rec = _running_rec(tmp_path)
    rec.status = "success"
    res = ops.get_run_status(rec.run_id)
    assert set(res) == {"ok", "run", "poll_interval_seconds", "wait_exhausted"}
