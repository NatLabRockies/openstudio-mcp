"""Moving the session workspace's generated files into a saved model's files/ dir.

A measure run leaves its generated files in the session's pending workspace
under the tenant's run root (#197); ``save_osm_model`` moves them into the
model's companion ``files/``. Both directories are tenant-writable, so the
move walks each tree by directory descriptor (``confined_fs``, issue #190):
regular files only, no link followed at any component, an existing regular
file in ``files/`` replaced (the generated file is the model's newest truth,
which is what the Application's copy-back does), a link or directory at the
destination name never written through.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

from mcp_server.confined_fs import DirHandle
from mcp_server.util import copy_fd_bounded

# Matches the measure-output budget in measures/operations.py.
MAX_PERSISTED_FILE_BYTES = 64 * 1024 * 1024


def persist_pending_files(pending: Path, dst_files: Path) -> tuple[list[str], list[str], list[str]]:
    """Move the workspace's regular files into ``dst_files``; returns (persisted, replaced, skipped).

    ``dst_files`` is created, with its parents under the confinement root,
    only when there is a file to move. A file that cannot be copied (a link
    or directory at its destination name, over the budget, unreadable) is
    skipped and reported. A link or non-directory above ``dst_files`` fails
    the whole move with OSError: nothing may be written through it.
    """
    persisted: list[str] = []
    replaced: list[str] = []
    skipped: list[str] = []
    with DirHandle.open(pending) as src:
        with src.scandir() as it:
            names = sorted(e.name for e in it if not e.is_symlink() and e.is_file(follow_symlinks=False))
        if not names:
            return persisted, replaced, skipped
        with DirHandle.open(dst_files, create=True) as dst:
            for name in names:
                existing = dst.lstat(name)
                if existing is not None and not stat.S_ISREG(existing.st_mode):
                    skipped.append(name)
                    continue
                try:
                    src_fd = src.open_file(name, os.O_RDONLY)
                except (OSError, ValueError):
                    skipped.append(name)
                    continue
                try:
                    if os.fstat(src_fd).st_size > MAX_PERSISTED_FILE_BYTES:
                        skipped.append(name)
                        continue
                    try:
                        dst_fd, existed = dst.create_file(name, overwrite=True)
                    except (OSError, ValueError):
                        skipped.append(name)
                        continue
                    try:
                        copy_fd_bounded(src_fd, dst_fd, MAX_PERSISTED_FILE_BYTES, name)
                    except (OSError, ValueError):
                        skipped.append(name)
                        continue
                finally:
                    os.close(src_fd)
                src.unlink(name)
                persisted.append(name)
                if existed:
                    replaced.append(name)
    return persisted, replaced, skipped
