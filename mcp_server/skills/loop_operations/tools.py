"""MCP tool registrations for loop operations skill."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp_server.skills.loop_operations import operations

if TYPE_CHECKING:
    from mcp import FastMCP


def register(mcp: "FastMCP") -> None:
    """Register loop operations tools with MCP server."""

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
            plant_loop_name, equipment_type, equipment_name, props
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
            plant_loop_name, equipment_name
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
            zone_name, equipment_type, equipment_name, props
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

        Returns:
            JSON with removal result
        """
        return json.dumps(operations.remove_zone_equipment(
            zone_name, equipment_name
        ), indent=2)
