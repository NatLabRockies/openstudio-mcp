"""MCP tool registrations for component properties skill."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp_server.skills.component_properties import operations

if TYPE_CHECKING:
    from mcp import FastMCP


def register(mcp: "FastMCP") -> None:
    """Register component properties tools with MCP server."""

    @mcp.tool(name="list_hvac_components")
    def list_hvac_components_tool(category: str | None = None) -> str:
        """List all HVAC components in the model with name, type, and category.

        Scans the model for known component types (coils, chillers, boilers,
        fans, pumps, cooling towers) and returns their names and categories.

        Args:
            category: Optional filter — "coil", "plant", "fan", or "pump"

        Returns:
            JSON with component list
        """
        return json.dumps(operations.list_hvac_components(category), indent=2)

    @mcp.tool(name="get_component_properties")
    def get_component_properties_tool(component_name: str) -> str:
        """Get all readable properties for a named HVAC component.

        Looks up the component by name across all registered types and returns
        current property values with units.

        Args:
            component_name: Exact name of the HVAC component

        Returns:
            JSON with property names, values, units, and types
        """
        return json.dumps(operations.get_component_properties(component_name), indent=2)

    @mcp.tool(name="set_component_properties")
    def set_component_properties_tool(component_name: str, properties: str) -> str:
        """Set one or more properties on a named HVAC component.

        Finds the component by name, validates property names against the
        registry, and applies changes. Returns old and new values.

        Args:
            component_name: Exact name of the HVAC component
            properties: JSON string of property_name: value pairs,
                e.g. '{"reference_cop": 6.0, "nominal_capacity_w": 50000}'

        Returns:
            JSON with old/new values for each changed property
        """
        try:
            props = json.loads(properties) if isinstance(properties, str) else properties
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        return json.dumps(operations.set_component_properties(component_name, props), indent=2)

    # --- 5B: Controls & Setpoints ---

    @mcp.tool(name="set_economizer_properties")
    def set_economizer_properties_tool(air_loop_name: str, properties: str) -> str:
        """Modify outdoor air economizer properties on an air loop.

        Available properties:
        - economizer_control_type: "NoEconomizer", "DifferentialDryBulb",
          "DifferentialEnthalpy", "FixedDryBulb", etc.
        - max_limit_drybulb_temp_c: Maximum OA dry-bulb temperature limit
        - min_limit_drybulb_temp_c: Minimum OA dry-bulb temperature limit

        Args:
            air_loop_name: Name of the air loop
            properties: JSON string of property: value pairs

        Returns:
            JSON with old/new values
        """
        try:
            props = json.loads(properties) if isinstance(properties, str) else properties
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        return json.dumps(operations.set_economizer_properties(air_loop_name, props), indent=2)

    @mcp.tool(name="set_sizing_properties")
    def set_sizing_properties_tool(loop_name: str, properties: str) -> str:
        """Modify sizing properties on a plant loop.

        Available properties:
        - loop_type: "Heating", "Cooling", "Condenser", "Both"
        - design_loop_exit_temperature_c: Design supply water temperature
        - loop_design_temperature_difference_c: Design delta-T

        Args:
            loop_name: Name of the plant loop
            properties: JSON string of property: value pairs

        Returns:
            JSON with old/new values
        """
        try:
            props = json.loads(properties) if isinstance(properties, str) else properties
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        return json.dumps(operations.set_sizing_properties(loop_name, props), indent=2)

    @mcp.tool(name="set_setpoint_manager_properties")
    def set_setpoint_manager_properties_tool(setpoint_name: str, properties: str) -> str:
        """Modify setpoint manager properties.

        Supports SetpointManagerSingleZoneReheat:
        - minimum_supply_air_temperature_c
        - maximum_supply_air_temperature_c

        Supports SetpointManagerScheduled:
        - control_variable: "Temperature", "HumidityRatio", etc.

        Args:
            setpoint_name: Name of the setpoint manager
            properties: JSON string of property: value pairs

        Returns:
            JSON with old/new values
        """
        try:
            props = json.loads(properties) if isinstance(properties, str) else properties
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        return json.dumps(operations.set_setpoint_manager_properties(setpoint_name, props), indent=2)
