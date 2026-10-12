"""Reject authenticated tool calls without a usable storage principal."""
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from fastmcp.tools.tool import ToolResult

from mcp_server.config import InvalidUserKeyError
from mcp_server.identity import InvalidPrincipalError, user_key


class IdentityGuard(Middleware):
    """Keep identity failures inside the normal tool error response contract."""

    async def on_call_tool(self, context, call_next):
        try:
            user_key()
            return await call_next(context)
        except (InvalidPrincipalError, InvalidUserKeyError) as exc:
            return ToolResult(structured_content={"ok": False, "error": str(exc)})
        except ToolError as exc:
            # FastMCP wraps exceptions from tool bodies, retaining the original cause.
            if not isinstance(exc.__cause__, (InvalidPrincipalError, InvalidUserKeyError)):
                raise
            return ToolResult(structured_content={"ok": False, "error": str(exc.__cause__)})
