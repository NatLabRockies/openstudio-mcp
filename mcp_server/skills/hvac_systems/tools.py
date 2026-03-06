"""MCP tool registrations for HVAC systems skill."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Union

from mcp_server.skills.hvac_systems import operations

if TYPE_CHECKING:
    from mcp import FastMCP


def _parse_str_list(value: Union[list, str]) -> list[str]:
    """Coerce a JSON-string-encoded list to a Python list.

    Some MCP clients serialize array parameters as JSON strings rather than
    native JSON arrays. This helper handles both cases.
    """
    if isinstance(value, str):
        return json.loads(value)
    return list(value)


def register(mcp: FastMCP) -> None:
    """Register HVAC systems tools with MCP server."""

    @mcp.tool(name="add_baseline_system")
    def add_baseline_system_tool(
        system_type: int,
        thermal_zone_names: Union[list[str], str],
        heating_fuel: str = "NaturalGas",
        cooling_fuel: str = "Electricity",
        economizer: bool = True,
        system_name: str | None = None,
    ) -> str:
        """Add ASHRAE 90.1 Appendix G baseline HVAC system.

        Systems 1-10: PTAC, PTHP, PSZ-AC, PSZ-HP, PkgVAV Reheat/PFP, VAV Reheat/PFP, Gas/Elec UnitHtrs.
        Call list_baseline_systems() to see all options with descriptions.

        Args:
            system_type: ASHRAE baseline system type (1-10). Call list_baseline_systems() to see options.
            thermal_zone_names: List of thermal zone names to serve
            heating_fuel: NaturalGas | Electricity | DistrictHeating
            cooling_fuel: Electricity | DistrictCooling
        """
        result = operations.add_baseline_system(
            system_type=system_type,
            thermal_zone_names=_parse_str_list(thermal_zone_names),
            heating_fuel=heating_fuel,
            cooling_fuel=cooling_fuel,
            economizer=economizer,
            system_name=system_name,
        )
        return json.dumps(result, indent=2)

    @mcp.tool(name="list_baseline_systems")
    def list_baseline_systems_tool() -> str:
        """List all 10 ASHRAE 90.1 Appendix G baseline system types with descriptions and technologies."""
        result = operations.list_baseline_systems()
        return json.dumps(result, indent=2)

    @mcp.tool(name="get_baseline_system_info")
    def get_baseline_system_info_tool(system_type: int) -> str:
        """Get detailed info for a specific ASHRAE baseline system type (1-10)."""
        result = operations.get_baseline_system_info(system_type)
        return json.dumps(result, indent=2)

    @mcp.tool(name="replace_air_terminals")
    def replace_air_terminals_tool(
        air_loop_name: str,
        terminal_type: str,
        terminal_options: dict | None = None,
    ) -> str:
        """Replace all air terminals on an air loop with a new type.

        Args:
            air_loop_name: Name of air loop to modify
            terminal_type: VAV_Reheat | VAV_NoReheat | PFP_Electric | PFP_HotWater | CAV | FourPipeBeam
            terminal_options: Optional dict: min_airflow_fraction (0-1), fan_power_w_per_cfm
        """
        result = operations.replace_air_terminals(
            air_loop_name=air_loop_name,
            terminal_type=terminal_type,
            terminal_options=terminal_options,
        )
        return json.dumps(result, indent=2)

    @mcp.tool(name="replace_zone_terminal")
    def replace_zone_terminal_tool(
        zone_name: str,
        terminal_type: str,
        terminal_options: dict | None = None,
    ) -> str:
        """Replace the air terminal on a single zone (vs replace_air_terminals which does all zones on a loop).

        Args:
            zone_name: Name of the thermal zone to modify
            terminal_type: VAV_Reheat | VAV_NoReheat | PFP_Electric | PFP_HotWater | CAV | FourPipeBeam
            terminal_options: Optional dict: min_airflow_fraction (0-1)
        """
        result = operations.replace_zone_terminal(
            zone_name=zone_name,
            terminal_type=terminal_type,
            terminal_options=terminal_options,
        )
        return json.dumps(result, indent=2)

    @mcp.tool(name="add_doas_system")
    def add_doas_system_tool(
        thermal_zone_names: list[str],
        system_name: str = "DOAS",
        energy_recovery: bool = True,
        sensible_effectiveness: float = 0.75,
        zone_equipment_type: str = "FanCoil",
        heating_fuel: str = "NaturalGas",
        cooling_fuel: str = "Electricity",
    ) -> str:
        """Add Dedicated Outdoor Air System with zone equipment.

        Creates 100% OA ventilation loop with optional ERV, plus zone-level conditioning.
        Plant loops auto-wired with supply equipment.

        Args:
            thermal_zone_names: List of thermal zone names to serve
            energy_recovery: Add energy recovery ventilator (default True)
            sensible_effectiveness: ERV sensible effectiveness 0-1 (default 0.75)
            zone_equipment_type: FanCoil | Radiant | ChilledBeams | FourPipeBeam
            heating_fuel: NaturalGas | Electricity | DistrictHeating
            cooling_fuel: Electricity | DistrictCooling
        """
        result = operations.add_doas_system(
            thermal_zone_names=thermal_zone_names,
            system_name=system_name,
            energy_recovery=energy_recovery,
            sensible_effectiveness=sensible_effectiveness,
            zone_equipment_type=zone_equipment_type,
            heating_fuel=heating_fuel,
            cooling_fuel=cooling_fuel,
        )
        return json.dumps(result, indent=2)

    @mcp.tool(name="add_vrf_system")
    def add_vrf_system_tool(
        thermal_zone_names: list[str],
        system_name: str = "VRF",
        heat_recovery: bool = True,
        outdoor_unit_capacity_w: float | None = None,
    ) -> str:
        """Add VRF multi-zone heat pump system.

        Creates single outdoor unit with individual zone terminals. Heat recovery enables
        simultaneous heating/cooling across zones.

        Args:
            thermal_zone_names: List of thermal zone names to serve (max ~20 per outdoor unit)
            heat_recovery: Enable heat recovery mode (default True)
            outdoor_unit_capacity_w: Capacity in Watts (autosize if None)
        """
        result = operations.add_vrf_system(
            thermal_zone_names=thermal_zone_names,
            system_name=system_name,
            heat_recovery=heat_recovery,
            outdoor_unit_capacity_w=outdoor_unit_capacity_w,
        )
        return json.dumps(result, indent=2)

    @mcp.tool(name="add_radiant_system")
    def add_radiant_system_tool(
        thermal_zone_names: list[str],
        system_name: str = "Radiant",
        radiant_type: str = "Floor",
        ventilation_system: str = "DOAS",
        heating_fuel: str = "NaturalGas",
        cooling_fuel: str = "Electricity",
    ) -> str:
        """Add low-temperature radiant heating/cooling system.

        Creates hydronic radiant surfaces with low-temp plant loops (auto-wired).
        Optionally adds DOAS for ventilation.

        Args:
            thermal_zone_names: List of thermal zone names to serve
            radiant_type: Floor | Ceiling | Walls
            ventilation_system: DOAS | None (default DOAS)
            heating_fuel: NaturalGas | Electricity | DistrictHeating
            cooling_fuel: Electricity | DistrictCooling
        """
        result = operations.add_radiant_system(
            thermal_zone_names=thermal_zone_names,
            system_name=system_name,
            radiant_type=radiant_type,
            ventilation_system=ventilation_system,
            heating_fuel=heating_fuel,
            cooling_fuel=cooling_fuel,
        )
        return json.dumps(result, indent=2)
