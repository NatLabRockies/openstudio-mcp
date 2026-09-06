"""MCP tool registrations for loop operations skill."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp_server.osm_helpers import parse_str_list
from mcp_server.skills.loop_operations import air_loop_supply, operations

if TYPE_CHECKING:
    from mcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register loop operations tools with MCP server."""

    @mcp.tool(tags={"hvac"}, name="create_plant_loop")
    def create_plant_loop_tool(
        name: str,
        loop_type: str,
        design_exit_temp_c: float | None = None,
        design_delta_temp_c: float | None = None,
        supply_pump_type: str = "variable",
        pump_head_pa: float = 179352.0,
        pump_motor_eff: float = 0.9,
    ) -> str:
        """Create a new plant loop (hot water, chilled water, condenser) with pump, bypass, and setpoint manager.

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

    @mcp.tool(tags={"hvac"}, name="add_demand_component")
    def add_demand_component_tool(
        component_name: str,
        plant_loop_name: str,
    ) -> str:
        """Add existing coil or heat exchanger to a plant loop's demand side.

        Args:
            component_name: Name of the existing component
            plant_loop_name: Name of the plant loop
        """
        return json.dumps(operations.add_demand_component(
            component_name, plant_loop_name,
        ), indent=2)

    @mcp.tool(tags={"hvac"}, name="remove_demand_component")
    def remove_demand_component_tool(
        component_name: str,
        plant_loop_name: str,
    ) -> str:
        """Remove coil or other component from a plant loop's demand side.

        Args:
            component_name: Name of the component to remove
            plant_loop_name: Name of the plant loop
        """
        return json.dumps(operations.remove_demand_component(
            component_name, plant_loop_name,
        ), indent=2)

    @mcp.tool(tags={"hvac"}, name="add_supply_equipment")
    def add_supply_equipment_tool(
        plant_loop_name: str,
        equipment_type: str,
        equipment_name: str,
        properties: str | None = None,
    ) -> str:
        """Create boiler, chiller, cooling tower, heat pump, or pump and add to plant loop supply side.

        Plant loops only (parallel supply branches). For coils and fans on an
        AIR loop's supply branch use add_air_loop_supply_component.

        Supported types:
        - BoilerHotWater: props -- nominal_thermal_efficiency, fuel_type, nominal_capacity_w
        - ChillerElectricEIR: props -- reference_cop, reference_capacity_w
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

    @mcp.tool(tags={"hvac"}, name="remove_supply_equipment")
    def remove_supply_equipment_tool(
        plant_loop_name: str,
        equipment_name: str,
    ) -> str:
        """Remove boiler, chiller, or other equipment from a plant loop's supply side.

        Plant loops only. For coils and fans on an AIR loop's supply branch use
        remove_air_loop_supply_component (keeps setpoint managers).

        Args:
            plant_loop_name: Name of the plant loop
            equipment_name: Exact name of the equipment to remove

        Returns:
            JSON with removal result
        """
        return json.dumps(operations.remove_supply_equipment(
            plant_loop_name, equipment_name,
        ), indent=2)

    @mcp.tool(tags={"hvac"}, name="add_air_loop_supply_component")
    def add_air_loop_supply_component_tool(
        air_loop_name: str,
        component_type: str,
        component_name: str,
        insert_before: str | None = None,
        insert_after: str | None = None,
        plant_loop_name: str | None = None,
    ) -> str:
        """Create a coil or fan and put it on an existing air loop's supply branch.

        Appends at the downstream end (just before the supply outlet node) unless
        insert_before / insert_after names an existing coil or fan on the loop.
        Tune the new component afterwards with set_component_properties.

        Supported component_type: FanConstantVolume, FanVariableVolume, FanOnOff,
        CoilHeatingElectric, CoilHeatingGas, CoilHeatingWater, CoilHeatingDXSingleSpeed,
        CoilCoolingDXSingleSpeed, CoilCoolingDXTwoSpeed, CoilCoolingWater.
        Water coils need plant_loop_name (joined to that loop's demand side first).

        Examples:
          add_air_loop_supply_component("VAV 1", "CoilHeatingWater", "Preheat Coil",
                                        insert_before="VAV 1 Cooling Coil", plant_loop_name="HW Loop")
          add_air_loop_supply_component("PSZ 1", "CoilHeatingElectric", "Reheat Booster")

        Args:
            air_loop_name: Existing AirLoopHVAC name (see list_air_loops)
            component_type: One of the supported types above
            component_name: Name for the new component (must not already be on the loop)
            insert_before: Put the new component immediately upstream of this component
            insert_after: Put the new component immediately downstream of this component
            plant_loop_name: Required for CoilHeatingWater / CoilCoolingWater

        Returns:
            JSON: air_loop, component_name, component_type, plant_loop, supply_order
            (full ordered list of {name, type} on the supply branch)
        """
        return json.dumps(air_loop_supply.add_air_loop_supply_component(
            air_loop_name=air_loop_name, component_type=component_type,
            component_name=component_name, insert_before=insert_before,
            insert_after=insert_after, plant_loop_name=plant_loop_name,
        ), indent=2)

    @mcp.tool(tags={"hvac"}, name="remove_air_loop_supply_component")
    def remove_air_loop_supply_component_tool(
        air_loop_name: str,
        component_name: str,
    ) -> str:
        """Remove a coil or fan from an air loop's supply branch.

        Safer than delete_object: checks the component is on THIS loop, and keeps
        any setpoint manager that sat on the node the removal deletes by moving it
        to the surviving neighbour node (reported in moved_setpoint_managers; a
        same-control-variable collision leaves it behind and is reported in
        dropped_setpoint_managers + warnings). Water coils leave their plant loop
        automatically. Outdoor air systems and terminals are refused.

        Args:
            air_loop_name: Existing AirLoopHVAC name
            component_name: Exact name of the coil or fan on that loop's supply side

        Returns:
            JSON: removed {name, type}, moved_setpoint_managers,
            dropped_setpoint_managers, supply_order
        """
        return json.dumps(air_loop_supply.remove_air_loop_supply_component(
            air_loop_name=air_loop_name, component_name=component_name,
        ), indent=2)

    @mcp.tool(tags={"hvac"}, name="replace_air_loop_supply_component")
    def replace_air_loop_supply_component_tool(
        air_loop_name: str,
        component_name: str,
        new_component_type: str,
        new_component_name: str | None = None,
        plant_loop_name: str | None = None,
    ) -> str:
        """Swap a coil or fan on an air loop's supply branch for a new type, in place.

        Keeps the branch position and, by default, the old name (so downstream
        references and reports still resolve). A water-coil-for-water-coil swap
        reuses the old coil's plant loop unless plant_loop_name says otherwise;
        DX-to-water needs plant_loop_name. Setpoint managers on the old
        component's outlet node move to the new component's outlet node.
        Prefer this over a hand-written measure for simple swaps: it performs
        the add-first / remove-second sequence that avoids the SDK segfault
        (search_wiring_patterns("replace coil") explains).

        Examples:
          replace_air_loop_supply_component("PSZ 1", "PSZ 1 DX Cooling Coil", "CoilCoolingDXTwoSpeed")
          replace_air_loop_supply_component("PSZ 1", "PSZ 1 Supply Fan", "FanVariableVolume",
                                            new_component_name="VAV Fan")

        Args:
            air_loop_name: Existing AirLoopHVAC name
            component_name: Exact name of the coil or fan to replace
            new_component_type: One of the types add_air_loop_supply_component supports
            new_component_name: Name for the replacement (default: reuse the old name)
            plant_loop_name: Plant loop for a new water coil (default: inherit from the old coil)

        Returns:
            JSON: removed {name, type}, added {name, type}, plant_loop,
            moved_setpoint_managers, dropped_setpoint_managers, supply_order
        """
        return json.dumps(air_loop_supply.replace_air_loop_supply_component(
            air_loop_name=air_loop_name, component_name=component_name,
            new_component_type=new_component_type, new_component_name=new_component_name,
            plant_loop_name=plant_loop_name,
        ), indent=2)

    @mcp.tool(tags={"hvac"}, name="add_zone_equipment")
    def add_zone_equipment_tool(
        zone_name: str,
        equipment_type: str,
        equipment_name: str,
        properties: str | None = None,
    ) -> str:
        """Add baseboard, unit heater, fan coil, PTAC, PTHP, or radiant panel to a thermal zone.

        Supported types:
        - ZoneHVACBaseboardConvectiveElectric: props -- nominal_capacity_w
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

    @mcp.tool(tags={"hvac"}, name="remove_zone_equipment")
    def remove_zone_equipment_tool(
        zone_name: str,
        equipment_name: str,
    ) -> str:
        """Remove heating or cooling equipment from a thermal zone.

        Args:
            zone_name: Name of the thermal zone
            equipment_name: Exact name of the equipment to remove
        """
        return json.dumps(operations.remove_zone_equipment(
            zone_name, equipment_name,
        ), indent=2)

    @mcp.tool(tags={"hvac"}, name="set_zone_equipment_priority")
    def set_zone_equipment_priority_tool(
        zone_name: str,
        equipment_names: list[str] | str,
    ) -> str:
        """Set heating and cooling priority order for zone HVAC equipment (1 = highest, served first).
        EnergyPlus simulates zone equipment in priority order -- ensures primary equipment
        (e.g., chilled beams) is served before secondary (e.g., fan coils).

        Args:
            zone_name: Thermal zone name
            equipment_names: Equipment names in desired priority order (highest first).
                            Must include ALL equipment on the zone.
        """
        return json.dumps(operations.set_zone_equipment_priority(
            zone_name=zone_name,
            equipment_names=parse_str_list(equipment_names),
        ), indent=2)

    @mcp.tool(tags={"hvac"}, name="remove_all_zone_equipment")
    def remove_all_zone_equipment_tool(zone_names: str) -> str:
        """Batch clear all HVAC equipment from multiple thermal zones in one call.
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
