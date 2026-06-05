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


def _access_token():
    """The verified access token for this request, or None (no auth / off-request)."""
    try:
        from fastmcp.server.dependencies import get_access_token

        return get_access_token()
    except Exception:
        return None


def _is_http_transport() -> bool:
    """True only for the remote/multi-user HTTP server (else stdio = single user)."""
    import os
    return os.environ.get("MCP_TRANSPORT", "stdio").lower() in ("http", "streamable-http")


def user_key() -> str:
    """Filesystem-safe key identifying the user (auth principal, else session).

    stdio is inherently single-user (one local process per client), so it always
    resolves to "local" — which owns the whole run root, preserving the original
    single-container workflow. Only the HTTP server scopes per session/principal.
    """
    # With auth, the verified token's client_id is the principal (StaticToken/JWT).
    tok = _access_token()
    cid = getattr(tok, "client_id", None) if tok is not None else None
    if cid:
        return _sanitize(cid)
    # Non-HTTP transport = one local user; FastMCP still assigns stdio a session
    # id, but that must not splinter the single user's run root per connection.
    if not _is_http_transport():
        return LOCAL
    ctx = _ctx()
    if ctx is None:
        return LOCAL
    sid = getattr(ctx, "session_id", None)
    return _sanitize(sid) if sid else LOCAL


def _sanitize(key: str) -> str:
    """Reduce an identity to a safe directory-name component."""
    s = re.sub(r"[^A-Za-z0-9_.-]", "_", str(key)).strip("._")
    return s or LOCAL
