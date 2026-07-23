"""Transport protection: cap serialized tool-response size.

Issue #98: run_qaqc_checks on a 27-zone model produced a ~19MB response;
writing it to the stdio JSON-RPC channel killed the server mid-call (clean
exit 0), and the client lost the session's tool roster until manual
reconnect. Individual tools bound their own output, but one escaping bug
must not take down the session — any response over the cap is spilled to a
file under the caller's run area and replaced with a small pointer response.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any

from fastmcp.server.middleware import Middleware
from fastmcp.tools.tool import ToolResult

from mcp_server.config import user_run_root
from mcp_server.util import create_run_dir

_PREVIEW_CHARS = 2000


def max_response_bytes() -> int:
    """Response cap in bytes (OSMCP_MAX_TOOL_RESPONSE_MB, default 1MB).

    Invalid, non-finite, or non-positive values clamp to the default — this
    runs on every tool call, so a bad env value must never raise (nan/inf
    parse as floats but crash int()) or flag every response as oversized.
    """
    default = 1024 * 1024
    try:
        mb = float(os.environ.get("OSMCP_MAX_TOOL_RESPONSE_MB", "1"))
    except ValueError:
        return default
    if not math.isfinite(mb) or mb <= 0:
        return default
    return int(mb * 1024 * 1024)


def serialize_result(result: Any) -> str | None:
    """Serialized view of a ToolResult payload (structured content, else text)."""
    sc = getattr(result, "structured_content", None)
    if sc is not None:
        try:
            return json.dumps(sc, default=str)
        except Exception:
            return None
    content = getattr(result, "content", None)
    if content:
        texts = [t for t in (getattr(block, "text", None) for block in content) if t]
        if texts:
            return "\n".join(texts)
    return None


def build_replacement(tool: str, serialized: str, cap: int) -> dict[str, Any]:
    """Small pointer response standing in for an oversized payload."""
    size = len(serialized.encode("utf-8", errors="replace"))
    # Carry the original ok through — a huge error payload is still an error
    ok = True
    try:
        original = json.loads(serialized)
        if isinstance(original, dict) and "ok" in original:
            ok = bool(original["ok"])
    except Exception:
        pass
    replacement: dict[str, Any] = {
        "ok": ok,
        "response_truncated": True,
        "tool": tool,
        "response_size_bytes": size,
        "preview": serialized[:_PREVIEW_CHARS],
    }
    try:
        run_id, spill_dir = create_run_dir(user_run_root(), "oversized", tool)
        spill_path = spill_dir / "response.json"
        spill_path.write_text(serialized, encoding="utf-8")
        replacement["spilled_path"] = str(spill_path)
        replacement["run_id"] = run_id
        replacement["user_message"] = (
            f"{tool} returned {size} bytes — over the {cap}-byte MCP response cap "
            "(OSMCP_MAX_TOOL_RESPONSE_MB). Full payload saved to spilled_path; use "
            "copy_file to export it, or rerun with narrower filters."
        )
    except Exception as e:
        replacement["user_message"] = (
            f"{tool} returned {size} bytes — over the {cap}-byte MCP response cap "
            f"(OSMCP_MAX_TOOL_RESPONSE_MB) — and spilling it to disk failed: {e}. "
            "Rerun with narrower filters."
        )
    return replacement


class ResponseSizeGuard(Middleware):
    """Replaces oversized tool responses so they never hit the transport."""

    async def on_call_tool(self, context, call_next):
        result = await call_next(context)
        try:
            serialized = serialize_result(result)
        except Exception:
            return result
        cap = max_response_bytes()
        if serialized is None or len(serialized.encode("utf-8", errors="replace")) <= cap:
            return result
        tool = getattr(getattr(context, "message", None), "name", "tool")
        return ToolResult(structured_content=build_replacement(tool, serialized, cap))
