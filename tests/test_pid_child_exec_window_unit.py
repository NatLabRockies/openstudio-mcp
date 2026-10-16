"""The run-record trust check (`_pid_is_runs_child`) sees an empty argv for an instant while the
sandbox shim execs the CLI (the kernel reports an empty /proc/<pid>/cmdline during execve); it must
re-read a live process instead of answering "could not inspect" (issue #212)."""
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


def test_empty_argv_during_execve_is_reread_and_judged(monkeypatch):
    # Regression: the first read landed in the exec window (argv empty) and the check returned None,
    # so test_dispatch_uses_each_run_owner flaked and cancel_run refused to signal in that instant
    proc = _Proc([[], ARGV])
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR) is True
    assert proc.reads == 2 and len(sleeps) == 1


def test_argv_that_stays_empty_on_a_live_process_is_none_after_bounded_retries(monkeypatch):
    # Validates: a live process with no argv (a kernel thread) is still "could not inspect", and the
    # re-reads are bounded so the callers (status refresh, timeout sweep, cancel) never hang
    proc = _Proc([[]])
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR) is None
    assert len(sleeps) == ops._EXEC_WINDOW_RETRIES and proc.reads == ops._EXEC_WINDOW_RETRIES + 1
    assert sum(sleeps) == pytest.approx(ops._EXEC_WINDOW_RETRIES * ops._EXEC_WINDOW_SLEEP, rel=1e-9)


def test_zombie_is_none_without_retrying(monkeypatch):
    # Validates: psutil raises ZombieProcess for an exited-but-unreaped child; that is "could not
    # inspect" at once, no sleeps (the status refresh then classifies the run from its artifacts)
    proc = _Proc([psutil.ZombieProcess(4242)])
    sleeps = _install(monkeypatch, proc)
    assert ops._pid_is_runs_child(4242, RUN_DIR) is None
    assert sleeps == [] and proc.reads == 1


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
