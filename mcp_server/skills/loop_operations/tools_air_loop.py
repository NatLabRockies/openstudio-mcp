"""MCP tool registrations for air-loop supply branches and setpoint managers.

Split out of tools.py (plant / zone equipment) to keep both files under the
~400-line limit. Called from tools.py::register.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp_server.skills.loop_operations import air_loop_supply, setpoint_managers

if TYPE_CHECKING:
    from mcp import FastMCP


def register_air_loop_tools(mcp: FastMCP) -> None:
    """Register add/remove/replace supply-component and setpoint-manager tools."""

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

    @mcp.tool(tags={"hvac"}, name="add_setpoint_manager")
    def add_setpoint_manager_tool(
        spm_type: str,
        name: str,
        air_loop_name: str | None = None,
        plant_loop_name: str | None = None,
        node: str = "supply_outlet",
        after_component: str | None = None,
        schedule_name: str | None = None,
        cooling_schedule_name: str | None = None,
        heating_schedule_name: str | None = None,
        control_zone_name: str | None = None,
        control_variable: str | None = None,
        replace_existing: bool = False,
    ) -> str:
        """Create a setpoint manager on an air loop or plant loop node.

        Placement: node="supply_outlet" (default) | "supply_inlet" | "mixed_air"
        (air loops with an OA system), or after_component=<coil/fan name> for that
        component's outlet node. Tune setpoints/reset curves afterwards with
        set_setpoint_manager_properties.

        spm_type and its required extra arg:
        - SetpointManagerScheduled: schedule_name (optional control_variable, e.g.
          "HumidityRatio"; default Temperature)
        - SetpointManagerScheduledDualSetpoint: cooling_schedule_name + heating_schedule_name
        - SetpointManagerSingleZoneReheat: control_zone_name (zone served by that air loop)
        - SetpointManagerWarmest / SetpointManagerColdest (air loops only),
          SetpointManagerFollowOutdoorAirTemperature, SetpointManagerOutdoorAirReset: none

        A node already holding a setpoint manager with the same control variable is
        refused (the SDK would silently delete the old one); pass replace_existing=True
        to replace it, and the response reports `replaced`.

        Examples:
          add_setpoint_manager("SetpointManagerOutdoorAirReset", "SAT Reset", air_loop_name="VAV 1",
                               replace_existing=True)
          add_setpoint_manager("SetpointManagerScheduled", "HW Setpoint", plant_loop_name="HW Loop",
                               schedule_name="HW Temp Sched")

        Args:
            spm_type: One of the 7 types above
            name: Name for the new setpoint manager (must be unique)
            air_loop_name: Target air loop (exactly one of air_loop_name / plant_loop_name)
            plant_loop_name: Target plant loop
            node: "supply_outlet" | "supply_inlet" | "mixed_air"
            after_component: Place on this supply component's outlet node instead of `node`
            schedule_name: SetpointManagerScheduled setpoint schedule
            cooling_schedule_name: Dual setpoint high (cooling) schedule
            heating_schedule_name: Dual setpoint low (heating) schedule
            control_zone_name: SingleZoneReheat control zone
            control_variable: Scheduled only — "Temperature" (default), "HumidityRatio", ...
            replace_existing: Replace a same-control-variable SPM already on the node

        Returns:
            JSON: name, spm_type, control_variable, loop, loop_type, node_name, replaced,
            setpoint_managers_on_node
        """
        return json.dumps(setpoint_managers.add_setpoint_manager(
            spm_type=spm_type, name=name, air_loop_name=air_loop_name,
            plant_loop_name=plant_loop_name, node=node, after_component=after_component,
            schedule_name=schedule_name, cooling_schedule_name=cooling_schedule_name,
            heating_schedule_name=heating_schedule_name, control_zone_name=control_zone_name,
            control_variable=control_variable, replace_existing=replace_existing,
        ), indent=2)

    @mcp.tool(tags={"hvac"}, name="remove_setpoint_manager")
    def remove_setpoint_manager_tool(name: str) -> str:
        """Delete a setpoint manager by name (any of the 7 supported types).

        Other setpoint managers on the same node are untouched. If the node is a
        loop's supply outlet and no Temperature setpoint manager remains, the
        response carries a warning: EnergyPlus will not simulate that loop until
        add_setpoint_manager puts one back.

        Args:
            name: Exact setpoint manager name (see get_air_loop_details / list_model_objects)

        Returns:
            JSON: removed, spm_type, node_name, remaining_on_node, warnings
        """
        return json.dumps(setpoint_managers.remove_setpoint_manager(name=name), indent=2)
