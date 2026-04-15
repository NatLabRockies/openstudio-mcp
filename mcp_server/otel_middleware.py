"""FastMCP middleware that wraps MCP tool calls with OpenTelemetry spans.

Each tools/call request becomes a SERVER span with:
  - mcp.tool.name    — the tool being invoked
  - mcp.tool.args    — JSON-serialized arguments, truncated to 512 chars
  - mcp.tool.success — true/false based on whether result has ok=False
  - mcp.method.name  — always "tools/call"
  - mcp.server.name  — "openstudio-mcp"

Errors: spans are marked ERROR when the tool raises or returns {"ok": False}.
Trace context is propagated via W3C traceparent headers in MCP request meta.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.telemetry import extract_trace_context
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanKind, StatusCode, use_span

from mcp_server.telemetry import _truncate, get_tracer, record_tool_error

logger = logging.getLogger(__name__)

_SERVER_NAME = "openstudio-mcp"


def _extract_tool_name(context: MiddlewareContext[Any]) -> str:
    """Pull the tool name out of a CallToolRequestParams message."""
    msg = context.message
    # mcp.types.CallToolRequestParams has a .name attribute
    if hasattr(msg, "name"):
        return str(msg.name)
    if hasattr(msg, "params") and hasattr(msg.params, "name"):
        return str(msg.params.name)
    return "unknown"


def _extract_tool_args(context: MiddlewareContext[Any]) -> str:
    """Serialize tool arguments to a truncated JSON string."""
    msg = context.message
    args: Any = None
    if hasattr(msg, "arguments"):
        args = msg.arguments
    elif hasattr(msg, "params") and hasattr(msg.params, "arguments"):
        args = msg.params.arguments
    if args is None:
        return "{}"
    return _truncate(args)


def _result_is_error(result: Any) -> tuple[bool, str]:
    """Return (is_error, error_message) from a tool result.

    Handles both raw dicts returned by operations and ToolResult objects
    that wrap content items.
    """
    if result is None:
        return False, ""

    # FastMCP ToolResult wraps content as a list; check for isError flag
    if hasattr(result, "isError") and result.isError:
        # Try to extract message from content
        msg = ""
        if hasattr(result, "content") and result.content:
            first = result.content[0]
            if hasattr(first, "text"):
                msg = str(first.text)[:512]
        return True, msg

    # Raw dict from operations (ok=False pattern)
    if isinstance(result, dict) and result.get("ok") is False:
        return True, str(result.get("error") or result.get("message") or "ok=False")

    return False, ""


class OtelMiddleware(Middleware):
    """OpenTelemetry tracing middleware for FastMCP.

    Wraps every tools/call with a SERVER span.  No-op when no TracerProvider
    is configured (i.e., when telemetry is disabled via env vars).
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        tool_name = _extract_tool_name(context)
        tool_args = _extract_tool_args(context)

        tracer = get_tracer()

        # Extract W3C trace context from MCP request meta for end-to-end tracing
        meta = None
        if context.fastmcp_context and hasattr(context.fastmcp_context, "request_context"):
            rc = context.fastmcp_context.request_context
            if hasattr(rc, "meta"):
                meta = rc.meta
        parent_ctx = extract_trace_context(meta)

        with tracer.start_as_current_span(
            tool_name,
            context=parent_ctx,
            kind=SpanKind.SERVER,
        ) as span:
            if isinstance(span, NonRecordingSpan):
                # Telemetry disabled — pass through without overhead
                return await call_next(context)

            span.set_attribute("mcp.method.name", "tools/call")
            span.set_attribute("mcp.server.name", _SERVER_NAME)
            span.set_attribute("mcp.tool.name", tool_name)
            span.set_attribute("mcp.tool.args", tool_args)

            try:
                result = await call_next(context)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(StatusCode.ERROR, str(exc))
                span.set_attribute("mcp.tool.success", False)
                raise

            is_err, err_msg = _result_is_error(result)
            span.set_attribute("mcp.tool.success", not is_err)
            if is_err:
                span.set_status(StatusCode.ERROR, err_msg)
                span.set_attribute("error.message", err_msg)

            return result
