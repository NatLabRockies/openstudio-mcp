"""MCP tool definitions for spaces and thermal zones."""
from __future__ import annotations

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
    def list_spaces_tool(detailed: bool = False):
        """List all spaces. Default brief: name, floor_area_m2, thermal_zone. Use get_space_details for full info.

        Args:
            detailed: Return all fields (handle, volume, origin, loads counts, etc.)
        """
        return list_spaces(detailed=detailed)

    @mcp.tool(name="get_space_details")
    def get_space_details_tool(space_name: str):
        """Get detailed information about a specific space.

        Args:
            space_name: Name of the space to retrieve
        """
        return get_space_details(space_name=space_name)

    @mcp.tool(name="list_thermal_zones")
    def list_thermal_zones_tool(detailed: bool = False):
        """List all thermal zones. Brief: name, floor_area, num_equipment. Use get_thermal_zone_details for full.

        Args:
            detailed: Return all fields (thermostat, schedules, equipment list, air_loop, etc.)
        """
        return list_thermal_zones(detailed=detailed)

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
    def create_thermal_zone_tool(name: str, space_names: list[str] | None = None):
        """Create a new thermal zone in the loaded OpenStudio model.

        Args:
            name: Name for the new thermal zone
            space_names: Optional list of space names to assign to this zone

        """
        return create_thermal_zone(name=name, space_names=space_names)
