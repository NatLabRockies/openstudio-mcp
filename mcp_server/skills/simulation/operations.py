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
from mcp_server.confined_copy import copy_tree_confined
from mcp_server.config import (
    LOG_TAIL_DEFAULT,
    MAX_CONCURRENCY,
    MAX_CONCURRENCY_PER_USER,
    OSCLI_GEM_PATH,
    OSCLI_GEMFILE,
    SIM_TIMEOUT_SECONDS,
    InvalidUserKeyError,
    is_path_allowed,
    pkgs_root_for,
    user_run_root,
)
from mcp_server.identity import user_key
from mcp_server.model_bundle import digest_resource_dirs
from mcp_server.resources import stage_model_resources
from mcp_server.util import (
    copy_regular_file_nofollow,
    create_run_dir,
    open_nofollow_for_write,
    read_file_bounded,
    read_tail_bounded,
    read_text_capped,
    reject_escaping_symlinks,
    resolve_run_dir,
    safe_name,
    sha256_regular_file_nofollow,
)

MAX_LOG_READ_BYTES = 4 * 1024 * 1024
MAX_STAGED_FILE_BYTES = 8 * 1024 * 1024 * 1024  # one OSW, seed or weather file staged into a run dir
MAX_ERR_READ_BYTES = 16 * 1024 * 1024
MAX_RECORD_BYTES = 64 * 1024  # run_record.json is small; anything bigger is hostile
MAX_OUT_OSW_BYTES = 16 * 1024 * 1024  # out.osw carries step results/messages and can be large
MAX_IDENTITY_FILE_BYTES = 1024 * 1024 * 1024  # a staged seed OSM or EPW, hashed for the run record
_SHA256_LEN = 64
_STATUSES = frozenset({"queued", "running", "success", "failed", "cancelled"})

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
    # What run_simulation simulated, hashed from its own staged snapshot before the
    # run was queued: the OSM, the effective EPW and the resource set (files/ before
    # the weather override). The OSAF seed preflight reuses a run only when all three
    # equal the seed's current identity; a record without them (an older run, or any
    # other run_osw caller) never matches. Never recomputed from the run dir, which
    # the tenant's sandboxed process writes.
    seed_sha256: str | None = None
    weather_sha256: str | None = None
    resources_sha256: str | None = None


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


def _read_json_nofollow(path: Path, max_bytes: int) -> dict[str, Any]:
    """A JSON object from a run dir, never through a symlink (ValueError if refused/invalid).

    Everything in a run dir is written by the tenant's sandboxed process, so a planted link
    must not redirect the read (the readers open with O_NOFOLLOW).
    """
    data = json.loads(read_file_bounded(path, max_bytes).decode("utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError(f"not a JSON object: {path}")
    return data


def _read_record_json(path: Path) -> dict[str, Any] | None:
    """run_record.json, or None when absent, refused (symlink/oversize) or invalid."""
    try:
        return _read_json_nofollow(path, MAX_RECORD_BYTES)
    except (ValueError, OSError):
        return None


def _inside(path: Path, root: Path) -> bool:
    """path resolves to somewhere strictly inside root (every symlink followed), so a planted
    parent-directory link cannot redirect a read whose leaf is a regular file."""
    try:
        return str(path.resolve()).startswith(str(root.resolve()) + os.sep)
    except OSError:
        return False


def _pid_is_runs_child(pid: int, run_dir: Path) -> bool | None:
    """Is `pid` this run's own subprocess? True / False / None (could not inspect).

    Every launch passes the staged OSW path, which lives inside run_dir, on the command
    line (also behind the sandbox exec shim), so the argv names the run dir. A tenant can
    only forge that on a process it already owns. /proc/<pid>/cmdline is world-readable;
    cwd is not for a privilege-dropped child (needs CAP_SYS_PTRACE, which Docker drops).
    """
    try:
        argv = psutil.Process(pid).cmdline()
    except psutil.Error:
        return None
    if not argv:
        return None  # zombie / kernel thread: nothing to judge by
    prefix = str(run_dir.resolve())
    return any(arg == prefix or arg.startswith(prefix + os.sep) for arg in argv)


def _coerce_number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_sha256(value: Any) -> str | None:
    """A 64-hex-digit string from a tenant-written record, else None (never matches)."""
    if isinstance(value, str) and len(value) == _SHA256_LEN and all(c in "0123456789abcdef" for c in value):
        return value
    return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and not isinstance(value, bool) else None
    except (TypeError, ValueError):
        return None


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
            "seed_sha256": rec.seed_sha256,
            "weather_sha256": rec.weather_sha256,
            "resources_sha256": rec.resources_sha256,
        }
        # Temp file + os.replace: a symlink planted at run_record.json is replaced, never
        # followed (write_text as root would have overwritten the link's target).
        fd, tmp_name = tempfile.mkstemp(prefix=".run_record-", dir=rec.run_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, indent=2))
            os.fchmod(fd, 0o644)  # on the open descriptor: the entry cannot be swapped under us
        Path(tmp_name).replace(_run_record_path(rec.run_dir))
    except Exception:
        # Best-effort persistence only
        return


