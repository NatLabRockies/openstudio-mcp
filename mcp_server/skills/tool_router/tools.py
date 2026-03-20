"""MCP tool registration for tool router skill."""
from __future__ import annotations

from .operations import recommend_tools_op


def register(mcp):
    @mcp.tool(tags={"core"}, name="recommend_tools")
    def recommend_tools_tool(task_description: str) -> dict:
        """Recommend relevant tools for a task. Call this when unsure which
        tool to use. Returns a focused group of tools instead of all 140.

        Args:
            task_description: What you want to do (e.g. "add VAV reheat",
                "extract EUI", "create a measure")

        Returns the recommended group name, tool list with descriptions,
        and other available groups.
        """
        return recommend_tools_op(task_description)
