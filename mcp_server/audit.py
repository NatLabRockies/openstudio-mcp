"""Structured audit logging — who ran what, when, with what outcome.

One JSON line per event, to stderr (-> `docker logs`) and, when MCP_AUDIT_FILE is
set, appended to that file too. Disable entirely with MCP_AUDIT=off.

Sources of events:
  - AuditMiddleware: one `tool_call` line per MCP tool invocation (user, session,
    tool, args preview, ok, duration). One chokepoint — the tools are untouched.
  - simulation ops: `sim_queued` / `sim_launched` / `sim_finished` / `sim_cancelled`
    (these complete in a background thread that no request/middleware sees).
  - retention: `run_evicted` (background GC daemon) / `run_deleted` / `run_pinned`
    / `run_unpinned` (explicit cleanup tools).
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sys
import time

from fastmcp.server.middleware import Middleware

_ENABLED = os.environ.get("MCP_AUDIT", "on").lower() not in ("0", "off", "false", "no")
_logger = logging.getLogger("openstudio-mcp.audit")
_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    _configured = True
    _logger.setLevel(logging.INFO)
    _logger.propagate = False
    fmt = logging.Formatter("%(message)s")
    sh = logging.StreamHandler(sys.stderr)  # stderr is never the JSON-RPC channel
    sh.setFormatter(fmt)
    _logger.addHandler(sh)
    path = os.environ.get("MCP_AUDIT_FILE")
    if path:
        try:
            fh = logging.FileHandler(path)
            fh.setFormatter(fmt)
            _logger.addHandler(fh)
        except Exception:
            pass


def audit(event: str, **fields) -> None:
    """Emit one structured audit line (no-op when MCP_AUDIT=off)."""
    if not _ENABLED:
        return
    _configure()
    rec = {"ts": round(time.time(), 3), "event": event}
    rec.update({k: v for k, v in fields.items() if v is not None})
    with contextlib.suppress(Exception):
        _logger.info(json.dumps(rec, default=str))


def _truncate(s: str, n: int = 300) -> str:
    return s if len(s) <= n else s[:n] + "..."


def _result_ok(result) -> bool | None:
    """Best-effort extract of the tool's {"ok": ...} from a ToolResult."""
    for attr in ("structured_content", "structuredContent"):
        sc = getattr(result, attr, None)
        if isinstance(sc, dict) and "ok" in sc:
            return bool(sc["ok"])
    content = getattr(result, "content", None)
    if content:
        text = getattr(content[0], "text", None)
        if text:
            try:
                d = json.loads(text)
                if isinstance(d, dict) and "ok" in d:
                    return bool(d["ok"])
            except Exception:
                pass
    if getattr(result, "is_error", False) or getattr(result, "isError", False):
        return False
    return None


class AuditMiddleware(Middleware):
    """Logs one `tool_call` audit line per MCP tool invocation."""

    async def on_call_tool(self, context, call_next):
        if not _ENABLED:
            return await call_next(context)
        from mcp_server.identity import session_key, user_key

        name = getattr(context.message, "name", "?")
        args = getattr(context.message, "arguments", None)
        t0 = time.perf_counter()
        ok: bool | None = None
        err: str | None = None
        try:
            result = await call_next(context)
            ok = _result_ok(result)
            return result
        except Exception as e:
            ok, err = False, f"{type(e).__name__}: {e}"
            raise
        finally:
            audit(
                "tool_call",
                user=user_key(), session=session_key(), tool=name, ok=ok,
                ms=round((time.perf_counter() - t0) * 1000, 1),
                args=_truncate(json.dumps(args, default=str)) if args else None,
                error=err,
            )
