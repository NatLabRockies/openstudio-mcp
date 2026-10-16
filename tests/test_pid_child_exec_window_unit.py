"""The run-record trust check (`_pid_is_runs_child`) sees an empty argv for an instant while the
sandbox shim execs the CLI (the kernel reports an empty /proc/<pid>/cmdline during execve). A one-shot
caller (cancel_run) asks it to re-read a live process instead of answering "could not inspect"; the
periodic callers (the timeout sweep under the simulation lock, status refresh, retention) never sleep
and see the process again on their next pass (issue #212)."""
import time
from pathlib import Path

import psutil
import pytest

from mcp_server.skills.simulation import operations as ops

pytestmark = pytest.mark.unit

RUN_DIR = Path("/runs/alice/run_x")
ARGV = ["/opt/openstudio/bin/openstudio", "run", "-w", str(RUN_DIR / "in.osw")]


class _Proc:
    """Stands in for psutil.Process: cmdline() answers from a script, the last entry repeating."""

    def __init__(self, cmdlines, status=psutil.STATUS_RUNNING):
        self._cmdlines, self._status, self.reads = list(cmdlines), status, 0

    def cmdline(self):
        self.reads += 1
        answer = self._cmdlines.pop(0) if len(self._cmdlines) > 1 else self._cmdlines[0]
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def status(self):
        return self._status


def _install(monkeypatch, proc: _Proc) -> list[float]:
    sleeps: list[float] = []
    monkeypatch.setattr(ops.psutil, "Process", lambda _pid: proc)
    monkeypatch.setattr(ops.time, "sleep", sleeps.append)
    return sleeps


def test_empty_argv_during_execve_is_reread_and_judged_when_asked(monkeypatch):
    # Regression: the first read landed in the exec window (argv empty) and the check returned None,
    # so cancel_run refused to signal in that instant; the one-shot caller asks for a re-read
    proc = _Proc([[], ARGV])
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR, wait_for_exec=True) is True
    assert proc.reads == 2 and len(sleeps) == 1


def test_default_path_answers_none_at_once_without_sleeping(monkeypatch):
    # Regression: review of the first version found the re-read sleeping inside the timeout sweep,
    # which holds the global simulation lock; a tenant could plant records whose pid is a process it
    # keeps argv-less and stall every tenant's status, queue and cancel updates by N x 250 ms per
    # sweep. Without wait_for_exec an empty argv is None immediately, no sleep, one read.
    proc = _Proc([[], ARGV])
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR) is None
    assert sleeps == [] and proc.reads == 1


def test_timeout_sweep_never_sleeps_on_uninspectable_records(monkeypatch):
    # Regression: the same finding at the caller: twelve expired records whose pid stays argv-less
    # must cost the sweep (and the lock it holds) no sleep at all, and none of them is signalled
    proc = _Proc([[]])
    sleeps = _install(monkeypatch, proc)
    monkeypatch.setattr(ops, "_pid_alive", lambda _pid: True)
    monkeypatch.setattr(ops, "SIM_TIMEOUT_SECONDS", 60)
    killed: list[int] = []
    monkeypatch.setattr(ops, "_kill_process_group", killed.append)
    monkeypatch.setattr(ops, "_persist_run_record", lambda _rec: None)
    records = []
    for i in range(12):
        rec = ops.RunRecord(
            run_id=f"stale_{i}", user_key="mallory", name="stale", status="running",
            created_at=time.time() - 7200, started_at=time.time() - 7200, ended_at=None, pid=4242,
            run_dir=RUN_DIR, osw_path=RUN_DIR / "in.osw", epw_path=None, exit_code=None, error=None,
        )
        monkeypatch.setitem(ops._RUNS, rec.run_id, rec)
        records.append(rec)
    ops._enforce_timeouts()
    assert sleeps == [] and proc.reads == 12
    assert killed == [] and all(rec.status == "running" for rec in records)


def test_argv_that_stays_empty_on_a_live_process_is_none_after_bounded_retries(monkeypatch):
    # Validates: a live process with no argv (a kernel thread) is still "could not inspect", and the
    # re-reads a one-shot caller asked for are bounded, so cancel_run never hangs
    proc = _Proc([[]])
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR, wait_for_exec=True) is None
    assert len(sleeps) == ops._EXEC_WINDOW_RETRIES and proc.reads == ops._EXEC_WINDOW_RETRIES + 1
    assert sum(sleeps) == pytest.approx(ops._EXEC_WINDOW_RETRIES * ops._EXEC_WINDOW_SLEEP, rel=1e-9)


def test_zombie_is_none_without_retrying(monkeypatch):
    # Validates: psutil raises ZombieProcess for an exited-but-unreaped child; that is "could not
    # inspect" at once, no sleeps (the status refresh then classifies the run from its artifacts)
    proc = _Proc([psutil.ZombieProcess(4242)])
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR, wait_for_exec=True) is None
    assert sleeps == [] and proc.reads == 1


def test_empty_argv_on_a_zombie_by_status_is_none_without_sleeping(monkeypatch):
    # Validates: a psutil that returns [] for a zombie (instead of raising) is caught by the status
    # check before any sleep, even for the one-shot caller
    proc = _Proc([[]], status=psutil.STATUS_ZOMBIE)
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR, wait_for_exec=True) is None
    assert sleeps == [] and proc.reads == 1


def test_process_vanishing_between_reads_is_none(monkeypatch):
    # Validates: NoSuchProcess raised by the re-read (reaped mid-window) is "could not inspect"
    proc = _Proc([[], psutil.NoSuchProcess(4242)])
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR, wait_for_exec=True) is None
    assert len(sleeps) == 1 and proc.reads == 2


def test_live_process_whose_argv_names_another_run_is_false(monkeypatch):
    # Validates: a pid reused by a process outside this run dir is False (never signalled), unchanged
    proc = _Proc([["/opt/openstudio/bin/openstudio", "run", "-w", "/runs/bob/run_y/in.osw"]])
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR) is False
    assert sleeps == [] and proc.reads == 1


def test_process_gone_is_none(monkeypatch):
    # Validates: NoSuchProcess (reaped between the liveness check and this one) is "could not inspect"
    proc = _Proc([psutil.NoSuchProcess(4242)])
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR) is None
    assert sleeps == []
