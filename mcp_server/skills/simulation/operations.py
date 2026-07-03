# mcp_server/tools/workflow_tools.py
from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import psutil

from mcp_server import sandbox
from mcp_server.audit import audit
from mcp_server.config import (
    LOG_TAIL_DEFAULT,
    MAX_CONCURRENCY,
    MAX_CONCURRENCY_PER_USER,
    OSCLI_GEM_PATH,
    OSCLI_GEMFILE,
    SIM_TIMEOUT_SECONDS,
    is_path_allowed,
    pkgs_root_for,
    user_run_root,
)
from mcp_server.identity import user_key
from mcp_server.util import (
    create_run_dir,
    reject_escaping_symlinks,
    resolve_run_dir,
    safe_name,
)

# Where the MCP server stores runs inside the container
DEFAULT_LOG_TAIL = LOG_TAIL_DEFAULT

LogStream = Literal["openstudio", "energyplus"]


@dataclass
class RunRecord:
    run_id: str
    user_key: str
    name: str
    status: Literal["queued", "running", "success", "failed", "cancelled"]
    created_at: float
    started_at: float | None
    ended_at: float | None
    pid: int | None
    run_dir: Path
    osw_path: Path
    epw_path: Path | None
    exit_code: int | None
    error: str | None


# In-memory registry (good enough for one-container dev right now)
_RUNS: dict[str, RunRecord] = {}

# Global FIFO scheduling + concurrency cap. run_osw enqueues (status="queued");
# a daemon dispatcher launches up to MAX_CONCURRENCY and drains as sims finish,
# so queued runs start without needing another tool call.
_sim_lock = threading.RLock()
_queue: deque[str] = deque()
_dispatcher_started = False
_TERMINAL = frozenset({"success", "failed", "cancelled", "error"})


def _run_record_path(run_dir: Path) -> Path:
    """Return path to the JSON metadata file for a run."""
    return run_dir / "run_record.json"


def _persist_run_record(rec: RunRecord) -> None:
    """Persist minimal run metadata for restart-safe lookup."""
    try:
        rec.run_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "run_id": rec.run_id,
            "user_key": rec.user_key,
            "name": rec.name,
            "status": rec.status,
            "created_at": rec.created_at,
            "started_at": rec.started_at,
            "ended_at": rec.ended_at,
            "pid": rec.pid,
            "run_dir": str(rec.run_dir),
            "osw_path": str(rec.osw_path),
            "epw_path": str(rec.epw_path) if rec.epw_path else None,
            "exit_code": rec.exit_code,
            "error": rec.error,
        }
        _run_record_path(rec.run_dir).write_text(json.dumps(data, indent=2))
    except Exception:
        # Best-effort persistence only
        return


def _load_run_record_from_disk(run_id: str) -> RunRecord | None:
    """Load run metadata from disk if present."""
    try:
        run_dir = resolve_run_dir(user_run_root(), run_id)
    except FileNotFoundError:
        return None

    meta_path = _run_record_path(run_dir)
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text())
        return RunRecord(
            run_id=data["run_id"],
            user_key=data.get("user_key") or user_key(),
            name=data.get("name") or run_id,
            status=data.get("status") or "unknown",
            created_at=float(data.get("created_at") or 0.0),
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
            pid=data.get("pid"),
            run_dir=Path(data.get("run_dir") or str(run_dir)),
            osw_path=Path(data.get("osw_path") or (run_dir / "workflow.osw")),
            epw_path=Path(data["epw_path"]) if data.get("epw_path") else None,
            exit_code=data.get("exit_code"),
            error=data.get("error"),
        )
    except Exception:
        return None


def _get_run_record(run_id: str) -> RunRecord | None:
    """Look up a run record owned by the caller, checking memory then disk."""
    me = user_key()
    rec = _RUNS.get(run_id)
    if rec is not None:
        return rec if rec.user_key == me else None
    rec = _load_run_record_from_disk(run_id)  # disk lookup is already user-scoped
    if rec is not None and rec.user_key == me:
        _RUNS[run_id] = rec
        return rec
    return None



