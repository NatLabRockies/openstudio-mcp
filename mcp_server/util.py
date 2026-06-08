from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path


def safe_read_text(path: Path, max_bytes: int = 200_000) -> str:
    data = safe_read_bytes(path, max_bytes=max_bytes)
    return data.decode("utf-8", errors="replace")

def copy_into(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def dump_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")

def safe_name(s: str) -> str:
    """Sanitize a string for use as a filesystem-safe name."""
    s = str(s)
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in s).strip("_") or "run"

def create_run_dir(run_root: Path, prefix: str, name: str | None = None) -> tuple[str, Path]:
    """Create a readable, unique run directory and return (run_id, path)."""
    label = safe_name(name or prefix)
    if label == "run" and prefix:
        label = safe_name(prefix)
    elif prefix and not label.startswith(f"{prefix}_"):
        label = f"{safe_name(prefix)}_{label}"

    for _ in range(10):
        run_id = f"{label}_{uuid.uuid4().hex[:12]}"
        run_dir = (run_root / run_id).resolve()
        if run_dir.parent != run_root.resolve():
            raise FileNotFoundError(f"Invalid run directory: {run_id}")
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            return run_id, run_dir
        except FileExistsError:
            continue
    raise FileExistsError(f"Could not create unique run directory under {run_root}")

def resolve_run_dir(run_root: Path, run_id: str) -> Path:
    """Resolve / validate a run directory on disk.

    Treats the filesystem as the source of truth (works across server restarts).
    """
    run_dir = (run_root / run_id).resolve()
    if run_dir.parent != run_root.resolve():
        # Basic guard against path traversal / weird run_id values
        raise FileNotFoundError(f"Unknown run_id: {run_id}")
    if not run_dir.exists() or not run_dir.is_dir():
        raise FileNotFoundError(f"Unknown run_id: {run_id}")
    return run_dir


def safe_read_bytes(path: Path, max_bytes: int = 2_000_000) -> bytes:
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data
