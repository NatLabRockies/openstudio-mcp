"""MCP tool definitions for building-level queries."""

from __future__ import annotations

from mcp_server.skills.building.operations import (
    get_building_info,
    get_model_summary,
    list_building_stories,
)


def register(mcp):
    @mcp.tool(name="get_building_info")
    def get_building_info_tool():
        """Get detailed information about the building object.

        Returns building-level attributes including:
        - Floor area (total and conditioned)
        - Exterior surface and wall areas
        - People density and count
        - Lighting power density
        - Equipment power density
        - Infiltration rates
        - North axis orientation
        - Standards building type and number of stories

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return get_building_info()

    @mcp.tool(name="get_model_summary")
    def get_model_summary_tool():
        """Get a high-level summary of the entire model.

        Returns counts of major object types:
        - Building info (name, floor area)
        - Spaces, zones, and stories
        - Geometry (surfaces, subsurfaces, shading)
        - Constructions and materials
        - Loads (space types, people, lights, equipment)
        - Schedules
        - HVAC systems (air loops, plant loops, zone equipment)

        Useful for understanding model scope and complexity.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return get_model_summary()

    @mcp.tool(name="list_building_stories")
    def list_building_stories_tool():
        """List all building stories in the model.

        Returns an array of building story objects with:
        - Name
        - Z-coordinate (elevation)
        - Floor-to-floor height
        - Floor-to-ceiling height
        - Number of spaces on the story
        - Default construction and schedule sets

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_building_stories()
