"""Finding and opening the result files a tenant's run wrote (eplusout.sql, eplustbl.htm).

``sqlite3.connect`` opens the database by pathname, and SQLite's Unix VFS
canonicalizes that name itself before its ``open()``, so no check the server
makes beforehand binds what SQLite reads: a ``run/`` component replaced by a
symlink in between hands it another tenant's database (issue #190). Pointing
SQLite at ``/proc/self/fd/<n>`` does not help (the VFS resolves the link back
to a pathname), and closing a spare descriptor on an inode SQLite has locked
drops the process's POSIX locks on it.

So SQLite never opens the tenant's file. The file is opened once through the
descriptor walk (``confined_fs.open_confined``: every component under the
tenant root opened no-follow relative to its parent) and copied from that
descriptor into a private temporary file in the server's temp dir (a
confinement root, tenant-immutable); SQLite opens the copy read-only and the
copy is unlinked at once, so it lives exactly as long as the connection and
is shared with nothing. No cache, so no state to lock, reclaim or invalidate:
the price is one copy per extraction call (tens of milliseconds to a second
for the usual tens to hundreds of megabytes; an 8 GiB budget bounds a runaway
file). Paths under no confinement root (test fixtures, shared read-only roots)
are opened by pathname, read-only, as before; so are all paths on platforms
without the descriptor walk.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

from mcp_server import confined_fs
from mcp_server.confined_fs import DirHandle
from mcp_server.util import copy_fd_bounded

# eplusout.sql of a timeseries run reaches gigabytes; this bounds a runaway copy, not a normal one.
MAX_RESULT_SQL_BYTES = 8 * 1024 * 1024 * 1024
_COPY_PREFIX = "osmcp-results-"


def connect_sql_readonly(path: Path) -> sqlite3.Connection:
    """Read-only connection to the SQLite result file at ``path``.

    Under a tenant tree the connection is to a private copy made from the
    descriptor-walked source (see module docstring); elsewhere to the file
    itself. Raises OSError / ValueError from the walk or the copy (a link at
    any component, not a regular file, over the size budget) and
    ``sqlite3.Error`` from SQLite. ``mode=ro`` never creates sidecar files.
    """
    p = Path(path)
    if not confined_fs.supported() or confined_fs.confinement_root_for(p) is None:
        return sqlite3.connect(f"{p.absolute().as_uri()}?mode=ro", uri=True)
    return _connect_private_copy(p)


def _connect_private_copy(src: Path) -> sqlite3.Connection:
    # One walk to the file's directory: the -wal check and the file open use the same held
    # descriptor, so they see the same directory whatever the path resolves to afterwards.
    with confined_fs.DirHandle.open(src.parent) as parent:
        # A WAL-mode database keeps committed pages in <name>-wal until a checkpoint; a copy of
        # the main file alone would silently read stale data. EnergyPlus writes journal_mode=OFF,
        # so this only concerns files produced or post-processed by other tools.
        wal = parent.lstat(f"{src.name}-wal")
        if wal is not None and wal.st_size > 0:
            raise ValueError(
                f"{src.name}: has uncheckpointed WAL data ({wal.st_size} bytes in {src.name}-wal); "
                "close or checkpoint the writer first",
            )
        fd = parent.open_file(src.name, os.O_RDONLY)
    try:
        size = os.fstat(fd).st_size
        if size > MAX_RESULT_SQL_BYTES:
            raise ValueError(f"{src.name}: {size} bytes exceeds the {MAX_RESULT_SQL_BYTES}-byte limit")
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=_COPY_PREFIX, suffix=".sql")
        tmp = Path(tmp_name)
        try:
            copy_fd_bounded(fd, tmp_fd, MAX_RESULT_SQL_BYTES, src.name)  # closes tmp_fd
            # immutable: the copy is private and final, so SQLite needs no locks and no
            # journal / WAL / shm lookups beside a name that is about to disappear (a
            # checkpointed WAL source would otherwise fail its first read after the unlink).
            conn = sqlite3.connect(f"{tmp.as_uri()}?mode=ro&immutable=1", uri=True)
        finally:
            # SQLite holds its own descriptor from the open above; the name can go. On a
            # failure the file goes too.
            tmp.unlink(missing_ok=True)
        return conn
    finally:
        os.close(fd)


def connection_for(source: Path | sqlite3.Connection) -> tuple[sqlite3.Connection, bool]:
    """An open connection for an extractor and whether the extractor owns (must close) it.

    A Path is opened through connect_sql_readonly (one private copy); an
    already open connection is reused, so a request that runs several
    extractors over one result file copies it once.
    """
    if isinstance(source, sqlite3.Connection):
        return source, False
    return connect_sql_readonly(source), True


_RESULT_FILE_NAMES = ("eplusout.sql", "eplustbl.htm", "eplustbl.html")
_RESULT_SEARCH_DEPTH = 4


def _find_first_existing(run_dir: Path, rel_candidates: list[str]) -> Path | None:
    """First result file from the candidates: a regular file inside run_dir, never a symlink.

    Result files are written by the tenant's sandboxed run. The candidate check
    here is a first filter; what is finally read is decided when the file is
    opened by descriptor (connect_sql_readonly, the bounded HTML reader), so a
    component swapped for a link after this check fails there. The fallback
    search walks the run dir by directory descriptor and never descends a link.
    """
    root = run_dir.resolve()

    def _regular_inside(p: Path) -> bool:
        return not p.is_symlink() and p.is_file() and str(p.resolve()).startswith(str(root) + os.sep)

    for rel in rel_candidates:
        p = run_dir / rel
        if _regular_inside(p):
            return p
    # fallback: search a little, by descriptor
    found: dict[str, Path] = {}
    try:
        with DirHandle.open(run_dir) as top:
            _search_result_files(top, run_dir, found, depth=0)
    except (OSError, ValueError):
        return None
    for name in _RESULT_FILE_NAMES:
        if name in found:
            return found[name]
    return None


def _search_result_files(handle: DirHandle, here: Path, found: dict[str, Path], *, depth: int) -> None:
    """Shallow sorted walk through held directory descriptors; records the first path per result name."""
    try:
        with handle.scandir() as it:
            entries = sorted(it, key=lambda e: e.name)
    except OSError:
        return
    for entry in entries:
        if entry.is_symlink():
            continue
        if entry.is_file(follow_symlinks=False):
            if entry.name in _RESULT_FILE_NAMES and entry.name not in found:
                found[entry.name] = here / entry.name
        elif entry.is_dir(follow_symlinks=False) and depth < _RESULT_SEARCH_DEPTH:
            try:
                child = handle.subdir(entry.name)
            except OSError:
                continue
            try:
                _search_result_files(child, here / entry.name, found, depth=depth + 1)
            finally:
                child.close()
