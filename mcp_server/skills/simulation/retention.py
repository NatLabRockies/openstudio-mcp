"""Run-directory retention: automatic age-based GC + explicit cleanup tools.

Two callers share one sweep:
  - start_retention_gc(): a background daemon (started in server.main()) that
    sweeps the WHOLE container (every user's runs) on an interval, deleting run
    dirs older than RUN_RETENTION_DAYS. Nobody calls it — it's infrastructure,
    like the sim dispatcher. Emits a `run_evicted` audit line per deletion.
  - cleanup_runs / delete_run / pin_run / unpin_run: MCP tools the agent invokes
    on the user's request, scoped to the caller's own runs.

Age = run_record.json `ended_at` (fallback: dir mtime). Pinned (`.pinned` marker)
and queued/running runs are never deleted. Only run dirs are targeted — a dir
counts as a run iff it holds run_record.json / out.osw / a run/ subdir, so saved
models under examples/ and exports/ are left alone.
"""
from __future__ import annotations

import contextlib
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from mcp_server.audit import audit
from mcp_server.config import (
    RETENTION_SWEEP_SECONDS,
    RUN_RETENTION_DAYS,
    RUN_ROOT,
    user_run_root,
)
from mcp_server.identity import user_key
from mcp_server.skills.simulation.operations import _RUNS, _pid_alive, _sim_lock
from mcp_server.util import resolve_run_dir

PIN_MARKER = ".pinned"
_NOT_A_RUN = {"examples", "exports"}  # user working dirs, never GC'd

# GC refuses to operate if RUN_ROOT is (mis)configured to a system location —
# a backstop against a catastrophic OSMCP_RUN_ROOT value wiping real data.
_FORBIDDEN_ROOTS = {
    "/", "/home", "/root", "/usr", "/etc", "/var", "/bin", "/lib", "/lib64",
    "/opt", "/tmp", "/boot", "/dev", "/proc", "/sys", "/srv", "/mnt", "/media",  # noqa: S108 — denylist, not temp usage
}


def _run_root_is_sane(root: Path) -> bool:
    """False if RUN_ROOT is a filesystem/system root we must never sweep."""
    try:
        r = root.resolve()
    except OSError:
        return False
    if len(r.parts) < 2:  # "/" or a bare drive root
        return False
    return str(r) not in _FORBIDDEN_ROOTS


def _is_real_child(d: Path, parent: Path) -> bool:
    """True only if d is a genuine, non-symlink direct child of parent (resolved).

    Defeats symlink escape: a symlinked entry — or anything whose resolved path
    leaves `parent` — is rejected, so deletion can never follow a link out of the
    swept tree.
    """
    try:
        return (not d.is_symlink()) and d.resolve().parent == parent.resolve()
    except OSError:
        return False


def _is_run_dir(d: Path) -> bool:
    """A dir is a run iff it holds a run record / OpenStudio output / run subdir."""
    if d.name in _NOT_A_RUN:
        return False
    return (
        (d / "run_record.json").exists()
        or (d / "out.osw").exists()
        or (d / "run").is_dir()
    )


def _record(d: Path) -> dict[str, Any] | None:
    rec = d / "run_record.json"
    if not rec.exists():
        return None
    try:
        return json.loads(rec.read_text())
    except Exception:
        return {}  # present but unreadable -> treat conservatively (see _is_active)


def _run_age_seconds(d: Path, now: float) -> float:
    data = _record(d)
    if data:
        ts = data.get("ended_at") or data.get("created_at")
        if ts:
            with contextlib.suppress(ValueError, TypeError):
                return max(0.0, now - float(ts))
    try:
        return max(0.0, now - d.stat().st_mtime)
    except OSError:
        return 0.0


def _is_active(d: Path) -> bool:
    """True if the run is still queued or genuinely running (never GC these)."""
    data = _record(d)
    if data is None:
        return False
    if not data:
        return True  # unreadable record -> don't risk deleting an active run
    status = data.get("status")
    if status == "queued":
        return True
    if status == "running":
        pid = data.get("pid")
        try:
            return bool(pid and _pid_alive(int(pid)))
        except (ValueError, TypeError):
            return True
    return False  # success / failed / cancelled -> terminal


def _dir_size_bytes(d: Path) -> int:
    total = 0
    for p in d.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def _forget(run_id: str) -> None:
    """Drop a deleted run from the in-memory registry."""
    with contextlib.suppress(Exception), _sim_lock:
        _RUNS.pop(run_id, None)


def _sweep_user_root(
    user_root: Path, user: str, max_age_s: float, now: float,
    *, dry_run: bool, reason: str,
) -> tuple[list[dict], int]:
    """Sweep one user's run dirs; delete (or, if dry_run, just list) the eligible
    ones older than max_age_s. Returns (records, freed_bytes)."""
    out: list[dict] = []
    freed = 0
    if not user_root.exists():
        return out, freed
    for d in sorted(user_root.iterdir()):
        if d.is_symlink() or not d.is_dir() or not _is_run_dir(d):
            continue
        if not _is_real_child(d, user_root):  # never follow a link out of the tree
            continue
        if (d / PIN_MARKER).exists() or _is_active(d):
            continue
        age = _run_age_seconds(d, now)
        if age < max_age_s:
            continue
        size = _dir_size_bytes(d)
        rec = {"run_id": d.name, "user": user,
               "age_days": round(age / 86400.0, 2), "freed_mb": round(size / 1e6, 1)}
        if not dry_run:
            shutil.rmtree(d, ignore_errors=True)
            _forget(d.name)
            audit("run_evicted", reason=reason, **rec)
        out.append(rec)
        freed += size
    return out, freed


