"""MCP tool definitions for HVAC systems."""
from __future__ import annotations

from mcp_server.osm_helpers import parse_str_list
from mcp_server.skills.hvac.operations import (
    add_air_loop,
    get_air_loop_details,
    get_plant_loop_details,
    get_zone_hvac_details,
    list_air_loops,
    list_plant_loops,
    list_zone_hvac_equipment,
)


def register(mcp):
    @mcp.tool(name="list_air_loops")
    def list_air_loops_tool(detailed: bool = False):
        """List all air loops. Default brief: name, zone count, zone names, terminal type.
        Use detailed=True only when you need full supply component lists and OA system info.

        Args:
            detailed: Add supply_components, demand_terminals per zone, OA system, setpoint managers
        """
        return list_air_loops(detailed=detailed)

    @mcp.tool(name="get_air_loop_details")
    def get_air_loop_details_tool(air_loop_name: str):
        """Get detailed information about a specific air loop HVAC system.

        Args:
            air_loop_name: Name of the air loop to retrieve
        """
        return get_air_loop_details(air_loop_name=air_loop_name)

    @mcp.tool(name="list_plant_loops")
    def list_plant_loops_tool(detailed: bool = False):
        """List all plant loops. Default brief: name, component counts, primary equipment type.
        Use detailed=True only when you need full supply/demand component lists.

        Args:
            detailed: Add full supply/demand component lists with types and names
        """
        return list_plant_loops(detailed=detailed)

    @mcp.tool(name="list_zone_hvac_equipment")
    def list_zone_hvac_equipment_tool(
        thermal_zone_name: str | None = None,
        equipment_type: str | None = None,
        max_results: int = 10,
    ):
        """List zone HVAC equipment. Default 10 results; use filters to narrow.

        Common filters:
        - Equipment in a zone: thermal_zone_name="Zone 1"

        Args:
            thermal_zone_name: Filter by thermal zone
            equipment_type: Filter by iddObjectType (e.g. "ZoneHVACPackagedTerminalAirConditioner")
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_zone_hvac_equipment(thermal_zone_name=thermal_zone_name,
                                       equipment_type=equipment_type, max_results=mr)

    @mcp.tool(name="add_air_loop")
    def add_air_loop_tool(name: str, thermal_zone_names: list[str] | str | None = None):
        """Add a new air loop HVAC system to the loaded OpenStudio model.

        Args:
            name: Name for the new air loop
            thermal_zone_names: Optional list of thermal zone names to serve

        """
        return add_air_loop(name=name, thermal_zone_names=parse_str_list(thermal_zone_names))

    @mcp.tool(name="get_plant_loop_details")
    def get_plant_loop_details_tool(plant_loop_name: str):
        """Get detailed information about a specific plant loop.

        Args:
            plant_loop_name: Name of the plant loop to retrieve
        """
        return get_plant_loop_details(plant_loop_name=plant_loop_name)

    @mcp.tool(name="get_zone_hvac_details")
    def get_zone_hvac_details_tool(equipment_name: str):
        """Get detailed information about specific zone HVAC equipment.

        Args:
            equipment_name: Name of the zone HVAC equipment to retrieve
        """
        return get_zone_hvac_details(equipment_name=equipment_name)
