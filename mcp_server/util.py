from __future__ import annotations

import json
import shutil
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