def _now() -> float:
    """Current epoch timestamp."""
    return time.time()


def _tail_text(path: Path, tail_lines: int) -> str:
    """Read the last N lines from a text file."""
    if not path.exists():
        return ""
    # Efficient-enough tail for our log sizes
    try:
        data = path.read_text(errors="replace").splitlines()
        return "\n".join(data[-tail_lines:])
    except Exception:
        return ""


def _copy_tree(src_dir: Path, dst_dir: Path) -> None:
    """
    Copy contents of src_dir into dst_dir (dst_dir exists).
    We do NOT copy 'run/' or typical OpenStudio outputs if present in the asset dir.
    """
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        # Skip common generated dirs in repo assets
        if item.name in ("run", "generated_files"):
            continue
        target = dst_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _load_json(path: Path) -> dict[str, Any]:
    """Parse a JSON file and return its contents as a dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, obj: dict[str, Any]) -> None:
    """Write a dict to a JSON file with indentation."""
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def validate_osw(osw_path: str, epw_path: str | None = None) -> dict[str, Any]:
    """
    Best-effort validation:
      - JSON parses
      - file exists
      - seed_file (if relative) resolves
      - weather_file (if relative) resolves
    """
    p = Path(osw_path)
    if not p.exists():
        return {"ok": False, "error": f"OSW not found: {osw_path}"}

    try:
        osw = _load_json(p)
    except Exception as e:
        return {"ok": False, "error": f"Failed to parse OSW JSON: {e}"}

    base = p.parent
    seed = osw.get("seed_file")
    weather = osw.get("weather_file")

    issues: list[str] = []

    # If an EPW override is provided, it must exist. When present, the OSW's
    # `weather_file` reference becomes optional (we may still report it as an
    # informational issue, but it won't fail validation).
    epw_override: Path | None = None
    if epw_path:
        epw_override = Path(epw_path).resolve()
        if not epw_override.exists():
            return {"ok": False, "error": f"EPW not found: {epw_path}"}

    if seed:
        seed_path = (base / seed).resolve()
        if not seed_path.exists():
            issues.append(f"seed_file not found at {seed} (resolved: {seed_path})")

    if weather:
        weather_path = (base / weather).resolve()
        if not weather_path.exists():
            msg = f"weather_file not found at {weather} (resolved: {weather_path})"
            if epw_override is None:
                issues.append(msg)
            else:
                # The OSW points at a missing weather file, but the caller intends
                # to override it with a valid EPW, so treat this as informational.
                issues.append(f"(ignored due to EPW override) {msg}")

    # If the only issues are informational "ignored due to EPW override" warnings,
    # we still consider validation successful.
    fatal_issues = [i for i in issues if not i.startswith("(ignored due to EPW override)")]
    return {"ok": len(fatal_issues) == 0, "issues": issues, "osw_dir": str(base), "osw": osw}


def _pid_alive(pid: int) -> bool:
    """True if the process is still running (not a reaped/zombie process)."""
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def _kill_process_group(pid: int, *, grace: float = 5.0) -> None:
    """Terminate the run's whole process group (SIGTERM, then SIGKILL after grace).

    Sims launch with start_new_session=True, so the child is its own group leader
    (pgid == pid); killing the group reaps forked children (EnergyPlus, ruby
    helpers) that a single-pid kill would orphan. We only signal a group we created
    (pgid == pid) — never the server's own group. Falls back to a single-pid kill
    when the group can't be resolved or on non-POSIX (no os.killpg).
    """
    pgid = None
    if hasattr(os, "getpgid") and hasattr(os, "killpg"):
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            pgid = os.getpgid(pid)
    if pgid is not None and pgid == pid:
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(pgid, signal.SIGTERM)
        with contextlib.suppress(psutil.NoSuchProcess, psutil.TimeoutExpired):
            psutil.Process(pid).wait(timeout=grace)
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(pgid, signal.SIGKILL)  # ESRCH if the group already exited
        return
    # Fallback: pgid unavailable / not a leader / non-POSIX — single-pid kill.
    with contextlib.suppress(psutil.NoSuchProcess, Exception):
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=grace)
        except psutil.TimeoutExpired:
            p.kill()


def _build_run_cmd(osw_path: Path) -> list[str]:
    """openstudio CLI command to run a staged OSW (with bundle flags)."""
    return [
        "openstudio",
        "--bundle", OSCLI_GEMFILE,
        "--bundle_path", OSCLI_GEM_PATH,
        "--bundle_without", "native_ext",
        "run", "-w", str(osw_path),
    ]


def _launch(rec: RunRecord) -> None:
    """Start the EnergyPlus subprocess for a queued run. Caller holds _sim_lock."""
    log = rec.run_dir / "openstudio.log"
    # build_env creates run_dir/tmp (TMPDIR) as root; chown after so the dropped
    # process owns it (order matters — see apply_measure).
    run_env = sandbox.build_env(rec.run_dir)
    sandbox.prepare_workdir(rec.run_dir)
    # The run owner's python_packages dir (if any) is granted read-only so
    # EnergyPlus Python plugins can import pip-installed packages from it
    # (wired into the model via PythonPlugin:SearchPaths).
    try:
        pkgs_dir = pkgs_root_for(rec.user_key)
        extra_ro = (str(pkgs_dir),) if pkgs_dir.is_dir() else ()
    except RuntimeError:  # symlinked pkgs dir — launch without the grant
        extra_ro = ()
    proc = subprocess.Popen(  # noqa: S603 - cmd built from trusted config + staged OSW path
        sandbox.wrap_cmd(_build_run_cmd(rec.osw_path), rec.run_dir, extra_ro=extra_ro),
        cwd=str(rec.run_dir),
        stdout=log.open("w", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        env=run_env,
        # New session => the child is its own process-group leader (pgid == pid),
        # so a timeout/cancel can kill the WHOLE group (EnergyPlus + any forked
        # helpers) without ever signalling the server's own group. See
        # _kill_process_group(). No-op on non-POSIX.
        start_new_session=True,
    )
    rec.pid = proc.pid
    rec.status = "running"
    rec.started_at = _now()
    audit("sim_launched", run_id=rec.run_id, user=rec.user_key, name=rec.name, pid=rec.pid)


def _dispatch_once() -> None:
    """Reap finished runs and launch queued ones, respecting the global cap and
    (when set) the per-user cap. FIFO, but a user already at their per-user limit
    is skipped so they can't monopolize the queue."""
    with _sim_lock:
        # Reap finished processes to free slots.
        for rec in _RUNS.values():
            if rec.status == "running" and rec.pid is not None and not _pid_alive(rec.pid):
                _refresh_status(rec)
                _persist_run_record(rec)

        # Tally what's running, globally and per user.
        per_user: dict[str, int] = {}
        for rec in _RUNS.values():
            if rec.status == "running":
                per_user[rec.user_key] = per_user.get(rec.user_key, 0) + 1
        running_total = sum(per_user.values())

        # Walk the queue in order: launch runnable runs, drop stale/cancelled ones,
        # leave per-user-capped runs queued for a later pass.
        drop: list[str] = []
        for run_id in list(_queue):
            if running_total >= MAX_CONCURRENCY:
                break
            rec = _RUNS.get(run_id)
            if rec is None or rec.status != "queued":
                drop.append(run_id)  # cancelled or vanished
                continue
            if MAX_CONCURRENCY_PER_USER > 0 and per_user.get(rec.user_key, 0) >= MAX_CONCURRENCY_PER_USER:
                continue  # this user is at their cap; try the next run
            _launch(rec)
            _persist_run_record(rec)
            per_user[rec.user_key] = per_user.get(rec.user_key, 0) + 1
            running_total += 1
            drop.append(run_id)
        for run_id in drop:
            with contextlib.suppress(ValueError):
                _queue.remove(run_id)