# --------------------------------------------------------------------------
# Background daemon (whole-container, automatic)
# --------------------------------------------------------------------------

def _gc_sweep_all(now: float | None = None) -> dict[str, Any]:
    """One whole-container sweep across every user's runs (used by the daemon)."""
    if RUN_RETENTION_DAYS <= 0 or not RUN_ROOT.exists() or not _run_root_is_sane(RUN_ROOT):
        return {"deleted": [], "freed_mb": 0.0}
    now = time.time() if now is None else now
    max_age_s = RUN_RETENTION_DAYS * 86400.0
    deleted: list[dict] = []
    freed = 0
    for user_dir in sorted(RUN_ROOT.iterdir()):
        if user_dir.is_symlink() or not user_dir.is_dir():
            continue
        if not _is_real_child(user_dir, RUN_ROOT):  # only genuine RUN_ROOT/<user> dirs
            continue
        recs, f = _sweep_user_root(
            user_dir, user_dir.name, max_age_s, now, dry_run=False, reason="gc")
        deleted.extend(recs)
        freed += f
    return {"deleted": deleted, "freed_mb": round(freed / 1e6, 1)}


def _retention_loop() -> None:
    interval = max(60.0, RETENTION_SWEEP_SECONDS)
    while True:
        with contextlib.suppress(Exception):
            _gc_sweep_all()
        time.sleep(interval)


_started = False
_start_lock = threading.Lock()


def start_retention_gc() -> bool:
    """Start the background retention daemon once. No-op if GC is disabled or the
    configured RUN_ROOT is unsafe to sweep."""
    global _started
    if RUN_RETENTION_DAYS <= 0:
        return False
    if not _run_root_is_sane(RUN_ROOT):
        audit("retention_disabled", reason="unsafe_run_root", run_root=str(RUN_ROOT))
        return False
    with _start_lock:
        if _started:
            return False
        _started = True
    threading.Thread(target=_retention_loop, daemon=True, name="sim-retention").start()
    return True


# --------------------------------------------------------------------------
# MCP tool operations (caller-scoped, explicit)
# --------------------------------------------------------------------------

def cleanup_runs(older_than_days: float | None = None, dry_run: bool = True) -> dict[str, Any]:
    """Delete the caller's run dirs older than `older_than_days` (default: the
    server retention window). dry_run previews without deleting. 0 days = all
    terminal runs. Pinned and queued/running runs are skipped."""
    days = RUN_RETENTION_DAYS if older_than_days is None else float(older_than_days)
    max_age_s = max(0.0, days) * 86400.0
    recs, freed = _sweep_user_root(
        user_run_root(), user_key(), max_age_s, time.time(),
        dry_run=dry_run, reason="cleanup")
    key = "candidates" if dry_run else "deleted"
    return {"ok": True, "dry_run": dry_run, "older_than_days": days,
            key: recs, "count": len(recs), "freed_mb": round(freed / 1e6, 1)}


def delete_run(run_id: str) -> dict[str, Any]:
    """Delete one of the caller's run dirs. Refuses while queued/running."""
    try:
        run_dir = resolve_run_dir(user_run_root(), run_id)
    except FileNotFoundError:
        return {"ok": False, "error": f"Unknown run_id: {run_id}"}
    if _is_active(run_dir):
        return {"ok": False, "error": f"Run {run_id} is queued/running — cancel_run first."}
    if not _is_real_child(run_dir, user_run_root()):  # never delete via a symlink/escape
        return {"ok": False, "error": f"Refusing to delete {run_id}: not a real run dir."}
    freed = round(_dir_size_bytes(run_dir) / 1e6, 1)
    shutil.rmtree(run_dir, ignore_errors=True)
    _forget(run_id)
    audit("run_deleted", run_id=run_id, user=user_key(), freed_mb=freed)
    return {"ok": True, "run_id": run_id, "deleted": True, "freed_mb": freed}


def pin_run(run_id: str) -> dict[str, Any]:
    """Protect a run from automatic age-based GC (keep indefinitely)."""
    try:
        run_dir = resolve_run_dir(user_run_root(), run_id)
    except FileNotFoundError:
        return {"ok": False, "error": f"Unknown run_id: {run_id}"}
    (run_dir / PIN_MARKER).write_text("pinned\n", encoding="utf-8")
    audit("run_pinned", run_id=run_id, user=user_key())
    return {"ok": True, "run_id": run_id, "pinned": True}


def unpin_run(run_id: str) -> dict[str, Any]:
    """Remove a run's pin so it is eligible for cleanup again."""
    try:
        run_dir = resolve_run_dir(user_run_root(), run_id)
    except FileNotFoundError:
        return {"ok": False, "error": f"Unknown run_id: {run_id}"}
    marker = run_dir / PIN_MARKER
    was_pinned = marker.exists()
    marker.unlink(missing_ok=True)
    audit("run_unpinned", run_id=run_id, user=user_key())
    return {"ok": True, "run_id": run_id, "pinned": False, "was_pinned": was_pinned}
