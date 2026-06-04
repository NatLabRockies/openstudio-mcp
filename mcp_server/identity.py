"""Caller identity for multi-user isolation.

Two keys, both safe to call from any tool body or off-request:

  session_key() — per-connection. Keys ephemeral *model* state, so two AI
                  windows (even same user) never stomp each other's model.
  user_key()    — per-authenticated-user. Keys durable run dirs + path scope,
                  so a user sees their own runs across sessions.

stdio (single local user) and off-request callers (unit tests, atexit)
collapse to "local", preserving today's single-user behavior unchanged.
"""
from __future__ import annotations

import re

LOCAL = "local"


def _ctx():
    """Current FastMCP request context, or None when off-request/stdio-less."""
    try:
        from fastmcp.server.dependencies import get_context

        return get_context()
    except Exception:
        return None


def session_key() -> str:
    """Stable key for the current connection's model state."""
    ctx = _ctx()
    if ctx is None:
        return LOCAL
    sid = getattr(ctx, "session_id", None)
    return sid or LOCAL


def user_key() -> str:
    """Filesystem-safe key identifying the user (auth principal, else session)."""
    ctx = _ctx()
    if ctx is None:
        return LOCAL
    # StaticTokenVerifier / JWTVerifier populate client_id with the principal.
    cid = getattr(ctx, "client_id", None)
    if cid:
        return _sanitize(cid)
    sid = getattr(ctx, "session_id", None)
    return _sanitize(sid) if sid else LOCAL


def _sanitize(key: str) -> str:
    """Reduce an identity to a safe directory-name component."""
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", str(key)).strip("._")
    return s or LOCAL
