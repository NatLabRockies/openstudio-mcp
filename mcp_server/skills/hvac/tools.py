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
    @mcp.tool(tags={"hvac"}, name="list_air_loops")
    def list_air_loops_tool(detailed: bool = False):
        """List all air loops (AHUs / air handling units / central air systems).
        Default brief: name, zone count, zone names, terminal type. Supply/return details with detailed=True.

        Args:
            detailed: Add supply_components, demand_terminals per zone, OA system, setpoint managers
        """
        return list_air_loops(detailed=detailed)

    @mcp.tool(tags={"hvac"}, name="get_air_loop_details")
    def get_air_loop_details_tool(air_loop_name: str):
        """Get detailed air loop info: components, outdoor air system, sizing, supply temperature.

        Args:
            air_loop_name: Name of the air loop to retrieve
        """
        return get_air_loop_details(air_loop_name=air_loop_name)

    @mcp.tool(tags={"hvac"}, name="list_plant_loops")
    def list_plant_loops_tool(detailed: bool = False):
        """List all plant loops (hot water, chilled water, condenser water, heating/cooling).
        Default brief: name, component counts, primary equipment type. Full lists with detailed=True.

        Args:
            detailed: Add full supply/demand component lists with types and names
        """
        return list_plant_loops(detailed=detailed)

    @mcp.tool(tags={"hvac"}, name="list_zone_hvac_equipment")
    def list_zone_hvac_equipment_tool(
        thermal_zone_name: str | None = None,
        equipment_type: str | None = None,
        max_results: int = 10,
    ):
        """List zone HVAC equipment (baseboard, fan coil, PTAC, PTHP, unit heater, radiant).
        Default 10 results; use filters to narrow.

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

    @mcp.tool(tags={"hvac"}, name="add_air_loop")
    def add_air_loop_tool(name: str, thermal_zone_names: list[str] | str | None = None):
        """Create a new air handling unit (air loop) and optionally connect thermal zones.

        Args:
            name: Name for the new air loop
            thermal_zone_names: Optional list of thermal zone names to serve

        """
        return add_air_loop(name=name, thermal_zone_names=parse_str_list(thermal_zone_names))

    @mcp.tool(tags={"hvac"}, name="get_plant_loop_details")
    def get_plant_loop_details_tool(plant_loop_name: str):
        """Get plant loop details: supply equipment, demand components, pump, setpoint manager.

        Args:
            plant_loop_name: Name of the plant loop to retrieve
        """
        return get_plant_loop_details(plant_loop_name=plant_loop_name)

    @mcp.tool(tags={"hvac"}, name="get_zone_hvac_details")
    def get_zone_hvac_details_tool(equipment_name: str):
        """Get zone-level heating/cooling equipment properties and configuration.

        Args:
            equipment_name: Name of the zone HVAC equipment to retrieve
        """
        return get_zone_hvac_details(equipment_name=equipment_name)
