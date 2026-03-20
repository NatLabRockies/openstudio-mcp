"""MCP tool definitions for building-level queries."""
from __future__ import annotations

from mcp_server.skills.building.operations import (
    get_building_info,
    get_model_summary,
)


def register(mcp):
    @mcp.tool(name="get_building_info", tags={"core"})
    def get_building_info_tool():
        """Get building-level attributes: total floor area, conditioned floor area,
        exterior wall area, people density, lighting power density, equipment power
        density, infiltration rate, north axis orientation, standards building type,
        number of stories.
        """
        return get_building_info()

    @mcp.tool(name="get_model_summary", tags={"core"})
    def get_model_summary_tool():
        """Get object counts for all major categories: spaces, thermal zones,
        building stories, surfaces, subsurfaces, shading, constructions,
        materials, people, lights, equipment, schedules, air loops, plant
        loops, zone HVAC equipment. Use to understand model scope.
        Requires loaded model. To preview without loading, use inspect_osm_summary.
        """
        return get_model_summary()

    # list_building_stories removed — use list_model_objects("BuildingStory")
