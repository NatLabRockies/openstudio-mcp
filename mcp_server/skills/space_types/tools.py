"""MCP tool definitions for space types."""
from __future__ import annotations

from mcp_server.skills.space_types.operations import (
    get_space_type_details,
    list_space_types,
)


def register(mcp):
    @mcp.tool(name="list_space_types")
    def list_space_types_tool(max_results: int = 10):
        """List space types. Default 10 results.

        Args:
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_space_types(max_results=mr)

    @mcp.tool(name="get_space_type_details")
    def get_space_type_details_tool(space_type_name: str):
        """Get detailed information about a specific space type.

        Args:
            space_type_name: Name of the space type to retrieve

        """
        return get_space_type_details(space_type_name=space_type_name)
