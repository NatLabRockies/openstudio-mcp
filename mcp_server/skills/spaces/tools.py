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
    def list_spaces_tool():
        """List all spaces in the currently loaded model.

        Returns array of space objects with:
        - Name, handle, floor area, volume
        - Space type and thermal zone assignments
        - Building story
        - Default construction and schedule sets
        - Origin coordinates and orientation
        - Counts of surfaces, people, lights, equipment

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_spaces()

    @mcp.tool(name="get_space_details")
    def get_space_details_tool(space_name: str):
        """Get detailed information about a specific space.

        Args:
            space_name: Name of the space to retrieve

        Returns detailed space attributes including geometry, loads,
        and assignments.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return get_space_details(space_name=space_name)

    @mcp.tool(name="list_thermal_zones")
    def list_thermal_zones_tool():
        """List all thermal zones in the currently loaded model.

        Returns array of thermal zone objects with:
        - Name, handle, multiplier
        - Floor area and volume
        - Number of spaces in zone
        - Thermostat and setpoint schedules
        - Connected air loop HVAC
        - Zone equipment list

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_thermal_zones()

    @mcp.tool(name="get_thermal_zone_details")
    def get_thermal_zone_details_tool(zone_name: str):
        """Get detailed information about a specific thermal zone.

        Args:
            zone_name: Name of the thermal zone to retrieve

        Returns detailed zone attributes including spaces, equipment,
        thermostats, and HVAC connections.

        Requires a model to be loaded via load_osm_model_tool first.
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

        Returns the created space object with handle, name, geometry,
        and assigned relationships.

        Note: Newly created spaces will have zero floor area and volume
        until surfaces are added. Use save_osm_model_tool to persist changes.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return create_space(name=name, building_story_name=building_story_name,
                          space_type_name=space_type_name)

    @mcp.tool(name="create_thermal_zone")
    def create_thermal_zone_tool(name: str, space_names: list[str] | None = None):
        """Create a new thermal zone in the loaded OpenStudio model.

        Args:
            name: Name for the new thermal zone
            space_names: Optional list of space names to assign to this zone

        Returns the created thermal zone object with handle, name,
        assigned spaces, and calculated floor area/volume.

        Note: If spaces are already assigned to another zone, they will
        be reassigned to this new zone. Use save_osm_model_tool to persist.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return create_thermal_zone(name=name, space_names=space_names)
