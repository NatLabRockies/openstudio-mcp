"""Saving an OpenStudio model into a tenant-writable tree (issue #190, the last pathname write).

``Model.save(path, overwrite)`` is an SDK call that opens its destination by
pathname and follows whatever is there, so a link planted at the destination
name (a finished sandboxed step can leave ``<run>/<name>.osm`` pointing at
another tenant's file) or a directory component swapped for a link after the
caller's check would be written through. The SDK cannot take a descriptor, so
the model is saved to a private temp file in the system temp dir (a
confinement root, server-owned) and copied from there to the destination with
``copy_regular_file_nofollow``: every component of the destination is opened
relative to its parent's descriptor, a link or directory at the destination
name is refused, an existing regular file is truncated only after the staged
size passed the budget, and missing parents are created from the root.

Cost: every save writes the model twice (temp, then copy), and the temp dir
needs room for one model.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from mcp_server.confined_fs import DirHandle
from mcp_server.util import copy_regular_file_nofollow

STAGING_PREFIX = "osmcp-save-"
MAX_SAVED_MODEL_BYTES = 1024 * 1024 * 1024  # matches model_bundle.MAX_BUNDLE_OSM_BYTES


def save_model_confined(model, dest: str | os.PathLike[str], *, max_bytes: int = MAX_SAVED_MODEL_BYTES) -> Path:
    """Save ``model`` (anything with ``save(path, overwrite) -> bool``) to ``dest`` through the descriptor walk.

    Returns the destination. Raises ``RuntimeError`` when the SDK refuses the
    write (``save`` returned False), ``OSError`` for a link at any component
    of the destination (or an unreadable or uncreatable path), ``ValueError``
    for a non-regular entry at the destination name, a ``..`` component or a
    model over ``max_bytes``. The staged file is always removed.
    """
    dest_path = Path(dest)
    fd, tmp_name = tempfile.mkstemp(prefix=STAGING_PREFIX, suffix=".osm")
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        if not model.save(str(tmp), True):
            raise RuntimeError(f"OpenStudio refused to write the model for {dest_path.name}")
        DirHandle.open(dest_path.parent, create=True).close()
        copy_regular_file_nofollow(tmp, dest_path, max_bytes)
    finally:
        tmp.unlink(missing_ok=True)
    return dest_path