def _enforce_timeouts() -> None:
    """Terminate running sims past the wall-clock cap and mark them failed.

    OSMCP_SIM_TIMEOUT_SECONDS=0 disables. The kill (terminate -> wait -> kill)
    runs outside _sim_lock so a slow exit can't stall the dispatcher.
    """
    if SIM_TIMEOUT_SECONDS <= 0:
        return
    now = _now()
    with _sim_lock:
        expired = [
            rec for rec in _RUNS.values()
            if rec.status == "running" and rec.pid is not None
            and rec.started_at is not None
            and now - rec.started_at > SIM_TIMEOUT_SECONDS
            # Skip a process that already exited but hasn't been reaped yet: let
            # _dispatch_once()/_refresh_status() classify it by its real exit code
            # instead of force-failing a run that may have completed successfully.
            and _pid_alive(rec.pid)
        ]
    for rec in expired:
        _kill_process_group(rec.pid)  # whole group: EnergyPlus + any forked helpers
        with _sim_lock:
            rec.status = "failed"
            rec.ended_at = _now()
            rec.exit_code = -1 if rec.exit_code is None else rec.exit_code
            rec.error = (f"Simulation exceeded the {SIM_TIMEOUT_SECONDS:.0f}s wall-clock "
                         "cap (OSMCP_SIM_TIMEOUT_SECONDS)")
            _RUNS[rec.run_id] = rec
        _persist_run_record(rec)
        audit("sim_timeout", run_id=rec.run_id, user=rec.user_key,
              ran_seconds=round(now - (rec.started_at or now), 1))


