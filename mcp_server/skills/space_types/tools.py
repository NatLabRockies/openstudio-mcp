"""MCP tool definitions for space types."""
from __future__ import annotations

from mcp_server.skills.space_types.operations import (
    list_space_types,
    get_space_type_details,
)


def register(mcp):
    @mcp.tool(name="list_space_types")
    def list_space_types_tool():
        """List all space types in the currently loaded model.

        Returns array of space type objects with:
        - Name, handle
        - Default construction set and schedule set
        - Standards building type and space type
        - Counts of people, lights, equipment loads
        - Number of spaces using this type

        Space types are templates that define characteristics like
        constructions, schedules, and internal loads for spaces.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_space_types()

    @mcp.tool(name="get_space_type_details")
    def get_space_type_details_tool(space_type_name: str):
        """Get detailed information about a specific space type.

        Args:
            space_type_name: Name of the space type to retrieve

        Returns detailed space type attributes including:
        - Basic info (construction set, schedule set, standards type)
        - All internal loads (people, lights, electric equipment, gas equipment)
        - List of spaces assigned to this space type

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return get_space_type_details(space_type_name=space_type_name)