def _load_run_record_from_disk(run_id: str) -> RunRecord | None:
    """Load run metadata from disk if present."""
    try:
        run_dir = resolve_run_dir(user_run_root(), run_id)
    except FileNotFoundError:
        return None

    data = _read_record_json(_run_record_path(run_dir))
    if data is None:
        return None
    try:
        # The record is tenant-writable, so every field is coerced and nothing in it may
        # redirect a read, a write or a signal: run_dir is whatever the user-scoped lookup
        # resolved (a forged one would receive this run's reads AND the record write-back);
        # osw_path must stay inside it; a pid is kept only when that process is this run's
        # own child (cancel_run kills it); run_id is the looked-up id.
        osw_path = Path(str(data.get("osw_path") or (run_dir / "workflow.osw")))
        if not _inside(osw_path, run_dir):
            osw_path = run_dir / "workflow.osw"
        pid = _coerce_int(data.get("pid"))
        if pid is not None:
            if not _pid_alive(pid):
                pid = None  # gone: classify from artifacts below
            elif _pid_is_runs_child(pid, run_dir) is False:
                pid = None  # someone else's live process: never poll or signal it
            # True, or None (alive but not inspectable): keep it so the run is still seen as
            # running; cancel_run only signals on True, retention only frees on False.
        status = data.get("status")
        if not isinstance(status, str) or status not in _STATUSES:
            status = "unknown"
        ended_at = _coerce_number(data.get("ended_at"))
        error = str(data["error"]) if data.get("error") is not None else None
        if status == "queued":
            # Every run this process queued is in _RUNS, so a queued record that had to be
            # read from disk was queued by a previous server process. The queue is
            # in-memory and nothing will ever dispatch it (issue #175): report it as
            # failed instead of leaving it "queued" forever.
            status = "failed"
            error = "server restarted before this run started; resubmit it"
            ended_at = ended_at or _now()
        epw = data.get("epw_path")
        return RunRecord(
            run_id=run_id,
            user_key=str(data.get("user_key") or user_key()),
            name=str(data.get("name") or run_id),
            status=status,
            created_at=_coerce_number(data.get("created_at")) or 0.0,
            started_at=_coerce_number(data.get("started_at")),
            ended_at=ended_at,
            pid=pid,
            run_dir=run_dir,
            osw_path=osw_path,
            epw_path=Path(str(epw)) if isinstance(epw, str) and epw else None,
            exit_code=_coerce_int(data.get("exit_code")),
            error=error,
            seed_sha256=_coerce_sha256(data.get("seed_sha256")),
            weather_sha256=_coerce_sha256(data.get("weather_sha256")),
            resources_sha256=_coerce_sha256(data.get("resources_sha256")),
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


def _tail_text(path: Path, tail_lines: int) -> str | None:
    """Last N lines of a log: "" when the file does not exist yet, None when it was refused.

    Logs are written by confined-but-untrusted code: a symlink or non-regular file is
    refused (None) rather than read, and never more than the tail window is loaded.
    """
    if not path.exists() and not path.is_symlink():
        return ""
    try:
        raw = read_tail_bounded(path, MAX_LOG_READ_BYTES)
    except (ValueError, OSError):
        return None
    data = raw.decode("utf-8", errors="replace").splitlines()
    return "\n".join(data[-tail_lines:])


def _copy_tree(src_dir: Path, dst_dir: Path) -> None:
    """Copy the contents of src_dir into dst_dir (created if missing), skipping 'run/' and
    'generated_files/' (OpenStudio outputs present in a repo asset dir).

    Both trees are walked by descriptor (#190): a link anywhere in the OSW's directory, or at
    a component of either path, fails the copy (OSError / ValueError) instead of being followed.
    """
    copy_tree_confined(src_dir, dst_dir, exclude_names={"run", "generated_files"})


def _stage_file(src: Path, dst: Path) -> str | None:
    """Copy one input file into the run dir by descriptor at both ends; an error string instead of raising."""
    try:
        copy_regular_file_nofollow(src, dst, MAX_STAGED_FILE_BYTES)
    except (OSError, ValueError) as e:
        return f"Could not stage {src.name}: {e}"
    return None


def _load_json(path: Path) -> dict[str, Any]:
    """Parse a JSON file and return its contents as a dict."""
    return json.loads(path.read_text(encoding="utf-8"))


def _dump_json(path: Path, obj: dict[str, Any]) -> None:
    """Write a dict to a JSON file with indentation."""
    path.write_text(json.dumps(obj, indent=2, sort_keys=False) + "\n", encoding="utf-8")


# Search dirs WorkflowJSON::findFile consults when the OSW declares no
# file_paths (relative to the OSW dir). Explicit file_paths are searched too —
# union rather than replacement, so the validator never rejects a workflow the
# CLI would run (issue #99: false rejection is the bug being fixed here).
_OSW_DEFAULT_FILE_DIRS = ("files", "weather", ".")


def _osw_file_paths(osw: dict) -> list:
    """The OSW's file_paths as a list.

    Caller-supplied JSON may put any type here — an int/bool would crash the
    starred unpack, and a string would be iterated char-by-char into junk
    search dirs. Non-lists are treated as absent.
    """
    fps = osw.get("file_paths")
    return fps if isinstance(fps, list) else []


def _resolve_osw_file(name: str, base: Path, osw: dict,
                      *, gated: bool = True) -> tuple[Path | None, Path | None]:
    """Resolve an OSW file reference the way the CLI's WorkflowJSON::findFile
    does: absolute as-is, else the WHOLE relative reference appended to the OSW
    dir, each file_paths entry (relative entries resolved against the OSW dir),
    and the default search dirs.

    When `gated`, candidates outside the caller's allowed roots are skipped:
    file_paths is caller-controlled OSW content and a hit is later staged into
    the run dir by the root server (run_osw) — ungated that is an arbitrary
    host-file read primitive (same class as issue #104's companion staging).
    Internal callers (run_simulation's private temp stage) pass gated=False.

    Returns (hit, denied_hit) — denied_hit is the first candidate that exists
    but failed the gate, kept for a precise error message.
    """
    n = Path(name)
    if n.is_absolute():
        candidates = [n]
    else:
        dirs = [base]
        for fp in (*_osw_file_paths(osw), *_OSW_DEFAULT_FILE_DIRS):
            fpp = Path(str(fp))  # entries may be non-strings in caller JSON
            dirs.append(fpp if fpp.is_absolute() else base / fpp)
        candidates = [d / name for d in dirs]
    denied: Path | None = None
    for c in candidates:
        if not c.exists():
            continue
        if gated and not is_path_allowed(c):
            if denied is None:
                denied = c.resolve()
            continue
        return c.resolve(), None
    return None, denied


def _osw_ref_issue(kind: str, name: str, denied: Path | None, osw: dict) -> str:
    """Error text for an unresolvable OSW file reference."""
    if denied is not None:
        return (f"{kind} '{name}' resolves to {denied}, which is outside the "
                "caller's allowed roots")
    searched = _osw_file_paths(osw)
    return f"{kind} '{name}' not found (searched OSW dir + file_paths {searched})"


def validate_osw(osw_path: str, epw_path: str | None = None,
                 *, _gated: bool = True) -> dict[str, Any]:
    """
    Best-effort validation:
      - JSON parses
      - file exists
      - seed_file resolves (OSW dir + file_paths search, like the CLI)
      - weather_file resolves (same search)

    `_gated=False` is the trusted internal path (run_simulation's server-built
    temp OSW lives outside the caller's roots); not exposed via the MCP tool.
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

    # Caller-supplied JSON: non-string refs would crash Path() below
    if seed is not None and not isinstance(seed, str):
        issues.append(f"seed_file must be a string, got {type(seed).__name__}")
        seed = None
    if weather is not None and not isinstance(weather, str):
        issues.append(f"weather_file must be a string, got {type(weather).__name__}")
        weather = None

    # If an EPW override is provided, it must exist. When present, the OSW's
    # `weather_file` reference becomes optional (we may still report it as an
    # informational issue, but it won't fail validation).
    epw_override: Path | None = None
    if epw_path:
        epw_override = Path(epw_path).resolve()
        if not epw_override.exists():
            return {"ok": False, "error": f"EPW not found: {epw_path}"}

    if seed:
        seed_hit, seed_denied = _resolve_osw_file(seed, base, osw, gated=_gated)
        if seed_hit is None:
            issues.append(_osw_ref_issue("seed_file", seed, seed_denied, osw))

    if weather:
        weather_hit, weather_denied = _resolve_osw_file(weather, base, osw, gated=_gated)
        if weather_hit is None:
            msg = _osw_ref_issue("weather_file", weather, weather_denied, osw)
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
    sandbox.prepare_workdir(rec.run_dir, key=rec.user_key)
    # The run owner's python_packages dir (if any) is granted read-only so
    # EnergyPlus Python plugins can import pip-installed packages from it
    # (wired into the model via PythonPlugin:SearchPaths).
    try:
        pkgs_dir = pkgs_root_for(rec.user_key)
        extra_ro = (str(pkgs_dir),) if pkgs_dir.is_dir() else ()
    except (RuntimeError, InvalidUserKeyError):  # symlinked pkgs dir or tenant root — no grant
        extra_ro = ()
    proc = subprocess.Popen(  # noqa: S603 - cmd built from trusted config + staged OSW path
        sandbox.wrap_cmd(
            _build_run_cmd(rec.osw_path), rec.run_dir, extra_ro=extra_ro, key=rec.user_key,
        ),
        cwd=str(rec.run_dir),
        stdout=open_nofollow_for_write(log),
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
            # Never signal a pid we cannot prove is this run's own child (pid reuse, or a
            # reloaded record whose process could not be inspected).
            and _pid_is_runs_child(rec.pid, rec.run_dir) is True
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
            *, _internal: bool = False,
            _identity: dict[str, str | None] | None = None) -> dict[str, Any]:
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
    `_identity` (run_simulation only) carries the seed and resources hashes of that
    staged snapshot; the weather hash is taken here from the staged EPW copy, and the
    three are written into the run record (see RunRecord).
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
    v = validate_osw(str(src_osw), epw_path=epw_path, _gated=not _internal)
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

    # Stage OSW directory contents. src_osw was resolved once, before the checks above; it is
    # not resolved again here (a resolve after the check would follow a link swapped in since
    # and hand the descriptor walk another tree's real path, which has no link to refuse).
    src_dir = src_osw.parent
    try:
        _copy_tree(src_dir, run_dir)
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"Could not stage the OSW directory {src_dir}: {e}", "run_dir": str(run_dir)}

    staged_osw = run_dir / src_osw.name
    if not staged_osw.exists():
        # In case OSW lived outside src_dir copy (unlikely), copy explicitly
        err = _stage_file(src_osw, staged_osw)
        if err:
            return {"ok": False, "error": err, "run_dir": str(run_dir)}

    # Load staged OSW and ensure referenced seed file is present.
    # Always stage the seed directly into run_dir (flatten any ../ refs)
    # and rewrite the OSW pointer so OpenStudio finds it.
    osw = _load_json(staged_osw)
    seed_rel = osw.get("seed_file")
    seed_resource_src: Path | None = None  # the seed as found, for its companion resources
    if seed_rel:
        # Lexical join (".." collapsed, no link followed): the walk opens exactly this path
        seed_src = Path(os.path.normpath(src_dir / seed_rel))
        if seed_src.exists():
            seed_resource_src = seed_src
            # Flatten: use just the filename, always inside run_dir
            seed_dst = run_dir / Path(seed_rel).name
            if not seed_dst.exists():
                err = _stage_file(seed_src, seed_dst)
                if err:
                    return {"ok": False, "error": err, "run_dir": str(run_dir)}
            # Rewrite OSW to point at the flattened location
            if seed_rel != Path(seed_rel).name:
                osw["seed_file"] = Path(seed_rel).name
                _dump_json(staged_osw, osw)
        else:
            # Not next to the OSW: resolve via the OSW file_paths search like
            # the CLI does (issue #99), then stage into the run dir — the
            # sandboxed CLI child can only read its own run dir, so leaving
            # the external reference in place would fail under Landlock
            # (issue #104 class). Absolute rewrite sidesteps search-path
            # semantics in the staged workflow.
            found, _denied = _resolve_osw_file(seed_rel, src_dir, osw,
                                               gated=not _internal)
            if found is not None:
                seed_resource_src = found
                seed_dst = run_dir / found.name
                if not seed_dst.exists():
                    err = _stage_file(found, seed_dst)
                    if err:
                        return {"ok": False, "error": err, "run_dir": str(run_dir)}
                osw["seed_file"] = str(seed_dst)
                _dump_json(staged_osw, osw)

    # Stage a weather_file the sandboxed child couldn't read in place: refs
    # resolving OUTSIDE the OSW dir (absolute path or ../ escape — _copy_tree
    # mirrors only the OSW dir itself) plus refs that only resolve via the
    # file_paths search. Staged copy gets an absolute rewrite. (PR #107
    # review: the absolute-ref case validated but was never staged.) Skipped
    # when an EPW override is present — the override staging below wins.
    weather_rel = osw.get("weather_file")
    if weather_rel and isinstance(weather_rel, str) and not epw_src:
        found: Path | None = None
        w_direct = (src_dir / weather_rel).resolve()
        if w_direct.exists():
            inside_src = w_direct == src_dir or \
                str(w_direct).startswith(str(src_dir) + os.sep)
            if not inside_src and (_internal or is_path_allowed(w_direct)):
                found = w_direct
            elif inside_src and Path(weather_rel).is_absolute():
                # Usually mirrored by _copy_tree already: point the staged OSW
                # at the mirror instead of the original absolute path, which
                # the sandboxed child may not be able to read. A file under a
                # dir the mirror skips (run/, generated_files/) is staged into
                # files/ instead.
                mirrored = run_dir / w_direct.relative_to(src_dir)
                if not mirrored.is_file() or mirrored.is_symlink():
                    files_dir = run_dir / "files"
                    files_dir.mkdir(parents=True, exist_ok=True)
                    mirrored = files_dir / w_direct.name
                    if mirrored.is_symlink() or mirrored.is_dir():
                        return {"ok": False,
                                "error": f"{mirrored} is a link or directory; refusing to stage weather there"}
                    err = _stage_file(w_direct, mirrored)
                    if err:
                        return {"ok": False, "error": err, "run_dir": str(run_dir)}
                osw["weather_file"] = str(mirrored)
                _dump_json(staged_osw, osw)
        else:
            found, _denied = _resolve_osw_file(weather_rel, src_dir, osw,
                                               gated=not _internal)
        if found is not None:
            files_dir = run_dir / "files"
            files_dir.mkdir(parents=True, exist_ok=True)
            weather_dst = files_dir / found.name
            # The OSW's explicit choice replaces a same-named file the OSW-dir
            # mirror brought along (an OSW inside a model's companion folder
            # mirrors that model's files/); a link there is never written
            # through.
            if weather_dst.is_symlink() or weather_dst.is_dir():
                return {"ok": False, "error": f"{weather_dst} is a link or directory; refusing to stage weather there"}
            err = _stage_file(found, weather_dst)
            if err:
                return {"ok": False, "error": err, "run_dir": str(run_dir)}
            osw["weather_file"] = str(weather_dst)
            _dump_json(staged_osw, osw)

    # If an EPW is provided, stage it into files/ and rewrite weather_file to match
    staged_epw: Path | None = None
    if epw_src:
        files_dir = run_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        staged_epw = files_dir / epw_src.name
        err = _stage_file(epw_src, staged_epw)
        if err:
            return {"ok": False, "error": err, "run_dir": str(run_dir)}
        osw["weather_file"] = f"files/{epw_src.name}"
        _dump_json(staged_osw, osw)
        if _identity is not None:
            try:
                _identity["weather_sha256"] = sha256_regular_file_nofollow(staged_epw, MAX_IDENTITY_FILE_BYTES)
            except (OSError, ValueError) as e:
                return {"ok": False, "error": f"Could not hash the staged weather file: {e}"}

    # The seed's own resources (its companion folder <seed>/files/, or an older
    # sibling files/) travel into the run's files/ behind everything the OSW
    # dir and the weather staging above provided: an explicit OSW weather_file
    # or epw_path keeps its copy, the companion never overwrites. The CLI's
    # default search paths look beside the OSW, not in the seed's companion
    # folder. run_simulation stages them itself (_internal) from a temp dir
    # outside the allowed roots.
    if seed_resource_src is not None and not _internal:
        stage_err = stage_model_resources(seed_resource_src, run_dir / "files")
        if stage_err:
            return {"ok": False, "error": stage_err}

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
        seed_sha256=_identity.get("seed_sha256") if _identity else None,
        weather_sha256=_identity.get("weather_sha256") if _identity else None,
        resources_sha256=_identity.get("resources_sha256") if _identity else None,
    )
    with _sim_lock:
        _RUNS[run_id] = rec
        # On disk from the moment it is queued: without this a run that was still queued
        # when the server died was "Unknown run_id" after the restart (issue #175).
        _persist_run_record(rec)
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
    if rec.pid is None and rec.status != "running":
        return rec  # queued/unknown: nothing has produced artifacts yet
    # A running record with no trusted pid (reloaded after a restart) is classified
    # from its artifacts below, exactly like a process that has already exited.

    if rec.pid is not None:
        try:
            p = psutil.Process(rec.pid)
            if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                return rec
        except psutil.NoSuchProcess:
            pass

    # Process ended; determine exit code from psutil if possible
    exit_code: int | None = rec.exit_code
    if rec.pid is not None:
        try:
            exit_code = psutil.Process(rec.pid).wait(timeout=0)
        except Exception:
            # Could be gone already; we'll infer failure unless out.osw says success
            exit_code = rec.exit_code

    # Look for out.osw to determine success/failure more accurately
    out_osw = rec.run_dir / "out.osw"
    status = "failed"
    err: str | None = None
    if out_osw.exists():
        try:
            out = _read_json_nofollow(out_osw, MAX_OUT_OSW_BYTES)
            status = "success" if out.get("completed_status") == "Success" else "failed"
        except (ValueError, OSError) as e:
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
        if err_path.exists() and _inside(err_path, rec.run_dir):
            try:
                from mcp_server.skills.results.err_parser import parse_err_file
                # Oversize err files (warning floods) are parsed from the head and flagged,
                # rather than silently losing the summary; a symlink is refused (no summary).
                text, truncated = read_text_capped(err_path, MAX_ERR_READ_BYTES)
                parsed = parse_err_file(text)
                run_dict["error_summary"] = {
                    "fatal_count": len(parsed["fatal"]),
                    "severe_count": len(parsed["severe"]),
                    "warning_count": parsed["warning_count"],
                    "first_fatal": parsed["fatal"][0] if parsed["fatal"] else None,
                    "first_severe": parsed["severe"][0] if parsed["severe"] else None,
                    "summary": parsed["summary"],
                    "truncated": truncated,
                }
            except (ValueError, OSError):
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

    text = _tail_text(path, tail_lines) if _inside(path, rec.run_dir) else None
    if text is None:
        return {
            "ok": False,
            "run_id": run_id,
            "stream": stream,
            "path": str(path),
            "error": f"log file is a symlink or not a regular file (refused): {path.name}",
        }
    return {
        "ok": True,
        "run_id": run_id,
        "stream": stream,
        "path": str(path),
        "tail": tail_lines,
        "text": text,
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
        if p.is_symlink() or not p.exists():  # a planted link would enumerate outside the run
            continue
        if p.is_dir():
            # shallow listing
            children = []
            for c in sorted(p.iterdir()):
                if c.is_symlink():
                    continue
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

    if rec.status in _TERMINAL:  # before the pid branch: reloaded terminal records carry no pid
        return {"ok": True, "run_id": run_id, "cancelled": False, "status": rec.status}
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
    if _pid_is_runs_child(pid, rec.run_dir) is not True:
        # pid reuse, or a record field we could not verify: never signal a stranger as root
        return {"ok": False, "run_id": run_id, "error": f"pid {pid} is not this run's process; not signalled"}
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
    else:
        # No override: resolve the model's own OS:WeatherFile url so run_osw
        # stages it into the run's files/ dir. A bare-filename url (the
        # portable form change_building_location writes — issue #104) is
        # unresolvable by the CLI alone, and a container-absolute /inputs url
        # is unreadable by the sandboxed sim child; staging fixes both.
        from mcp_server.skills.weather.operations import resolve_model_weather_epw
        resolved = resolve_model_weather_epw(osm)
        if resolved["epw"] is not None:
            epw_abs = str(resolved["epw"])
        elif resolved["loadable"] and resolved["run_periods_requested"]:
            # An annual (weather-file run period) sim with no resolvable EPW
            # dies in EnergyPlus within ~1s — fail fast with guidance instead
            # of launching a run the caller must poll to see fail. Design-day-
            # only models (run_periods_requested False) legitimately run
            # without an EPW and are not blocked. An unloadable OSM defers to
            # the CLI for its authoritative load error.
            if resolved["declared"]:
                return {"ok": False, "error": (
                    f"Model's weather file '{resolved['url']}' was not found. "
                    "Pass epw_path, or re-run change_building_location with a "
                    "valid EPW.")}
            return {"ok": False, "error": (
                "Model has no weather file — an annual simulation would fail "
                "immediately. Set weather with change_building_location or "
                "pass epw_path.")}

    # The file on disk is what gets simulated. Say so when the session model
    # loaded from (or saved to) this path has edits the file lacks (issue #177):
    # the agent otherwise believes it simulated its edits.
    from mcp_server.model_manager import unsaved_edits_for
    unsaved_warning: str | None = None
    if unsaved_edits_for(osm):
        unsaved_warning = (
            f"The session model loaded from {osm} has edits that are not saved. "
            "This simulation uses the file on disk, without those edits. "
            "Call save_osm_model first to simulate the edits."
        )

    # Stage the minimal OSW in a throwaway temp dir. run_osw() copies the staged
    # files into the real per-user run dir before it returns, so nothing here
    # needs to persist — this avoids leaving an orphan sim_* dir under /runs.
    with tempfile.TemporaryDirectory(prefix="osw_stage_") as tmp:
        stage = Path(tmp)
        staged_osm = stage / osm.name
        shutil.copy2(str(osm), str(staged_osm))

        # Stage the model's resources (its companion folder <model>/files/, or
        # this server's older sibling files/). Workflow-time forward
        # translation resolves an OSM's relative OS:External:File name via the
        # OSW search paths (osw dir, then files/), so they must travel with
        # the seed.
        stage_err = stage_model_resources(osm, stage / "files")
        if stage_err:
            return {"ok": False, "error": stage_err}

        # The run's identity for the OSAF seed preflight cache, hashed from
        # this staged snapshot (not the source files, which may change
        # between the copy and the hash) before anything is queued. The
        # staged files/ is exactly the model's effective resource set, so its
        # digest equals resources_digest(osm) computed by the preflight.
        try:
            identity: dict[str, str | None] = {
                "seed_sha256": sha256_regular_file_nofollow(staged_osm, MAX_IDENTITY_FILE_BYTES),
                "weather_sha256": None,
                "resources_sha256": digest_resource_dirs([stage / "files"])["sha256"],
            }
        except (OSError, ValueError) as e:
            return {"ok": False, "error": f"Could not hash the staged model: {e}"}

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
        result = run_osw(
            osw_path=str(osw_path_out),
            epw_path=epw_abs,
            name=name or osm.stem,
            _internal=True,
            _identity=identity,
        )
    if unsaved_warning and result.get("ok"):
        result.setdefault("warnings", []).append(unsaved_warning)
        result["user_message"] = unsaved_warning
    return result
