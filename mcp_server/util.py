from __future__ import annotations

import json
import os
import shutil
import stat
import uuid
from pathlib import Path


def reject_escaping_symlinks(root: Path) -> str | None:
    """Return an error string if the directory tree `root` contains a symlink
    whose target resolves OUTSIDE `root`; else None.

    Used before staging untrusted measure/OSW trees: a link to a host file
    (e.g. -> /etc/shadow) must not be copied or executed. Internal symlinks are
    allowed. Does not follow symlinked directories (no traversal / loops).
    """
    try:
        rroot = str(root.resolve())
    except OSError:
        return f"Cannot resolve path: {root}"
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in dirnames + filenames:
            p = Path(dirpath) / name
            if not p.is_symlink():
                continue
            try:
                target = str(p.resolve())
            except OSError:
                return f"Broken symlink in staged tree: {name}"
            if target != rroot and not target.startswith(rroot + os.sep):
                return f"Symlink escapes the allowed directory (not allowed): {name}"
    return None


def read_file_bounded(path: Path, max_bytes: int) -> bytes:
    """Read a regular file WITHOUT following a final-component symlink, capping
    the read at ``max_bytes``.

    Hardening for copying back files produced by confined-but-untrusted code
    (e.g. ``openstudio measure -u`` regenerating ``measure.xml`` in a staged
    dir):
      * O_NOFOLLOW (where available) closes the symlink-swap TOCTOU — a measure
        that replaces the output with a link to e.g. /etc/shadow cannot redirect
        the read to the link target.
      * the read stops at ``max_bytes + 1``, so an oversized output cannot be
        slurped wholesale into memory before being rejected.

    Raises ``ValueError`` on a symlink, a non-regular file (dir/fifo/device), an
    oversize file, or an unreadable path. On platforms without O_NOFOLLOW the
    symlink guard degrades to the caller's own is_symlink() check (the sandbox
    targets Linux).
    """
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    try:
        fd = os.open(path, flags)
    except OSError as e:
        # ELOOP => final component is a symlink (O_NOFOLLOW); surface clearly.
        raise ValueError(f"cannot read {path} (symlink or unreadable): {e}") from e
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError(f"not a regular file: {path}")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > max_bytes:
            raise ValueError(f"file exceeds {max_bytes} bytes: {path}")
        return data
    finally:
        os.close(fd)


def read_tail_bounded(path: Path, max_bytes: int) -> bytes:
    """Read the LAST ``max_bytes`` of a regular file WITHOUT following a
    final-component symlink.

    Same threat model as read_file_bounded (confined-but-untrusted subprocess
    output read back by the unconfined server), but for tail-style reads: a
    failure log can legitimately exceed any sane whole-file cap, so instead of
    rejecting oversize files this seeks to end-minus-max_bytes and returns only
    the tail — the whole file is never loaded into memory.

    Raises ``ValueError`` on a symlink, a non-regular file, or an unreadable
    path (same degradation notes as read_file_bounded on non-POSIX platforms).
    """
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    try:
        fd = os.open(path, flags)
    except OSError as e:
        raise ValueError(f"cannot read {path} (symlink or unreadable): {e}") from e
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"not a regular file: {path}")
        if st.st_size > max_bytes:
            os.lseek(fd, st.st_size - max_bytes, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = max_bytes
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


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
    # Tail-truncating by contract (callers read simulation-produced HTML whose
    # useful tables sit at the end); read_tail_bounded adds the no-follow +
    # never-slurp-the-whole-file hardening (PR #105).
    return read_tail_bounded(path, max_bytes)
