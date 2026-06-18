"""Guarded extraction of user-uploaded archives (e.g. measure .zip).

Untrusted zips reach the server: a malicious archive can path-traverse out of
the extract dir (`../../etc/cron.d/x`), smuggle a symlink to a host file, or
zip-bomb the disk. We extract entry-by-entry with explicit guards instead of
ZipFile.extractall, then run reject_escaping_symlinks as a backstop.
"""
from __future__ import annotations

import os
import stat
import zipfile
from pathlib import Path

from mcp_server.util import reject_escaping_symlinks

_CHUNK = 1 << 20  # 1 MiB


def guarded_extract(
    zip_path: Path, dest_dir: Path, *, max_uncompressed_bytes: int, max_entries: int,
) -> str | None:
    """Extract `zip_path` into `dest_dir`. Return an error string, or None on success.

    Guards: entry-count cap, no absolute / `..`-escaping member paths, no symlink
    members, and a REAL (streamed) uncompressed-size cap — the ZipInfo.file_size
    header is attacker-controlled, so we also count bytes as we read.
    """
    if not zipfile.is_zipfile(zip_path):
        return "not a valid zip archive"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_root = dest_dir.resolve()
    total = 0
    try:
        with zipfile.ZipFile(zip_path) as zf:
            infos = zf.infolist()
            if len(infos) > max_entries:
                return f"archive has too many entries ({len(infos)} > {max_entries})"
            for info in infos:
                name = info.filename
                if name.startswith("/") or Path(name).is_absolute() or ".." in Path(name).parts:
                    return f"archive entry escapes extract dir: {name!r}"
                # zip stores unix mode in the high 16 bits of external_attr.
                mode = (info.external_attr >> 16) & 0xFFFF
                if stat.S_ISLNK(mode):
                    return f"archive contains a symlink (not allowed): {name!r}"
                target = (dest_root / name).resolve()
                if target != dest_root and not str(target).startswith(str(dest_root) + os.sep):
                    return f"archive entry escapes extract dir: {name!r}"
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, target.open("wb") as dst:
                    while True:
                        chunk = src.read(_CHUNK)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_uncompressed_bytes:
                            return (f"archive expands beyond limit "
                                    f"({max_uncompressed_bytes} bytes) — possible zip bomb")
                        dst.write(chunk)
    except (zipfile.BadZipFile, OSError) as e:
        return f"failed to extract archive: {e}"
    # Backstop: nothing under the tree may be a symlink that escapes the root.
    return reject_escaping_symlinks(dest_root)
