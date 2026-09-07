"""Session-scoped memory of the gbXML file a model was imported from.

Stored in model_manager's generic per-session `extra` dict (see
mcp_server.model_manager.get_session_extra), the same mechanism the space-type
wizard uses (see space_type_assignment/wizard_state.py) — so this is dropped
automatically with its model's TTL/LRU eviction rather than leaking across
sessions or models.

import_gbxml_op() never keeps a handle to the source .xml after translation:
the OSM it produces has no back-reference to the file it came from. Anything
that later wants to re-read the source (e.g. cross-checking Revit's own
Area/Volume values against the post-repair model — see
mcp_server.skills.geometry.gbxml_deltas) needs this stashed separately, keyed
to the model generation so a reload/replace invalidates it rather than
silently comparing against the wrong model.

The path stashed is the staged copy under the import's run_dir/gbxmls/ — the
bytes the translator actually consumed — not the caller's input path, which
an uploader is free to delete or overwrite after the import returns.

Sync tools on one session run concurrently (FastMCP dispatches them via
anyio.to_thread), so the generation is always passed in explicitly by a
caller that obtained it atomically with the model (see
model_manager.load_model_with_generation / get_model_with_generation), never
re-read from model_manager here: a second read could observe a load that
landed in between and bind this path to the wrong model.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from mcp_server import model_manager

_KEY = "gbxml_import"
# Serializes the compare-and-set in set_source(): get_session_extra() hands back the
# dict outside model_manager's lock, so without this two concurrent imports could both
# read the old entry and the older one could write last.
_write_lock = threading.Lock()


@dataclass
class GbxmlSourceState:
    gbxml_path: str
    model_generation: int


def set_source(gbxml_path: str, model_generation: int) -> None:
    """Record the gbXML file that produced the model with generation `model_generation`.

    `model_generation` must be the value returned by the load_model_with_generation()
    call that loaded that model. A concurrent later import on this session may already
    have stashed a newer generation — never overwrite it with an older one.
    """
    extra = model_manager.get_session_extra()
    with _write_lock:
        existing = extra.get(_KEY)
        if existing is not None and existing.model_generation > model_generation:
            return
        extra[_KEY] = GbxmlSourceState(gbxml_path=gbxml_path, model_generation=model_generation)


def get_source_for_model(model_generation: int) -> str | None:
    """Return the gbXML path the model with generation `model_generation` was imported from.

    `model_generation` is the value the caller captured together with the model it
    holds (model_manager.get_model_with_generation), so the answer describes *that*
    model even if the session has loaded another one since.

    None if that model was never produced by import_gbxml_op (e.g. loaded directly
    with load_osm_model), or the stash belongs to a different generation — a stale
    stash would silently compare the wrong two files.
    """
    state = model_manager.get_session_extra().get(_KEY)
    if state is None or state.model_generation != model_generation:
        return None
    return state.gbxml_path
