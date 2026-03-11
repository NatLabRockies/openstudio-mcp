"""MCP tool registrations for loop operations skill."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp_server.skills.loop_operations import operations

if TYPE_CHECKING:
    from mcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register loop operations tools with MCP server."""

    @mcp.tool(name="create_plant_loop")
    def create_plant_loop_tool(
        name: str,
        loop_type: str,
        design_exit_temp_c: float | None = None,
        design_delta_temp_c: float | None = None,
        supply_pump_type: str = "variable",
        pump_head_pa: float = 179352.0,
        pump_motor_eff: float = 0.9,
    ) -> str:
        """Create a new plant loop with pump, bypass pipes, and setpoint manager.

        Args:
            name: Name for the plant loop
            loop_type: "Cooling" or "Heating"
            design_exit_temp_c: Loop exit temp (C). Default 7.2 cooling / 82.0 heating.
            design_delta_temp_c: Loop delta-T (C). Default 6.7 cooling / 11.0 heating.
            supply_pump_type: "variable" or "constant" (default "variable")
            pump_head_pa: Pump head in Pa (default 179352)
            pump_motor_eff: Pump motor efficiency 0-1 (default 0.9)
        """
        return json.dumps(operations.create_plant_loop(
            name=name,
            loop_type=loop_type,
            design_exit_temp_c=design_exit_temp_c,
            design_delta_temp_c=design_delta_temp_c,
            supply_pump_type=supply_pump_type,
            pump_head_pa=pump_head_pa,
            pump_motor_eff=pump_motor_eff,
        ), indent=2)

    @mcp.tool(name="add_demand_component")
    def add_demand_component_tool(
        component_name: str,
        plant_loop_name: str,
    ) -> str:
        """Add an existing component (coil, water heater, etc.) to a plant loop's demand side.

        Args:
            component_name: Name of the existing component
            plant_loop_name: Name of the plant loop
        """
        return json.dumps(operations.add_demand_component(
            component_name, plant_loop_name,
        ), indent=2)

    @mcp.tool(name="remove_demand_component")
    def remove_demand_component_tool(
        component_name: str,
        plant_loop_name: str,
    ) -> str:
        """Remove a component from a plant loop's demand side.

        Args:
            component_name: Name of the component to remove
            plant_loop_name: Name of the plant loop
        """
        return json.dumps(operations.remove_demand_component(
            component_name, plant_loop_name,
        ), indent=2)

    @mcp.tool(name="add_supply_equipment")
    def add_supply_equipment_tool(
        plant_loop_name: str,
        equipment_type: str,
        equipment_name: str,
        properties: str | None = None,
    ) -> str:
        """Create equipment and add to a plant loop's supply side.

        Supported types:
        - BoilerHotWater: props — nominal_thermal_efficiency, fuel_type, nominal_capacity_w
        - ChillerElectricEIR: props — reference_cop, reference_capacity_w
        - CoolingTowerSingleSpeed: no extra props

        Args:
            plant_loop_name: Name of the plant loop
            equipment_type: One of the supported equipment types
            equipment_name: Name for the new equipment
            properties: Optional JSON string of property: value pairs

        Returns:
            JSON with creation result
        """
        props = None
        if properties:
            try:
                props = json.loads(properties) if isinstance(properties, str) else properties
            except json.JSONDecodeError as e:
                return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        return json.dumps(operations.add_supply_equipment(
            plant_loop_name, equipment_type, equipment_name, props,
        ), indent=2)

    @mcp.tool(name="remove_supply_equipment")
    def remove_supply_equipment_tool(
        plant_loop_name: str,
        equipment_name: str,
    ) -> str:
        """Remove named equipment from a plant loop's supply side.

        Args:
            plant_loop_name: Name of the plant loop
            equipment_name: Exact name of the equipment to remove

        Returns:
            JSON with removal result
        """
        return json.dumps(operations.remove_supply_equipment(
            plant_loop_name, equipment_name,
        ), indent=2)

    @mcp.tool(name="add_zone_equipment")
    def add_zone_equipment_tool(
        zone_name: str,
        equipment_type: str,
        equipment_name: str,
        properties: str | None = None,
    ) -> str:
        """Create zone-level equipment and add to a thermal zone.

        Supported types:
        - ZoneHVACBaseboardConvectiveElectric: props — nominal_capacity_w
        - ZoneHVACUnitHeater: creates with fan + electric heating coil

        Args:
            zone_name: Name of the thermal zone
            equipment_type: One of the supported equipment types
            equipment_name: Name for the new equipment
            properties: Optional JSON string of property: value pairs

        Returns:
            JSON with creation result
        """
        props = None
        if properties:
            try:
                props = json.loads(properties) if isinstance(properties, str) else properties
            except json.JSONDecodeError as e:
                return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        return json.dumps(operations.add_zone_equipment(
            zone_name, equipment_type, equipment_name, props,
        ), indent=2)

    @mcp.tool(name="remove_zone_equipment")
    def remove_zone_equipment_tool(
        zone_name: str,
        equipment_name: str,
    ) -> str:
        """Remove named equipment from a thermal zone.

        Args:
            zone_name: Name of the thermal zone
            equipment_name: Exact name of the equipment to remove
        """
        return json.dumps(operations.remove_zone_equipment(
            zone_name, equipment_name,
        ), indent=2)

    @mcp.tool(name="remove_all_zone_equipment")
    def remove_all_zone_equipment_tool(zone_names: str) -> str:
        """Remove ALL equipment from multiple thermal zones in one call.

        Use instead of calling remove_zone_equipment repeatedly.

        Args:
            zone_names: JSON array of zone names, e.g. '["Zone1", "Zone2"]'
        """
        try:
            names = json.loads(zone_names) if isinstance(zone_names, str) else zone_names
            if not isinstance(names, list):
                return json.dumps({"ok": False, "error": "zone_names must be a JSON array of strings"})
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        return json.dumps(operations.remove_all_zone_equipment(names), indent=2)