def _dispatch_loop() -> None:
    while True:
        with contextlib.suppress(Exception):
            _enforce_timeouts()
        with contextlib.suppress(Exception):
            _dispatch_once()
        time.sleep(0.5)


def _ensure_dispatcher() -> None:
    """Start the background dispatcher thread once (drains queue as slots free)."""
    global _dispatcher_started
    with _sim_lock:
        if _dispatcher_started:
            return
        _dispatcher_started = True
    threading.Thread(target=_dispatch_loop, daemon=True, name="sim-dispatcher").start()


def _enqueue(run_id: str) -> None:
    with _sim_lock:
        _queue.append(run_id)


def run_osw(osw_path: str, epw_path: str | None = None, name: str | None = None,
            *, _internal: bool = False) -> dict[str, Any]:
    """
    Stage the OSW + referenced files into /runs/<descriptive_name>_<short_id>/ and execute:
      openstudio run -w <staged_osw>

    Notes on validation:
      - We always validate the OSW JSON and its seed_file reference (if any).
      - If no EPW override is provided, we also require the OSW's weather_file (if set) to exist.
      - If an EPW override is provided, we allow a missing OSW weather_file because it will be replaced.

    Access control: as a PUBLIC tool, run_osw copies the OSW's whole parent dir into
    the run dir — so an un-gated path discloses arbitrary host / other-tenant files.
    Public callers must pass an OSW (and EPW) under their own run root or a shared
    read root (is_path_allowed). `_internal=True` is the trusted path for
    run_simulation, whose server-built temp OSW lives in a private staging dir and
    whose inputs it has already validated; it is NOT exposed via the MCP tool.
    """
    src_osw = Path(osw_path).resolve()
    if not src_osw.exists():
        return {"ok": False, "error": f"OSW not found: {osw_path}"}
    if not _internal:
        # Gate BEFORE reading/validating/copying anything from the path.
        if not is_path_allowed(src_osw):
            return {"ok": False, "error": f"OSW path not allowed: {osw_path}"}
        if epw_path and not is_path_allowed(Path(epw_path)):
            return {"ok": False, "error": f"EPW path not allowed: {epw_path}"}
    # We must never FOLLOW a symlink in the OSW's tree that escapes the bundle
    # (would copy a host file into the run dir), even for the trusted internal path.
    sym_err = reject_escaping_symlinks(src_osw.parent)
    if sym_err:
        return {"ok": False, "error": sym_err}

    # Fail fast on invalid OSW (before staging any run dir)
    v = validate_osw(str(src_osw), epw_path=epw_path)
    if not v.get("ok", False):
        return {
            "ok": False,
            "error": "OSW validation failed",
            "issues": list(v.get("issues") or []),
            "validation": v,
        }

    # EPW override (optional)
    epw_src: Path | None = None
    if epw_path:
        epw_src = Path(epw_path).resolve()

    source_osw = v.get("osw") if isinstance(v.get("osw"), dict) else {}
    run_name = safe_name(name or source_osw.get("name") or src_osw.stem)

    # Create caller-scoped run directory
    run_id, run_dir = create_run_dir(user_run_root(), "run", run_name)

    # Stage OSW directory contents
    src_dir = src_osw.parent.resolve()
    _copy_tree(src_dir, run_dir)

    staged_osw = run_dir / src_osw.name
    if not staged_osw.exists():
        # In case OSW lived outside src_dir copy (unlikely), copy explicitly
        shutil.copy2(src_osw, staged_osw)

    # Load staged OSW and ensure referenced seed file is present.
    # Always stage the seed directly into run_dir (flatten any ../ refs)
    # and rewrite the OSW pointer so OpenStudio finds it.
    osw = _load_json(staged_osw)
    seed_rel = osw.get("seed_file")
    if seed_rel:
        seed_src = (src_dir / seed_rel).resolve()
        if seed_src.exists():
            # Flatten: use just the filename, always inside run_dir
            seed_dst = run_dir / Path(seed_rel).name
            if not seed_dst.exists():
                shutil.copy2(seed_src, seed_dst)
            # Rewrite OSW to point at the flattened location
            if seed_rel != Path(seed_rel).name:
                osw["seed_file"] = Path(seed_rel).name
                _dump_json(staged_osw, osw)

    # If an EPW is provided, stage it into files/ and rewrite weather_file to match
    staged_epw: Path | None = None
    if epw_src:
        files_dir = run_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        staged_epw = files_dir / epw_src.name
        shutil.copy2(epw_src, staged_epw)
        osw["weather_file"] = f"files/{epw_src.name}"
        _dump_json(staged_osw, osw)

    # Build the run command (executed later by the dispatcher when a slot frees)
    cmd = _build_run_cmd(staged_osw)

    rec = RunRecord(
        run_id=run_id,
        user_key=user_key(),
        name=run_name,
        status="queued",
        created_at=_now(),
        started_at=None,
        ended_at=None,
        pid=None,
        run_dir=run_dir,
        osw_path=staged_osw,
        epw_path=staged_epw,
        exit_code=None,
        error=None,
    )
    with _sim_lock:
        _RUNS[run_id] = rec
    audit("sim_queued", run_id=run_id, user=rec.user_key, name=run_name)
    _enqueue(run_id)
    _ensure_dispatcher()
    _dispatch_once()  # launch immediately if under the concurrency cap

    return {
        "ok": True,
        "run_id": run_id,
        "name": run_name,
        "status": rec.status,
        "run_dir": str(run_dir),
        "osw_path": str(staged_osw),
        "epw_path": str(staged_epw) if staged_epw else None,
        "command": cmd,
    }


