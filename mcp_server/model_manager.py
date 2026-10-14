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
import hashlib
import itertools
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
    # Token of the load_model() that produced `model`, drawn from the
    # process-wide _load_tokens counter so it is never reused — not a
    # per-session count, which would restart at 1 in the fresh state a
    # TTL/LRU-evicted session gets on its next load and let an in-flight
    # operation that captured generation N mistake the replacement model for
    # its own. Session-scoped skill state (see `extra`) records this at
    # capture time to detect that the model it references was swapped out —
    # id(model) can't be trusted for that because CPython reuses freed
    # addresses.
    generation: int = 0
    # Generic scratch space for skills that need session-scoped state beyond
    # the model itself (e.g. a multi-turn wizard). Keyed by skill name so
    # unrelated skills can't collide. Shares this session's TTL/LRU eviction,
    # so wizard state and its model are always dropped together.
    extra: dict[str, Any] = field(default_factory=dict)
    # Resolved file paths this session loaded or saved, each with the digest of
    # the model at that moment. run_simulation compares against this to warn
    # when the file on disk is behind the session model (issue #177). Every
    # path stays in the dict, so a save-as to B keeps A with its older digest.
    clean: dict[Path, str] = field(default_factory=dict)
    # Serializes digest + file write + `clean` publication of saves on this
    # session. Two concurrent saves to one path could otherwise write in one
    # order and publish in the other, leaving `clean` describing a model that
    # is not the one on disk (Codex review of #192).
    save_lock: threading.Lock = field(default_factory=threading.Lock)


_lock = threading.RLock()
_sessions: dict[str, _SessionState] = {}
# One token per load_model() across every session for the life of the process
# (advanced under _lock). See _SessionState.generation for why it is not
# per-session.
_load_tokens = itertools.count(1)


def _now() -> float:
    return time.monotonic()


def _digest(model: openstudio.model.Model) -> str:
    """Content digest of the model (SHA-256 of its IDF text).

    0.27 s on a 5k-object model, deterministic for one model object. Not
    comparable across loads: the version translator assigns new handles.
    """
    return hashlib.sha256(str(model).encode("utf-8")).hexdigest()


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
    return _load_into_session(osm_path, version_translate, keep_clean=False)


def reload_model(osm_path: Path, expected_generation: int) -> openstudio.model.Model:
    """Replace the session model's CONTENT with a file the server wrote itself.

    For apply_measure, which reloads the measure's output OSM. Differences
    from load_model:

    - `path` is NOT changed: the session keeps pointing at the file the user
      loaded (or the create_* tool wrote), so a bare save_model() and the
      files/ companion-dir lookups still target the user's model, not the
      internal run-dir copy that run retention deletes (issue #195).
    - The paths the user loaded or saved stay in `clean` with their older
      digests, so the next run_simulation on one of them warns that it is
      behind the session model (issue #177).
    - `expected_generation` (from get_model_with_generation() when the caller
      captured the model it sent to the measure) must still be the session's
      current generation. A concurrent load_model on this session, or TTL/LRU
      eviction, while the measure ran raises RuntimeError and publishes
      nothing; otherwise the measure output would land under the other
      model's path and a bare save would overwrite that file.

    Known false positive: a file written by an older OpenStudio version gets
    new object handles on every version-translated load, so after a measure
    that changed nothing the reloaded model still digests differently and the
    user's path warns. Same-version files (everything this server saves) are
    stable across reloads.
    """
    model, _generation = _load_into_session(
        osm_path, True, keep_clean=True, expected_generation=expected_generation,
    )
    return model


def _load_into_session(
    osm_path: Path, version_translate: bool, *, keep_clean: bool,
    expected_generation: int | None = None,
) -> tuple[openstudio.model.Model, int]:
    abs_path = str(Path(osm_path).resolve())
    with suppress_openstudio_warnings():
        if version_translate:
            loaded = openstudio.osversion.VersionTranslator().loadModel(abs_path)
        else:
            loaded = openstudio.model.Model.load(abs_path)
        if not loaded.is_initialized():
            raise ValueError(f"Failed to load OSM: {osm_path}")
        model = loaded.get()
        # Taken before the model is published to the session, so no concurrent
        # tool call on this session can edit it between load and digest.
        digest = _digest(model)
    key = session_key()
    with _lock:
        _sweep_idle()
        if keep_clean:
            # Internal reload: checked before any state is created or evicted,
            # so a rejected reload has no side effects on this or other sessions.
            current = _sessions.get(key)
            current_generation = current.generation if current is not None else 0
            if current is None or current_generation != expected_generation:
                raise RuntimeError(
                    "The session model was replaced or evicted while the measure ran "
                    f"(model generation {expected_generation} -> {current_generation}); "
                    f"nothing was changed. The measure output is at {osm_path}: "
                    "load_osm_model it to adopt the result.",
                )
        _evict_if_needed(keep=key)
        st = _sessions.setdefault(key, _SessionState())
        st.model = model
        if not keep_clean:
            # A user load (or a create_* tool's output) is the file the session
            # points at; an internal reload keeps it (issue #195).
            st.path = Path(osm_path)
        st.generation = next(_load_tokens)
        if not keep_clean:
            st.clean = {}
        if not keep_clean or Path(abs_path) not in st.clean:
            # A user load starts a fresh clean set. An internal reload keeps the
            # user's paths; the reloaded file itself is only recorded when it is
            # new, so a user path that was reloaded over keeps its older digest.
            st.clean[Path(abs_path)] = digest
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
        save_lock = st.save_lock
        _touch(st)
    with save_lock, suppress_openstudio_warnings():
        # Digest BEFORE the save: an edit that lands between the two reaches
        # disk but not the digest, so the next run_simulation warns once (safe
        # side). Digesting after the save could record an edit that never
        # reached disk and hide a real warning.
        digest = _digest(model)
        saved = model.save(str(path), True)
        if saved:
            with _lock:
                st = _sessions.get(key)
                # Recorded even when a concurrent load_model replaced the
                # session model meanwhile: the file now holds THIS model's
                # content, so its digest is the truth about the file. The
                # replacement model's digest differs, so run_simulation on this
                # path warns, which is correct. Still under save_lock so no
                # other save on this session can write between the two steps.
                if st is not None:
                    st.clean[Path(path).resolve()] = digest
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


def unsaved_edits_for(path: Path) -> bool:
    """True when `path` was loaded or saved by this session and the session model has changed since.

    A path this session never touched returns False: the check covers only
    what this session knows the file held. The digest runs outside _lock
    (0.27 s on a 5k-object model would block every other session).
    """
    key = session_key()
    with _lock:
        _sweep_idle()
        st = _sessions.get(key)
        if st is None or st.model is None:
            return False
        clean_digest = st.clean.get(Path(path).resolve())
        if clean_digest is None:
            return False
        model = st.model
        _touch(st)
    return _digest(model) != clean_digest


def get_model_path() -> Path | None:
    """Return the file path of the current session's model, or None.

    This is the file the user loaded or a create_* tool wrote: the default
    target of a bare save_model() and the base dir of the model's companion
    files/ resources. An internal reload (reload_model) does not move it.
    """
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
    """Token of the load that produced this session's current model.

    Process-wide monotonic and never reused, so it survives the session
    being evicted and re-created (see _SessionState.generation). Session-
    scoped skill state (see get_session_extra) records this at capture time
    and compares later to detect that the model it references was replaced.
    Returns 0 if the session currently holds no model.
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
