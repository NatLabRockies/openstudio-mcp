"""Unit tests for the simulation queue policy (FIFO + concurrency cap).

The queue *logic* is the unit under test; only its dependencies are mocked
(the subprocess launch and process-liveness check). No Docker/OpenStudio.
"""
from pathlib import Path

import pytest

import mcp_server.skills.simulation.operations as ops

pytestmark = pytest.mark.unit


def _mk_rec(run_id: str) -> ops.RunRecord:
    return ops.RunRecord(
        run_id=run_id, name=run_id, status="queued",
        created_at=0.0, started_at=None, ended_at=None, pid=None,
        run_dir=Path(run_id), osw_path=Path(run_id) / "w.osw",
        epw_path=None, exit_code=None, error=None,
    )


@pytest.fixture(autouse=True)
def _reset_registry():
    ops._RUNS.clear()
    ops._queue.clear()
    yield
    ops._RUNS.clear()
    ops._queue.clear()


def test_queue_caps_running_at_max_concurrency(monkeypatch):
    # Validates: the dispatcher never launches more than MAX_CONCURRENCY at once
    monkeypatch.setattr(ops, "MAX_CONCURRENCY", 2)
    alive: set[int] = set()

    def fake_launch(rec):
        rec.pid = int(rec.run_id[1:]) + 1000
        rec.status = "running"
        alive.add(rec.pid)

    monkeypatch.setattr(ops, "_launch", fake_launch)
    monkeypatch.setattr(ops, "_pid_alive", lambda pid: pid in alive)

    for i in range(4):
        rid = f"r{i}"
        ops._RUNS[rid] = _mk_rec(rid)
        ops._enqueue(rid)
    ops._dispatch_once()

    running = [r.run_id for r in ops._RUNS.values() if r.status == "running"]
    queued = [r.run_id for r in ops._RUNS.values() if r.status == "queued"]
    assert len(running) == 2, f"cap=2 must cap concurrent runs, got running={running}"
    assert len(queued) == 2, f"remaining must stay queued, got queued={queued}"
    assert running == ["r0", "r1"], f"FIFO: first-enqueued launch first, got {running}"


def test_slot_frees_on_completion_launches_next_fifo(monkeypatch):
    # Validates: when a running sim finishes, the next queued sim (FIFO) starts
    monkeypatch.setattr(ops, "MAX_CONCURRENCY", 1)
    alive: set[int] = set()

    def fake_launch(rec):
        rec.pid = int(rec.run_id[1:]) + 1000
        rec.status = "running"
        alive.add(rec.pid)

    def fake_refresh(rec):
        rec.status = "success"
        return rec

    monkeypatch.setattr(ops, "_launch", fake_launch)
    monkeypatch.setattr(ops, "_pid_alive", lambda pid: pid in alive)
    monkeypatch.setattr(ops, "_refresh_status", fake_refresh)
    monkeypatch.setattr(ops, "_persist_run_record", lambda _rec: None)

    for i in range(3):
        rid = f"r{i}"
        ops._RUNS[rid] = _mk_rec(rid)
        ops._enqueue(rid)
    ops._dispatch_once()
    assert ops._RUNS["r0"].status == "running", "first run starts under cap=1"
    assert ops._RUNS["r1"].status == "queued"
    assert ops._RUNS["r2"].status == "queued"

    # r0's process exits -> next dispatch reaps it and launches r1
    alive.discard(ops._RUNS["r0"].pid)
    ops._dispatch_once()
    assert ops._RUNS["r0"].status == "success", "finished run is reaped"
    assert ops._RUNS["r1"].status == "running", "freed slot launches next FIFO run"
    assert ops._RUNS["r2"].status == "queued", "third run still waits"


def test_cancelled_queued_run_is_not_launched(monkeypatch):
    # Regression: a queued run cancelled before launch must never start
    monkeypatch.setattr(ops, "MAX_CONCURRENCY", 1)
    launched: list[str] = []
    monkeypatch.setattr(ops, "_launch", lambda rec: launched.append(rec.run_id))
    monkeypatch.setattr(ops, "_pid_alive", lambda _pid: True)

    for i in range(2):
        rid = f"r{i}"
        ops._RUNS[rid] = _mk_rec(rid)
        ops._enqueue(rid)
    # Cancel the queued tail before any dispatch
    ops._RUNS["r1"].status = "cancelled"
    ops._dispatch_once()  # launches r0
    ops._RUNS["r0"].status = "success"  # free the slot
    ops._dispatch_once()  # r1 is cancelled -> skipped, nothing else to run

    assert launched == ["r0"], f"cancelled run must be skipped, launched={launched}"
    assert ops._RUNS["r1"].status == "cancelled"