def _refresh_status(rec: RunRecord) -> RunRecord:
    """Check if the OS process has ended and update run status accordingly."""
    _prev = rec.status
    if rec.status in _TERMINAL:
        # Already terminal (incl. cancelled) — never reclassify. Keeps a cancelled
        # run sticky (a dead pid would otherwise be read as "failed") and makes
        # refresh idempotent.
        return rec
    if rec.pid is None:
        return rec

    try:
        p = psutil.Process(rec.pid)
        if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
            return rec
    except psutil.NoSuchProcess:
        pass

    # Process ended; determine exit code from psutil if possible
    exit_code: int | None = None
    try:
        p = psutil.Process(rec.pid)
        exit_code = p.wait(timeout=0)
    except Exception:
        # Could be gone already; we'll infer failure unless out.osw says success
        exit_code = rec.exit_code

    # Look for out.osw to determine success/failure more accurately
    out_osw = rec.run_dir / "out.osw"
    status = "failed"
    err: str | None = None
    if out_osw.exists():
        try:
            out = _load_json(out_osw)
            status = "success" if out.get("completed_status") == "Success" else "failed"
        except Exception as e:
            err = f"Failed to parse out.osw: {e}"

    rec.status = status  # type: ignore[assignment]
    rec.ended_at = rec.ended_at or _now()
    rec.exit_code = exit_code if exit_code is not None else rec.exit_code
    rec.error = err or rec.error
    if _prev not in _TERMINAL and rec.status in _TERMINAL:
        audit("sim_finished", run_id=rec.run_id, user=rec.user_key,
              status=rec.status, exit_code=rec.exit_code)
    return rec


