"""Per-session model state for multi-user isolation.

Each MCP session (one connection) gets its own loaded OpenStudio model,
keyed by identity.session_key(). stdio / off-request callers collapse to a
single "local" session, so single-user behavior is unchanged.

Idle sessions are evicted after OSMCP_SESSION_TTL seconds (swept on the next
access); a hard LRU cap (OSMCP_MAX_SESSIONS) bounds resident heavy models
regardless of activity.

All model-querying skills call get_model() — they never see the session key,
so the 100+ call sites are untouched by the multi-user refactor.
"""
from __future__ import annotations

import atexit
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.identity import session_key
from mcp_server.stdout_suppression import suppress_openstudio_warnings

# Hard RAM backstop: heavy OSM models must not accumulate unbounded across
# sessions. Idle sessions are swept after the TTL; the LRU cap is the floor.
MAX_SESSIONS = max(1, int(os.environ.get("OSMCP_MAX_SESSIONS", "16")))
# Idle timeout (seconds) before a session's model is dropped. 0 disables TTL.
SESSION_TTL_SECONDS = float(os.environ.get("OSMCP_SESSION_TTL", "1800"))


@dataclass
class _SessionState:
    model: openstudio.model.Model | None = None
    path: Path | None = None
    last_access: float = 0.0  # time.monotonic() of last touch
    # Bumped every time `model` is replaced. Session-scoped skill state (see
    # `extra`) records this at capture time to detect that the model it
    # references was swapped out — id(model) can't be trusted for that
    # because CPython reuses freed addresses.
    generation: int = 0
    # Generic scratch space for skills that need session-scoped state beyond
    # the model itself (e.g. a multi-turn wizard). Keyed by skill name so
    # unrelated skills can't collide. Shares this session's TTL/LRU eviction,
    # so wizard state and its model are always dropped together.
    extra: dict[str, Any] = field(default_factory=dict)


_lock = threading.RLock()
_sessions: dict[str, _SessionState] = {}


def _now() -> float:
    return time.monotonic()


def _touch(state: _SessionState) -> None:
    state.last_access = _now()


def _sweep_idle() -> None:
    """Drop sessions idle longer than the TTL. Caller holds _lock."""
    if SESSION_TTL_SECONDS <= 0:
        return
    cutoff = _now() - SESSION_TTL_SECONDS
    for key in [k for k, st in _sessions.items() if st.last_access < cutoff]:
        _sessions.pop(key, None)  # drop Model ref -> GC


def _evict_if_needed(keep: str) -> None:
    """Evict least-recently-used sessions until there is room to add `keep`.

    No-op when `keep` already has a session: nothing new is being added, so
    there is nothing to make room for. Without this, every load_model() or
    get_session_extra() from an existing session at the cap dropped an
    unrelated session's model.
    """
    if keep in _sessions:
        return
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
    model, _generation = load_model_with_generation(osm_path, version_translate)
    return model


def load_model_with_generation(
    osm_path: Path, version_translate: bool = True,
) -> tuple[openstudio.model.Model, int]:
    """load_model(), also returning the generation this load produced.

    For callers that attach generation-keyed session state to the model they
    just loaded (see get_session_extra): sync tools run concurrently on the
    same session (FastMCP dispatches them via anyio.to_thread), so reading
    model_generation() in a second call could observe a *later* load_model
    and bind the state to the wrong model.
    """
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
        _sweep_idle()
        _evict_if_needed(keep=key)
        st = _sessions.setdefault(key, _SessionState())
        st.model = model
        st.path = Path(osm_path)
        st.generation += 1
        _touch(st)
        return model, st.generation


def save_model(save_path: Path | None = None) -> Path:
    """Save current session's model. Returns the path saved to."""
    key = session_key()
    with _lock:
        _sweep_idle()
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
        _sweep_idle()
        st = _sessions.get(key)
        if st is None or st.model is None:
            raise RuntimeError("No model loaded. Call load_osm_model first.")
        _touch(st)
        return st.model


def get_model_with_generation() -> tuple[openstudio.model.Model, int]:
    """get_model() plus the generation that model belongs to, read under one lock.

    A separate model_generation() call could observe a concurrent load_model
    that landed in between, pairing this model with the *next* model's
    generation. Callers validating generation-keyed session state (see
    get_session_extra) against the model they hold need the two together.
    """
    key = session_key()
    with _lock:
        _sweep_idle()
        st = _sessions.get(key)
        if st is None or st.model is None:
            raise RuntimeError("No model loaded. Call load_osm_model first.")
        _touch(st)
        return st.model, st.generation


def ensure_generation_unchanged(generation: int) -> None:
    """Raise if this session's model has been replaced since `generation` was captured.

    For multi-step operations whose helpers each call get_model(): a
    load_model from a concurrent tool call on the same session between two
    steps would otherwise let one response silently mix results from two
    different models. Capture the generation with get_model_with_generation()
    at the start and call this before returning; the RuntimeError surfaces as
    the operation's ok=False error.
    """
    current = model_generation()
    if current != generation:
        raise RuntimeError(
            "The session model was replaced by another tool call while this operation "
            f"ran (model generation {generation} -> {current}); re-run it on the current model.",
        )


def get_model_path() -> Path | None:
    """Return the file path of the current session's model, or None."""
    with _lock:
        _sweep_idle()
        st = _sessions.get(session_key())
        if st is None:
            return None
        _touch(st)
        return st.path


def get_model_if_loaded() -> openstudio.model.Model | None:
    """Return the current session's model without raising, or None."""
    with _lock:
        _sweep_idle()
        st = _sessions.get(session_key())
        if st is None:
            return None
        _touch(st)
        return st.model


def model_generation() -> int:
    """Monotonic per-session counter, bumped on every load_model.

    Session-scoped skill state (see get_session_extra) records this at
    capture time and compares later to detect that the model it references
    was replaced. Returns 0 if the session has never loaded a model.
    """
    with _lock:
        st = _sessions.get(session_key())
        return st.generation if st else 0


def get_session_extra() -> dict[str, Any]:
    """Return this session's generic scratch dict, creating it if needed.

    For skills that need session-scoped non-model state (e.g. a multi-turn
    wizard) without model_manager knowing anything about that skill's data
    shape. Shares the same TTL/LRU sweep as the model, so wizard-style state
    is always evicted together with the model it references.
    """
    key = session_key()
    with _lock:
        _sweep_idle()
        _evict_if_needed(keep=key)
        st = _sessions.setdefault(key, _SessionState())
        _touch(st)
        return st.extra


def clear_model() -> None:
    """Clear the current session's model state (mainly for testing)."""
    with _lock:
        _sessions.pop(session_key(), None)


def _clear_all() -> None:
    with _lock:
        _sessions.clear()


# Release SWIG Model* refs before interpreter shutdown (openstudio#5421)
atexit.register(_clear_all)
