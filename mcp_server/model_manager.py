"""Per-session model state for multi-user isolation.

Each MCP session (one connection) gets its own loaded OpenStudio model,
keyed by identity.session_key(). stdio / off-request callers collapse to a
single "local" session, so single-user behavior is unchanged.

All model-querying skills call get_model() — they never see the session key,
so the 100+ call sites are untouched by the multi-user refactor.
"""
from __future__ import annotations

import atexit
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import openstudio

from mcp_server.identity import session_key
from mcp_server.stdout_suppression import suppress_openstudio_warnings

# Hard RAM backstop: heavy OSM models must not accumulate unbounded across
# sessions. Idle-TTL eviction is a follow-up; this LRU cap is the safety net.
MAX_SESSIONS = max(1, int(os.environ.get("OSMCP_MAX_SESSIONS", "16")))


@dataclass
class _SessionState:
    model: openstudio.model.Model | None = None
    path: Path | None = None
    last_access: int = 0


_lock = threading.RLock()
_sessions: dict[str, _SessionState] = {}
_tick = 0


def _touch(state: _SessionState) -> None:
    global _tick
    _tick += 1
    state.last_access = _tick


def _evict_if_needed(keep: str) -> None:
    """Evict least-recently-used sessions until under cap (never `keep`)."""
    while len(_sessions) >= MAX_SESSIONS:
        victim = min(
            (k for k in _sessions if k != keep),
            key=lambda k: _sessions[k].last_access,
            default=None,
        )
        if victim is None:
            return
        _sessions.pop(victim, None)  # drop Model ref -> GC


def load_model(osm_path: Path, version_translate: bool = True) -> openstudio.model.Model:
    """Load an OSM file and set it as the current session's model."""
    abs_path = str(Path(osm_path).resolve())
    with suppress_openstudio_warnings():
        if version_translate:
            loaded = openstudio.osversion.VersionTranslator().loadModel(abs_path)
        else:
            loaded = openstudio.model.Model.load(abs_path)
        if not loaded.is_initialized():
            raise ValueError(f"Failed to load OSM: {osm_path}")
        model = loaded.get()
    key = session_key()
    with _lock:
        _evict_if_needed(keep=key)
        st = _sessions.setdefault(key, _SessionState())
        st.model = model
        st.path = Path(osm_path)
        _touch(st)
    return model


def save_model(save_path: Path | None = None) -> Path:
    """Save current session's model. Returns the path saved to."""
    key = session_key()
    with _lock:
        st = _sessions.get(key)
        if st is None or st.model is None:
            raise RuntimeError("No model loaded.")
        path = save_path or st.path
        if path is None:
            raise RuntimeError("No save path specified and no current path.")
        model = st.model
        _touch(st)
    with suppress_openstudio_warnings():
        model.save(str(path), True)
    return path


def get_model() -> openstudio.model.Model:
    """Get the currently loaded model for this session, or raise."""
    key = session_key()
    with _lock:
        st = _sessions.get(key)
        if st is None or st.model is None:
            raise RuntimeError("No model loaded. Call load_osm_model first.")
        _touch(st)
        return st.model


def get_model_path() -> Path | None:
    """Return the file path of the current session's model, or None."""
    with _lock:
        st = _sessions.get(session_key())
        return st.path if st else None


def get_model_if_loaded() -> openstudio.model.Model | None:
    """Return the current session's model without raising, or None."""
    with _lock:
        st = _sessions.get(session_key())
        return st.model if st else None


def clear_model() -> None:
    """Clear the current session's model state (mainly for testing)."""
    with _lock:
        _sessions.pop(session_key(), None)


def _clear_all() -> None:
    with _lock:
        _sessions.clear()


# Release SWIG Model* refs before interpreter shutdown (openstudio#5421)
atexit.register(_clear_all)