def get_run_status(run_id: str) -> dict[str, Any]:
    rec = _get_run_record(run_id)
    if not rec:
        return {
            "ok": False,
            "error": f"Unknown run_id: {run_id}",
            "hint": "Use list_files(directory='/runs') to find simulation run "
                    "directories, or run_simulation() to create one.",
        }

    with _sim_lock:
        rec = _refresh_status(rec)
        _RUNS[run_id] = rec
        _persist_run_record(rec)

    run_dict = {
        "run_id": rec.run_id,
        "name": rec.name,
        "status": rec.status,
        "created_at": rec.created_at,
        "started_at": rec.started_at,
        "ended_at": rec.ended_at,
        "pid": rec.pid,
        "run_dir": str(rec.run_dir),
        "osw_path": str(rec.osw_path),
        "epw_path": str(rec.epw_path) if rec.epw_path else None,
        "exit_code": rec.exit_code,
        "error": rec.error,
    }

    # On failure, attach error_summary from eplusout.err if available
    if rec.status == "failed":
        err_path = rec.run_dir / "run" / "eplusout.err"
        if not err_path.exists():
            err_path = rec.run_dir / "energyplus.err"
        if err_path.exists():
            try:
                from mcp_server.skills.results.err_parser import parse_err_file
                parsed = parse_err_file(err_path.read_text(errors="replace"))
                run_dict["error_summary"] = {
                    "fatal_count": len(parsed["fatal"]),
                    "severe_count": len(parsed["severe"]),
                    "warning_count": parsed["warning_count"],
                    "first_fatal": parsed["fatal"][0] if parsed["fatal"] else None,
                    "first_severe": parsed["severe"][0] if parsed["severe"] else None,
                    "summary": parsed["summary"],
                }
            except Exception:
                pass

    return {"ok": True, "run": run_dict}


def get_run_logs(run_id: str, tail: int | None = None, stream: LogStream = "openstudio") -> dict[str, Any]:
    rec = _get_run_record(run_id)
    if not rec:
        return {
            "ok": False,
            "error": f"Unknown run_id: {run_id}",
            "hint": "Use list_files(directory='/runs') to find simulation run "
                    "directories, or run_simulation() to create one.",
        }

    try:
        tail_lines = int(tail) if tail is not None else DEFAULT_LOG_TAIL
    except (ValueError, TypeError):
        tail_lines = DEFAULT_LOG_TAIL

    if stream == "openstudio":
        path = rec.run_dir / "openstudio.log"
    else:
        # EnergyPlus tends to write eplusout.err under run/ (OpenStudio convention),
        # but we also expose openstudio-collected stderr via openstudio.log.
        path = rec.run_dir / "run" / "eplusout.err"
        if not path.exists():
            path = rec.run_dir / "energyplus.err"

    return {
        "ok": True,
        "run_id": run_id,
        "stream": stream,
        "path": str(path),
        "tail": tail_lines,
        "text": _tail_text(path, tail_lines),
    }


def get_run_artifacts(run_id: str) -> dict[str, Any]:
    rec = _get_run_record(run_id)
    if rec:
        run_dir = rec.run_dir
    else:
        # Fall back to filesystem lookup — measure runs aren't registered
        try:
            run_dir = resolve_run_dir(user_run_root(), run_id)
        except FileNotFoundError:
            return {"ok": False, "error": f"Unknown run_id: {run_id}"}
    candidates = [
        run_dir / "out.osw",
        run_dir / "openstudio.log",
        run_dir / "run",
        run_dir / "generated_files",
    ]

    artifacts: list[dict[str, Any]] = []
    for p in candidates:
        if not p.exists():
            continue
        if p.is_dir():
            # shallow listing
            children = []
            for c in sorted(p.iterdir()):
                try:
                    children.append(
                        {
                            "path": str(c),
                            "name": c.name,
                            "is_dir": c.is_dir(),
                            "size": c.stat().st_size if c.is_file() else None,
                        },
                    )
                except Exception:
                    continue
            artifacts.append({"path": str(p), "name": p.name, "is_dir": True, "children": children})
        else:
            artifacts.append({"path": str(p), "name": p.name, "is_dir": False, "size": p.stat().st_size})

    return {"ok": True, "run_id": run_id, "artifacts": artifacts}


