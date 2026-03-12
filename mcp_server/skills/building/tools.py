"""MCP tool definitions for building-level queries."""
from __future__ import annotations

from mcp_server.skills.building.operations import (
    get_building_info,
    get_model_summary,
)


def register(mcp):
    @mcp.tool(name="get_building_info")
    def get_building_info_tool():
        """Get building-level attributes (floor area, people/lighting/equipment densities, orientation)."""
        return get_building_info()

    @mcp.tool(name="get_model_summary")
    def get_model_summary_tool():
        """Get object counts for all major categories (spaces, zones, geometry, HVAC, loads, schedules)."""
        return get_model_summary()

    # list_building_stories removed — use list_model_objects("BuildingStory")
