"""Unit tests for the get_run_status poll hint and server-side wait (issue #200).

The interval table, the response descriptors and the wait loop are the units
under test; only the status snapshot and the clock are faked. No Docker, no
openstudio import.
"""
import asyncio
import inspect
from pathlib import Path

import pytest

import mcp_server.skills.simulation.operations as ops
from mcp_server import config, tool_policy

pytestmark = pytest.mark.unit


def _mk_rec(run_id: str, **over) -> ops.RunRecord:
    base = {
        "run_id": run_id, "user_key": "local", "name": run_id, "status": "queued",
        "created_at": 0.0, "started_at": None, "ended_at": None, "pid": None,
        "run_dir": Path(run_id), "osw_path": Path(run_id) / "w.osw",
        "epw_path": None, "exit_code": None, "error": None,
    }
    base.update(over)
    return ops.RunRecord(**base)


@pytest.fixture(autouse=True)
def _reset_registry(monkeypatch):
    monkeypatch.setattr(ops, "_persist_run_record", lambda _rec: None)
    monkeypatch.setattr(ops, "_load_run_record_from_disk", lambda _run_id: None)
    monkeypatch.setattr(ops, "POLL_HINT_MIN_SECONDS", 15)
    monkeypatch.setattr(ops, "POLL_HINT_MAX_SECONDS", 300)
    ops._RUNS.clear()
    ops._queue.clear()
    yield
    ops._RUNS.clear()
    ops._queue.clear()


# ---------------------------------------------------------------- interval table

@pytest.mark.parametrize(("status", "elapsed", "queue_position", "expected"), [
    ("success", 123.0, None, 0),
    ("failed", 123.0, None, 0),
    ("cancelled", None, None, 0),
    ("error", 5.0, None, 0),
    ("queued", None, 1, 30),
    ("queued", None, 2, 60),
    ("queued", None, 4, 120),
    ("queued", None, 11, 300),      # 330 clamped to the 300 ceiling
    ("running", 0.0, None, 30),
    ("running", 59.9, None, 30),
    ("running", 60.0, None, 60),
    ("running", 299.9, None, 60),
    ("running", 300.0, None, 120),
    ("running", 3600.0, None, 120),
])
def test_poll_interval_table(status, elapsed, queue_position, expected):
    # Validates: the advisory interval is the locked 30/60/120 s tier table (issue #200),
    # 30 s per queue slot while queued, and 0 for every terminal state in _TERMINAL
    assert ops.poll_interval_seconds(status, elapsed, queue_position) == expected


@pytest.mark.parametrize(("lo", "hi", "status", "elapsed", "expected"), [
    (45, 300, "running", 0.0, 45),       # floor lifts the 30 s tier
    (15, 90, "running", 3600.0, 90),     # ceiling caps the 120 s tier
    (15, 300, "running", 3600.0, 120),   # defaults leave the tier alone
])
def test_poll_interval_clamped_by_config(monkeypatch, lo, hi, status, elapsed, expected):
    # Validates: OSMCP_POLL_HINT_MIN/MAX_SECONDS bound every non-terminal hint
    monkeypatch.setattr(ops, "POLL_HINT_MIN_SECONDS", lo)
    monkeypatch.setattr(ops, "POLL_HINT_MAX_SECONDS", hi)
    assert ops.poll_interval_seconds(status, elapsed, None) == expected


def test_terminal_hint_ignores_clamp_floor(monkeypatch):
    # Validates: a terminal run always reports 0 even when the floor is above 0,
    # so an agent never sleeps after the run has finished
    monkeypatch.setattr(ops, "POLL_HINT_MIN_SECONDS", 45)
    assert ops.poll_interval_seconds("success", 10.0, None) == 0


@pytest.mark.parametrize(("raw_min", "raw_max", "expected"), [
    ("15", "300", (15, 300)),
    ("20", "20", (20, 20)),
    ("0", "300", (15, 300)),      # min must be > 0
    ("400", "300", (15, 300)),    # min must be <= max
    ("abc", "300", (15, 300)),    # non-numeric falls back to both defaults
    ("15", "-1", (15, 300)),
])
def test_poll_hint_bounds_validation(raw_min, raw_max, expected):
    # Validates: startup rejects 0 < min <= max violations as a pair and falls back to
    # the documented defaults instead of serving a hint table that can never clamp
    assert config._poll_hint_bounds(raw_min, raw_max) == expected