def cancel_run(run_id: str) -> dict[str, Any]:
    rec = _get_run_record(run_id)
    if not rec:
        return {"ok": False, "error": f"Unknown run_id: {run_id}"}

    pid = rec.pid
    if pid is None:
        # Queued (or never started) — mark cancelled; dispatcher skips non-queued.
        with _sim_lock:
            rec.status = "cancelled"
            rec.ended_at = rec.ended_at or _now()
            _RUNS[run_id] = rec
        _persist_run_record(rec)  # disk record must read 'cancelled' so GC can reclaim it
        audit("sim_cancelled", run_id=run_id, user=rec.user_key)
        return {"ok": True, "run_id": run_id, "cancelled": True}

    if not _pid_alive(pid):
        # Finished before the cancel landed — classify by exit code, don't mislabel
        # a completed run as cancelled.
        with _sim_lock:
            rec = _refresh_status(rec)
            _RUNS[run_id] = rec
        return {"ok": True, "run_id": run_id, "cancelled": False, "status": rec.status}
    try:
        _kill_process_group(pid)  # whole group (EnergyPlus + helpers), not just the leader
        with _sim_lock:
            rec.status = "cancelled"
            rec.ended_at = rec.ended_at or _now()
            _RUNS[run_id] = rec
        _persist_run_record(rec)  # disk record must read 'cancelled' so GC can reclaim it
        audit("sim_cancelled", run_id=run_id, user=rec.user_key)
        return {"ok": True, "run_id": run_id, "cancelled": True}
    except Exception as e:
        return {"ok": False, "run_id": run_id, "error": str(e)}


def validate_model_op() -> dict[str, Any]:
    """Pre-simulation model checks using the loaded model."""
    from mcp_server.model_manager import get_model

    model = get_model()
    errors: list[str] = []
    warnings: list[str] = []

    MAX_PER_CATEGORY = 10

    # Check weather file (warning, not error — EPW can be passed at sim time)
    wf = model.getOptionalWeatherFile()
    if not wf.is_initialized():
        warnings.append(
            "No weather file set on model — pass epw_path to run_simulation or use change_building_location",
        )

    # Check design days
    dds = model.getDesignDays()
    if len(dds) == 0:
        errors.append("No design days — HVAC sizing will fail")

    # Check thermal zones have HVAC or ideal air
    zones = model.getThermalZones()
    zones_no_hvac: list[str] = []
    for z in zones:
        equip = z.equipment()
        has_ideal = z.useIdealAirLoads()
        if len(equip) == 0 and not has_ideal:
            zones_no_hvac.append(z.nameString())
    if zones_no_hvac:
        shown = zones_no_hvac[:MAX_PER_CATEGORY]
        msg = f"{len(zones_no_hvac)} zone(s) have no HVAC or ideal air loads: {', '.join(shown)}"
        if len(zones_no_hvac) > MAX_PER_CATEGORY:
            msg += f" and {len(zones_no_hvac) - MAX_PER_CATEGORY} more"
        warnings.append(msg)

    # Check surfaces missing constructions
    surfaces = model.getSurfaces()
    no_construction: list[str] = []
    for s in surfaces:
        c = s.construction()
        if not c.is_initialized():
            no_construction.append(s.nameString())
    if no_construction:
        shown = no_construction[:MAX_PER_CATEGORY]
        msg = f"{len(no_construction)} surface(s) missing construction: {', '.join(shown)}"
        if len(no_construction) > MAX_PER_CATEGORY:
            msg += f" and {len(no_construction) - MAX_PER_CATEGORY} more"
        warnings.append(msg)

    # Air loops serving zero zones and single-zone setpoint managers without a
    # control zone are both EnergyPlus input-processing fatals. Typical cause:
    # a system-adding tool took over the loop's zones (#83).
    empty_loops = [
        loop.nameString()
        for loop in model.getAirLoopHVACs()
        if len(loop.thermalZones()) == 0
    ]
    for name in empty_loops[:MAX_PER_CATEGORY]:
        errors.append(
            f"Air loop '{name}' serves no thermal zones — EnergyPlus fatal. "
            "Usually left behind after another tool took over its zones; "
            "delete_object it or reassign zones",
        )

    orphaned_spms: list = []
    orphaned_spms.extend(model.getSetpointManagerSingleZoneReheats())
    orphaned_spms.extend(model.getSetpointManagerSingleZoneCoolings())
    orphaned_spms.extend(model.getSetpointManagerSingleZoneHeatings())
    for spm in orphaned_spms:
        if not spm.controlZone().is_initialized():
            errors.append(
                f"Setpoint manager '{spm.nameString()}' has no control zone — "
                "EnergyPlus fatal. Usually a leftover from moving its zone to "
                "another system; delete the setpoint manager or its air loop",
            )

    return {
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "zone_count": len(zones),
        "surface_count": len(surfaces),
        "design_day_count": len(dds),
    }


