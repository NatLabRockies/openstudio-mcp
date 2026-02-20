"""MCP tool definitions for HVAC systems."""

from __future__ import annotations

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
    def list_air_loops_tool():
        """List all air loop HVAC systems in the currently loaded model.

        Returns array of air loop objects with:
        - Name, handle
        - Number of thermal zones served
        - List of thermal zones
        - Number and list of supply components (limited to first 10)

        Air loops distribute conditioned air to thermal zones via
        supply and return ducts, fans, heating/cooling coils, etc.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_air_loops()

    @mcp.tool(name="get_air_loop_details")
    def get_air_loop_details_tool(air_loop_name: str):
        """Get detailed information about a specific air loop HVAC system.

        Args:
            air_loop_name: Name of the air loop to retrieve

        Returns detailed air loop attributes including:
        - Thermal zones served
        - Supply components with types and names
        - Detailed components (fans, coils with specs) - NEW Phase 4D
        - Outdoor air system details (economizer settings) - NEW Phase 4D
        - Setpoint managers - NEW Phase 4D

        Enhanced in Phase 4D for component validation testing.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return get_air_loop_details(air_loop_name=air_loop_name)

    @mcp.tool(name="list_plant_loops")
    def list_plant_loops_tool():
        """List all plant loops in the currently loaded model.

        Returns array of plant loop objects with:
        - Name, handle
        - Number and list of supply components (limited to first 10)
        - Number and list of demand components (limited to first 10)

        Plant loops circulate hot water, chilled water, or condenser water
        between equipment like boilers, chillers, cooling towers, and coils.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_plant_loops()

    @mcp.tool(name="list_zone_hvac_equipment")
    def list_zone_hvac_equipment_tool():
        """List all zone HVAC equipment in the currently loaded model.

        Returns array of zone HVAC component objects with:
        - Type, name, handle
        - Associated thermal zone (if applicable)

        Zone HVAC equipment serves individual zones directly without
        ductwork, e.g., PTACs, fan coil units, baseboards, VRF terminals.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_zone_hvac_equipment()

    @mcp.tool(name="add_air_loop")
    def add_air_loop_tool(name: str, thermal_zone_names: list[str] | None = None):
        """Add a new air loop HVAC system to the loaded OpenStudio model.

        Args:
            name: Name for the new air loop
            thermal_zone_names: Optional list of thermal zone names to serve

        Returns the created air loop object with handle, name, thermal zones,
        and supply components.

        Note: Creates basic air loop with uncontrolled terminals for each zone.
        Additional components (fans, coils, etc.) should be added separately.
        Use save_osm_model_tool to persist changes.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return add_air_loop(name=name, thermal_zone_names=thermal_zone_names)

    @mcp.tool(name="get_plant_loop_details")
    def get_plant_loop_details_tool(plant_loop_name: str):
        """Get detailed information about a specific plant loop.

        NEW in Phase 4D for component validation testing.

        Args:
            plant_loop_name: Name of the plant loop to retrieve

        Returns detailed plant loop attributes including:
        - Loop type (Heating/Cooling)
        - Supply temperature setpoint (°C)
        - Design loop exit temperature (°C)
        - Loop design temperature difference (°C)
        - Supply and demand components

        Use for validating plant loop setpoints in baseline HVAC systems.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return get_plant_loop_details(plant_loop_name=plant_loop_name)

    @mcp.tool(name="get_zone_hvac_details")
    def get_zone_hvac_details_tool(equipment_name: str):
        """Get detailed information about specific zone HVAC equipment.

        NEW in Phase 4D for component validation testing.

        Args:
            equipment_name: Name of the zone HVAC equipment to retrieve

        Returns detailed equipment attributes including:
        - Equipment type and thermal zone
        - Heating coil (type, name)
        - Cooling coil (type, name)
        - Supply air fan (type, name)

        Use for validating zone equipment like PTACs, PTHPs, unit heaters.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return get_zone_hvac_details(equipment_name=equipment_name)
