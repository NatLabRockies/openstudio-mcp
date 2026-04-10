"""MCP tool definitions for space types."""
from __future__ import annotations

from mcp_server.skills.space_types.operations import (
    get_space_type_details,
)


def register(mcp):
    # list_space_types removed — use list_model_objects("SpaceType")

    @mcp.tool(tags={"loads"}, name="get_space_type_details")
    def get_space_type_details_tool(space_type_name: str):
        """Get space type details — assigned loads, schedules, default constructions, standards info.

        Args:
            space_type_name: Name of the space type to retrieve

        """
        return get_space_type_details(space_type_name=space_type_name)