def run_simulation(osm_path: str, epw_path: str | None = None, name: str | None = None) -> dict[str, Any]:
    """Create a minimal OSW from an OSM file and run the simulation.

    This is the high-level entry point for running a simulation from just
    an OSM model file and an optional EPW weather file. It:
    1. Generates a minimal workflow.osw with the OSM as seed_file
    2. Delegates to run_osw() for staging and execution

    Args:
        osm_path: Path to the .osm model file
        epw_path: Optional path to an EPW weather file
        name: Optional display name for the run
    """
    osm = Path(osm_path)
    if not osm.exists():
        return {"ok": False, "error": f"OSM file not found: {osm_path}"}
    if not is_path_allowed(osm):
        return {"ok": False, "error": f"OSM path not allowed: {osm_path}"}

    # Validate EPW path upfront if provided
    epw_abs: str | None = None
    if epw_path:
        epw = Path(epw_path)
        if not epw.exists():
            return {"ok": False, "error": f"EPW file not found: {epw_path}"}
        if not is_path_allowed(epw):
            return {"ok": False, "error": f"EPW path not allowed: {epw_path}"}
        epw_abs = str(epw.resolve())

    # Stage the minimal OSW in a throwaway temp dir. run_osw() copies the staged
    # files into the real per-user run dir before it returns, so nothing here
    # needs to persist — this avoids leaving an orphan sim_* dir under /runs.
    with tempfile.TemporaryDirectory(prefix="osw_stage_") as tmp:
        stage = Path(tmp)
        staged_osm = stage / osm.name
        shutil.copy2(str(osm), str(staged_osm))

        # Stage the model's companion files/ dir (ExternalFile resources, e.g.
        # Python EMS plugin scripts). Workflow-time forward translation resolves
        # an OSM's relative OS:External:File name via the OSW search paths
        # (osw dir, then files/), so the dir must travel with the seed.
        src_files = osm.resolve().parent / "files"
        if src_files.is_dir():
            sym_err = reject_escaping_symlinks(src_files)
            if sym_err:
                return {"ok": False, "error": sym_err}
            shutil.copytree(str(src_files), str(stage / "files"), dirs_exist_ok=True)

        osw: dict[str, Any] = {
            "seed_file": osm.name,
            "file_paths": [],
            "measure_paths": [],
            "steps": [],
        }
        osw_path_out = stage / "workflow.osw"
        osw_path_out.write_text(json.dumps(osw, indent=2), encoding="utf-8")

        # Delegate to run_osw — pass epw_path so it handles staging into files/.
        # _internal=True: osm + epw are already is_path_allowed above and the temp
        # OSW is server-built in a private staging dir (not a caller-supplied path).
        return run_osw(
            osw_path=str(osw_path_out),
            epw_path=epw_abs,
            name=name or osm.stem,
            _internal=True,
        )
