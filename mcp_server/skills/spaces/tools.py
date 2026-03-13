"""MCP tool definitions for spaces and thermal zones."""
from __future__ import annotations

from mcp_server.osm_helpers import parse_str_list
from mcp_server.skills.spaces.operations import (
    create_space,
    create_thermal_zone,
    get_space_details,
    get_thermal_zone_details,
    list_spaces,
    list_thermal_zones,
)


def register(mcp):
    @mcp.tool(name="list_spaces")
    def list_spaces_tool(
        detailed: bool = False,
        thermal_zone_name: str | None = None,
        building_story_name: str | None = None,
        space_type_name: str | None = None,
        max_results: int = 10,
    ):
        """List spaces. Default 10 results; use filters to narrow.

        Common filters:
        - Spaces on a story: building_story_name="Floor 1"
        - Spaces in a zone: thermal_zone_name="Zone 1"

        Args:
            detailed: Return all fields (volume, origin, loads counts, etc.)
            thermal_zone_name: Filter by thermal zone
            building_story_name: Filter by building story
            space_type_name: Filter by space type
            max_results: Max items to return (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_spaces(detailed=detailed, thermal_zone_name=thermal_zone_name,
                          building_story_name=building_story_name,
                          space_type_name=space_type_name, max_results=mr)

    @mcp.tool(name="get_space_details")
    def get_space_details_tool(space_name: str):
        """Get detailed information about a specific space.

        Args:
            space_name: Name of the space to retrieve
        """
        return get_space_details(space_name=space_name)

    @mcp.tool(name="list_thermal_zones")
    def list_thermal_zones_tool(
        detailed: bool = False,
        air_loop_name: str | None = None,
        max_results: int = 10,
    ):
        """List thermal zones. Default 10 results; use filters to narrow.

        Common filters:
        - Zones on an air loop: air_loop_name="DOAS"

        Args:
            detailed: Return all fields (thermostat, schedules, air_loop, etc.)
            air_loop_name: Filter by air loop name
            max_results: Max items to return (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_thermal_zones(detailed=detailed, air_loop_name=air_loop_name,
                                 max_results=mr)

    @mcp.tool(name="get_thermal_zone_details")
    def get_thermal_zone_details_tool(zone_name: str):
        """Get detailed information about a specific thermal zone.

        Args:
            zone_name: Name of the thermal zone to retrieve
        """
        return get_thermal_zone_details(zone_name=zone_name)

    @mcp.tool(name="create_space")
    def create_space_tool(name: str, building_story_name: str | None = None,
                         space_type_name: str | None = None):
        """Create a new space in the loaded OpenStudio model.

        Args:
            name: Name for the new space
            building_story_name: Optional name of building story to assign
            space_type_name: Optional name of space type to assign

        """
        return create_space(name=name, building_story_name=building_story_name,
                          space_type_name=space_type_name)

    @mcp.tool(name="create_thermal_zone")
    def create_thermal_zone_tool(name: str, space_names: list[str] | str | None = None):
        """Create a new thermal zone in the loaded OpenStudio model.

        Args:
            name: Name for the new thermal zone
            space_names: Optional list of space names to assign to this zone

        """
        return create_thermal_zone(name=name, space_names=parse_str_list(space_names))