# ---------------------------------------------------------------- response fields

def test_snapshot_fields_queued(monkeypatch):
    # Validates: a queued run reports its 1-based FIFO slot, no elapsed time, and a
    # hint scaled by that slot; wait_exhausted is False on a plain snapshot
    monkeypatch.setattr(ops, "_now", lambda: 1000.0)
    ops._RUNS["a"] = _mk_rec("a")
    ops._RUNS["b"] = _mk_rec("b")
    ops._queue.extend(["a", "b"])
    res = ops.get_run_status("b")
    assert res["ok"] is True
    assert res["run"]["queue_position"] == 2
    assert res["run"]["elapsed_seconds"] is None
    assert res["poll_interval_seconds"] == 60
    assert res["wait_exhausted"] is False


def test_snapshot_fields_running(monkeypatch):
    # Validates: a running run reports now - started_at and no queue position
    monkeypatch.setattr(ops, "_now", lambda: 1000.0)
    monkeypatch.setattr(ops, "_refresh_status", lambda rec: rec)
    ops._RUNS["r"] = _mk_rec("r", status="running", started_at=900.0, pid=4242)
    res = ops.get_run_status("r")
    assert res["run"]["status"] == "running"
    assert res["run"]["elapsed_seconds"] == pytest.approx(100.0, abs=0.01)
    assert res["run"]["queue_position"] is None
    assert res["poll_interval_seconds"] == 60


def test_snapshot_fields_terminal(monkeypatch):
    # Validates: a finished run reports ended_at - started_at and a 0 hint
    monkeypatch.setattr(ops, "_now", lambda: 5000.0)
    ops._RUNS["t"] = _mk_rec("t", status="success", started_at=100.0, ended_at=350.5)
    res = ops.get_run_status("t")
    assert res["run"]["elapsed_seconds"] == pytest.approx(250.5, abs=0.01)
    assert res["run"]["queue_position"] is None
    assert res["poll_interval_seconds"] == 0


def test_snapshot_cancelled_while_queued_has_no_elapsed(monkeypatch):
    # Regression: cancel_run on a queued run sets ended_at but never started_at;
    # elapsed_seconds must be None there, not a TypeError from None arithmetic
    monkeypatch.setattr(ops, "_now", lambda: 5000.0)
    ops._RUNS["c"] = _mk_rec("c", status="cancelled", started_at=None, ended_at=120.0)
    res = ops.get_run_status("c")
    assert res["ok"] is True
    assert res["run"]["elapsed_seconds"] is None
    assert res["poll_interval_seconds"] == 0


def test_response_built_from_snapshot_taken_under_lock(monkeypatch):
    # Regression: status, elapsed and queue_position were read from the live record after
    # _sim_lock was released, so a dispatcher launch in that window produced
    # status=running with queue_position=1 (Codex review of PR #216). The response must
    # come from one copy taken under the lock.
    monkeypatch.setattr(ops, "_now", lambda: 1000.0)
    ops._RUNS["q"] = _mk_rec("q")
    ops._queue.append("q")
    real_elapsed = ops._elapsed_seconds

    def launch_then_delegate(rec, now):
        # _elapsed_seconds runs after the lock drops: stand in for the dispatcher thread
        # and launch the live record right there, before the response is assembled.
        live = ops._RUNS["q"]
        live.status = "running"
        live.started_at = 900.0
        live.pid = 4242
        return real_elapsed(rec, now)

    monkeypatch.setattr(ops, "_elapsed_seconds", launch_then_delegate)
    res = ops.get_run_status("q")
    run = res["run"]
    assert (run["status"], run["queue_position"], run["elapsed_seconds"]) == ("queued", 1, None), run
    assert res["poll_interval_seconds"] == 30


