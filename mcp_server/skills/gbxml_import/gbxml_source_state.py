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
"""
from __future__ import annotations

from dataclasses import dataclass

from mcp_server import model_manager

_KEY = "gbxml_import"


@dataclass
class GbxmlSourceState:
    gbxml_path: str
    model_generation: int


def set_source(gbxml_path: str) -> None:
    """Record the gbXML path used for the model just loaded into this session."""
    model_manager.get_session_extra()[_KEY] = GbxmlSourceState(
        gbxml_path=gbxml_path,
        model_generation=model_manager.model_generation(),
    )


def get_source_for_current_model() -> str | None:
    """Return the gbXML path the current session's model was imported from.

    None if the model was never imported via import_gbxml_op (e.g. loaded
    directly with load_osm_model), or if the model was reloaded/replaced since
    the import — a stale stash would silently compare the wrong two files.
    """
    state = model_manager.get_session_extra().get(_KEY)
    if state is None or state.model_generation != model_manager.model_generation():
        return None
    return state.gbxml_path
