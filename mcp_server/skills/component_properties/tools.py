"""MCP tool registrations for component properties skill."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp_server.skills.component_properties import operations

if TYPE_CHECKING:
    from mcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register component properties tools with MCP server."""

    @mcp.tool(name="list_hvac_components")
    def list_hvac_components_tool(category: str | None = None) -> str:
        """List all HVAC components in the model with name, type, and category.

        Args:
            category: Optional filter — "coil", "plant", "fan", or "pump"
        """
        return json.dumps(operations.list_hvac_components(category), indent=2)

    @mcp.tool(name="get_component_properties")
    def get_component_properties_tool(component_name: str) -> str:
        """Get all readable properties for a named HVAC component.

        Args:
            component_name: Exact name of the HVAC component
        """
        return json.dumps(operations.get_component_properties(component_name), indent=2)

    @mcp.tool(name="set_component_properties")
    def set_component_properties_tool(component_name: str, properties: str) -> str:
        """Set one or more properties on a named HVAC component.

        Args:
            component_name: Exact name of the HVAC component
            properties: JSON string of property_name: value pairs,
                e.g. '{"reference_cop": 6.0, "nominal_capacity_w": 50000}'
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
        """
        try:
            props = json.loads(properties) if isinstance(properties, str) else properties
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        return json.dumps(operations.set_sizing_properties(loop_name, props), indent=2)

    @mcp.tool(name="set_sizing_system_properties")
    def set_sizing_system_properties_tool(air_loop_name: str, properties: str) -> str:
        """Set SizingSystem properties on an air loop.

        Properties: type_of_load_to_size_on, central_cooling/heating_design_supply_air_temperature,
        central_cooling/heating_design_supply_air_humidity_ratio, all_outdoor_air_in_cooling/heating,
        preheat/precool_design_temperature, sizing_option, cooling/heating_design_air_flow_method.

        Args:
            air_loop_name: Name of the air loop
            properties: JSON string of property: value pairs
        """
        try:
            props = json.loads(properties) if isinstance(properties, str) else properties
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        return json.dumps(operations.set_sizing_system_properties(air_loop_name, props), indent=2)

    @mcp.tool(name="get_sizing_system_properties")
    def get_sizing_system_properties_tool(air_loop_name: str) -> str:
        """Get all SizingSystem properties for an air loop.

        Args:
            air_loop_name: Name of the air loop
        """
        return json.dumps(operations.get_sizing_system_properties(air_loop_name), indent=2)

    @mcp.tool(name="set_sizing_zone_properties")
    def set_sizing_zone_properties_tool(zone_names: str, properties: str) -> str:
        """Set SizingZone properties on one or more thermal zones.

        Properties: zone_cooling/heating_design_supply_air_temperature,
        zone_cooling/heating_sizing_factor, cooling_design_air_flow_method,
        cooling_minimum_air_flow_fraction, account_for_dedicated_outdoor_air_system,
        dedicated_outdoor_air_system_control_strategy, dedicated_outdoor_air_low/high_setpoint_temp.

        Args:
            zone_names: Zone name or JSON array of zone names
            properties: JSON string of property: value pairs
        """
        try:
            props = json.loads(properties) if isinstance(properties, str) else properties
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        try:
            if isinstance(zone_names, str) and zone_names.startswith("["):
                names = json.loads(zone_names)
            else:
                names = [zone_names]
        except json.JSONDecodeError:
            names = [zone_names]
        return json.dumps(operations.set_sizing_zone_properties(names, props), indent=2)

    @mcp.tool(name="get_sizing_zone_properties")
    def get_sizing_zone_properties_tool(zone_name: str) -> str:
        """Get all SizingZone properties for a thermal zone.

        Args:
            zone_name: Name of the thermal zone
        """
        return json.dumps(operations.get_sizing_zone_properties(zone_name), indent=2)

    @mcp.tool(name="get_setpoint_manager_properties")
    def get_setpoint_manager_properties_tool(setpoint_name: str) -> str:
        """Get all properties for a named setpoint manager.

        Supports: SingleZoneReheat, Scheduled, Warmest, Coldest,
        FollowOutdoorAirTemperature, OutdoorAirReset, ScheduledDualSetpoint.

        Args:
            setpoint_name: Name of the setpoint manager
        """
        return json.dumps(operations.get_setpoint_manager_properties(setpoint_name), indent=2)

    @mcp.tool(name="set_setpoint_manager_properties")
    def set_setpoint_manager_properties_tool(setpoint_name: str, properties: str) -> str:
        """Modify setpoint manager properties.

        Supports 7 SPM types: SingleZoneReheat, Scheduled, Warmest, Coldest,
        FollowOutdoorAirTemperature, OutdoorAirReset, ScheduledDualSetpoint.
        Use get_setpoint_manager_properties to see available properties per type.

        Args:
            setpoint_name: Name of the setpoint manager
            properties: JSON string of property: value pairs
        """
        try:
            props = json.loads(properties) if isinstance(properties, str) else properties
        except json.JSONDecodeError as e:
            return json.dumps({"ok": False, "error": f"Invalid JSON: {e}"})
        return json.dumps(operations.set_setpoint_manager_properties(setpoint_name, props), indent=2)