def test_queue_position_skips_cancelled_predecessors(monkeypatch):
    # Regression: cancel_run leaves its entry in _queue and the dispatcher only drops it
    # on a walk it skips while every slot is busy, so a raw deque index reported the
    # next run as slot 2 (60 s hint) instead of slot 1 (Codex review of PR #216)
    monkeypatch.setattr(ops, "_now", lambda: 1000.0)
    for rid in ("a", "b", "c"):
        ops._RUNS[rid] = _mk_rec(rid)
        ops._queue.append(rid)
    ops._RUNS["a"].status = "cancelled"
    ops._RUNS["a"].ended_at = 999.0
    b = ops.get_run_status("b")
    c = ops.get_run_status("c")
    assert (b["run"]["queue_position"], b["poll_interval_seconds"]) == (1, 30), b
    assert (c["run"]["queue_position"], c["poll_interval_seconds"]) == (2, 60), c
    assert ops.get_run_status("a")["run"]["queue_position"] is None


# ---------------------------------------------------------------- wait loop

class _FakeClock:
    """Monotonic clock that only advances when the loop sleeps."""

    def __init__(self):
        self.t = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _install_snapshots(monkeypatch, snapshots):
    """Patch the single-snapshot primitive with a scripted sequence (last repeats)."""
    clock = _FakeClock()
    calls: list[str] = []
    seq = list(snapshots)

    def fake_status(run_id):
        calls.append(run_id)
        snap = seq.pop(0) if len(seq) > 1 else seq[0]
        return {k: (dict(v) if isinstance(v, dict) else v) for k, v in snap.items()}

    monkeypatch.setattr(ops, "get_run_status", fake_status)
    monkeypatch.setattr(ops.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(ops.asyncio, "sleep", clock.sleep)
    monkeypatch.setattr(ops, "WAIT_MAX_SECONDS", 50)
    return clock, calls


def _running(elapsed=1.0):
    return {"ok": True, "run": {"status": "running", "elapsed_seconds": elapsed},
            "poll_interval_seconds": 30, "wait_exhausted": False}


_DONE = {"ok": True, "run": {"status": "success", "elapsed_seconds": 9.0},
         "poll_interval_seconds": 0, "wait_exhausted": False}
_UNKNOWN = {"ok": False, "error": "Unknown run_id: nope"}


def test_wait_default_zero_is_one_snapshot(monkeypatch):
    # Validates: wait_seconds=0 (the default) keeps today's instant-return contract:
    # exactly one snapshot, no sleep, wait_exhausted stays False even though non-terminal
    clock, calls = _install_snapshots(monkeypatch, [_running()])
    res = asyncio.run(ops.wait_for_run_status("r", 0))
    assert calls == ["r"]
    assert clock.sleeps == []
    assert res["run"]["status"] == "running"
    assert res["wait_exhausted"] is False


def test_wait_returns_on_terminal_before_cap(monkeypatch):
    # Validates: the loop returns on the first terminal snapshot with wait_exhausted False
    clock, calls = _install_snapshots(monkeypatch, [_running(), _running(2.0), _DONE])
    res = asyncio.run(ops.wait_for_run_status("r", 50))
    assert res["run"]["status"] == "success"
    assert res["wait_exhausted"] is False
    assert len(calls) == 3
    assert clock.sleeps == [1.0, 1.0]


def test_wait_unknown_run_returns_before_any_sleep(monkeypatch):
    # Validates: an unknown (or other user's) run never sleeps, so wait_seconds cannot
    # be used to distinguish "does not exist" from "not mine" by latency
    clock, calls = _install_snapshots(monkeypatch, [_UNKNOWN])
    res = asyncio.run(ops.wait_for_run_status("nope", 50))
    assert res == _UNKNOWN
    assert calls == ["nope"]
    assert clock.sleeps == []


def test_wait_exhausted_at_cap(monkeypatch):
    # Validates: with the run still running the loop sleeps 1 s ticks up to the cap and
    # returns the last snapshot flagged wait_exhausted=True
    clock, calls = _install_snapshots(monkeypatch, [_running()])
    res = asyncio.run(ops.wait_for_run_status("r", 5))
    assert res["run"]["status"] == "running"
    assert res["wait_exhausted"] is True
    assert clock.sleeps == [1.0] * 5
    assert len(calls) == 6, "one snapshot before the first sleep plus one per tick"


def test_wait_clamps_to_cap_without_wall_clock(monkeypatch):
    # Validates: wait_seconds above OSMCP_WAIT_MAX_SECONDS is clamped to the cap, not
    # honoured, so a Desktop-safe cap holds regardless of what the agent asks for
    clock, _calls = _install_snapshots(monkeypatch, [_running()])
    monkeypatch.setattr(ops, "WAIT_MAX_SECONDS", 3)
    res = asyncio.run(ops.wait_for_run_status("r", 600))
    assert res["wait_exhausted"] is True
    assert sum(clock.sleeps) == pytest.approx(3.0, abs=1e-9)


def test_wait_negative_treated_as_zero(monkeypatch):
    # Validates: a negative wait_seconds is one snapshot, never a negative deadline
    clock, calls = _install_snapshots(monkeypatch, [_running()])
    res = asyncio.run(ops.wait_for_run_status("r", -7))
    assert calls == ["r"]
    assert clock.sleeps == []
    assert res["wait_exhausted"] is False


def test_wait_deadline_counts_snapshot_time(monkeypatch):
    # Validates: the deadline is taken before the first snapshot, so a slow snapshot
    # shortens the remaining wait instead of extending the call past wait_seconds
    clock, _calls = _install_snapshots(monkeypatch, [_running()])
    scripted = ops.get_run_status

    def slow_status(run_id):
        clock.t += 0.6   # each snapshot costs 0.6 s of fake wall clock
        return scripted(run_id)

    monkeypatch.setattr(ops, "get_run_status", slow_status)
    asyncio.run(ops.wait_for_run_status("r", 2))
    assert clock.t - 100.0 <= 2.0 + 0.6, "call overran wait_seconds by more than one snapshot"
    assert all(s <= 1.0 for s in clock.sleeps)


def test_wait_cancellation_stops_loop(monkeypatch):
    # Validates: cancelling the waiting coroutine (client disconnect) stops the loop and
    # drops it from the active-waiter gauge; CancelledError is never swallowed
    monkeypatch.setattr(ops, "get_run_status", lambda _run_id: _running())
    monkeypatch.setattr(ops, "WAIT_MAX_SECONDS", 50)
    remaining = -1

    async def _run():
        nonlocal remaining
        task = asyncio.create_task(ops.wait_for_run_status("r", 50))
        await asyncio.sleep(0.05)
        assert ops.active_waiters() == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        remaining = ops.active_waiters()

    asyncio.run(_run())
    assert remaining == 0


def test_get_run_status_tool_is_async():
    # Validates: the registered get_run_status handler is a coroutine so a 50 s wait
    # holds no FastMCP worker thread (a sync wrapper would reserve one per waiter)
    from mcp_server.skills.simulation import tools as sim_tools

    fns: dict[str, object] = {}

    class _Rec:
        def tool(self, *a, name=None, **kw):
            def deco(fn):
                fns[name or fn.__name__] = fn
                return fn
            return deco

    sim_tools.register(_Rec())
    assert inspect.iscoroutinefunction(fns["get_run_status"])
    assert inspect.signature(fns["get_run_status"]).parameters["wait_seconds"].default == 0


# ---------------------------------------------------------------- startup warning

@pytest.mark.parametrize(("transport", "cap", "warns"), [
    ("http", 60, True),
    ("streamable-http", 56, True),
    ("http", 55, False),
    ("http", 50, False),
    ("stdio", 600, False),
])
def test_wait_cap_proxy_warning(monkeypatch, transport, cap, warns):
    # Validates: under HTTP a cap above 55 s is flagged at startup (nginx proxy_read_timeout
    # defaults to 60 s and would cut the held call); stdio has no proxy and never warns
    monkeypatch.setenv("MCP_TRANSPORT", transport)
    msg = tool_policy.wait_cap_proxy_warning(cap)
    if warns:
        assert msg is not None and "OSMCP_WAIT_MAX_SECONDS" in msg and str(cap) in msg
    else:
        assert msg is None
