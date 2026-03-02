# mcp_server/tools/workflow_tools.py
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import psutil

from mcp_server.config import LOG_TAIL_DEFAULT, RUN_ROOT
from mcp_server.util import resolve_run_dir

# Where the MCP server stores runs inside the container
DEFAULT_LOG_TAIL = LOG_TAIL_DEFAULT

LogStream = Literal["openstudio", "energyplus"]


@dataclass
class RunRecord:
    run_id: str
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


def _run_record_path(run_dir: Path) -> Path:
    """Return path to the JSON metadata file for a run."""
    return run_dir / "run_record.json"


def _persist_run_record(rec: RunRecord) -> None:
    """Persist minimal run metadata for restart-safe lookup."""
    try:
        rec.run_dir.mkdir(parents=True, exist_ok=True)
        data = {
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
        _run_record_path(rec.run_dir).write_text(json.dumps(data, indent=2))
    except Exception:
        # Best-effort persistence only
        return


def _load_run_record_from_disk(run_id: str) -> RunRecord | None:
    """Load run metadata from disk if present."""
    try:
        run_dir = resolve_run_dir(RUN_ROOT, run_id)
    except FileNotFoundError:
        return None

    meta_path = _run_record_path(run_dir)
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text())
        return RunRecord(
            run_id=data["run_id"],
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
    """Look up a run record by ID, checking memory first then disk."""
    rec = _RUNS.get(run_id)
    if rec:
        return rec
    rec = _load_run_record_from_disk(run_id)
    if rec:
        _RUNS[run_id] = rec
    return rec



def _now() -> float:
    """Current epoch timestamp."""
    return time.time()


def _safe_name(s: str) -> str:
    """Sanitize a string for use as a filesystem-safe run name."""
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in s).strip("_") or "run"


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


def run_osw(osw_path: str, epw_path: str | None = None, name: str | None = None) -> dict[str, Any]:
    """
    Stage the OSW + referenced files into /runs/<run_id>/ and execute:
      openstudio run -w <staged_osw>

    Notes on validation:
      - We always validate the OSW JSON and its seed_file reference (if any).
      - If no EPW override is provided, we also require the OSW's weather_file (if set) to exist.
      - If an EPW override is provided, we allow a missing OSW weather_file because it will be replaced.
    """
    src_osw = Path(osw_path).resolve()
    if not src_osw.exists():
        return {"ok": False, "error": f"OSW not found: {osw_path}"}

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

    # Create run directory
    run_id = uuid.uuid4().hex
    run_dir = (RUN_ROOT / run_id).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

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

    # Determine run display name
    run_name = _safe_name(name or osw.get("name") or src_osw.stem)

    # Create log files
    openstudio_log = run_dir / "openstudio.log"

    # Kick off openstudio run
    # Note: use Popen so it can run async.
    cmd = ["openstudio", "run", "-w", str(staged_osw)]
    proc = subprocess.Popen(
        cmd,
        cwd=str(run_dir),
        stdout=open(openstudio_log, "w", encoding="utf-8"),
        stderr=open(openstudio_log, "a", encoding="utf-8"),
        env=os.environ.copy(),
    )

    rec = RunRecord(
        run_id=run_id,
        name=run_name,
        status="running",
        created_at=_now(),
        started_at=_now(),
        ended_at=None,
        pid=proc.pid,
        run_dir=run_dir,
        osw_path=staged_osw,
        epw_path=staged_epw,
        exit_code=None,
        error=None,
    )
    _RUNS[run_id] = rec

    # Return immediately
    return {
        "ok": True,
        "run_id": run_id,
        "name": run_name,
        "run_dir": str(run_dir),
        "osw_path": str(staged_osw),
        "epw_path": str(staged_epw) if staged_epw else None,
        "command": cmd,
    }


def _refresh_status(rec: RunRecord) -> RunRecord:
    """Check if the OS process has ended and update run status accordingly."""
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
            if out.get("completed_status") == "Success":
                status = "success"
            else:
                status = "failed"
        except Exception as e:
            err = f"Failed to parse out.osw: {e}"

    # If we couldn't parse out.osw and exit_code is known non-zero, keep failed.
    if status != "success" and rec.status != "cancelled":
        status = "failed"

    rec.status = status  # type: ignore[assignment]
    rec.ended_at = rec.ended_at or _now()
    rec.exit_code = exit_code if exit_code is not None else rec.exit_code
    rec.error = err or rec.error
    return rec


def get_run_status(run_id: str) -> dict[str, Any]:
    rec = _get_run_record(run_id)
    if not rec:
        return {"ok": False, "error": f"Unknown run_id: {run_id}"}

    rec = _refresh_status(rec)
    _RUNS[run_id] = rec
    _persist_run_record(rec)

    return {
        "ok": True,
        "run": {
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
        },
    }


def get_run_logs(run_id: str, tail: int | None = None, stream: LogStream = "openstudio") -> dict[str, Any]:
    rec = _get_run_record(run_id)
    if not rec:
        return {"ok": False, "error": f"Unknown run_id: {run_id}"}

    tail_lines = int(tail or DEFAULT_LOG_TAIL)

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
    if not rec:
        return {"ok": False, "error": f"Unknown run_id: {run_id}"}

    run_dir = rec.run_dir
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

    if rec.pid is None:
        rec.status = "cancelled"
        rec.ended_at = rec.ended_at or _now()
        _RUNS[run_id] = rec
        return {"ok": True, "run_id": run_id, "cancelled": True}

    try:
        p = psutil.Process(rec.pid)
        p.terminate()
        try:
            p.wait(timeout=5)
        except psutil.TimeoutExpired:
            p.kill()
        rec.status = "cancelled"
        rec.ended_at = rec.ended_at or _now()
        _RUNS[run_id] = rec
        return {"ok": True, "run_id": run_id, "cancelled": True}
    except psutil.NoSuchProcess:
        rec = _refresh_status(rec)
        _RUNS[run_id] = rec
        return {"ok": True, "run_id": run_id, "cancelled": False, "status": rec.status}
    except Exception as e:
        return {"ok": False, "run_id": run_id, "error": str(e)}


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

    # Create a temporary OSW alongside the OSM
    run_id = uuid.uuid4().hex[:12]
    osw_dir = RUN_ROOT / f"sim_{run_id}"
    osw_dir.mkdir(parents=True, exist_ok=True)

    # Copy OSM into the run dir so OSW can reference it by relative path
    staged_osm = osw_dir / osm.name
    shutil.copy2(str(osm), str(staged_osm))

    # Build minimal OSW
    osw: dict[str, Any] = {
        "seed_file": osm.name,
        "file_paths": [],
        "measure_paths": [],
        "steps": [],
    }

    # Validate EPW path upfront if provided
    epw_abs: str | None = None
    if epw_path:
        epw = Path(epw_path)
        if not epw.exists():
            return {"ok": False, "error": f"EPW file not found: {epw_path}"}
        epw_abs = str(epw.resolve())

    osw_path_out = osw_dir / "workflow.osw"
    osw_path_out.write_text(json.dumps(osw, indent=2), encoding="utf-8")

    # Delegate to run_osw — pass epw_path so it handles staging into files/
    return run_osw(osw_path=str(osw_path_out), epw_path=epw_abs, name=name)