"""MCP tool registrations for HVAC systems skill."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp_server.skills.hvac_systems import operations

if TYPE_CHECKING:
    from mcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register HVAC systems tools with MCP server."""

    @mcp.tool(name="add_baseline_system")
    def add_baseline_system_tool(
        system_type: int,
        thermal_zone_names: list[str],
        heating_fuel: str = "NaturalGas",
        cooling_fuel: str = "Electricity",
        economizer: bool = True,
        system_name: str | None = None,
    ) -> str:
        """Add ASHRAE 90.1 Appendix G baseline HVAC system to the model.

        Creates complete HVAC system based on ASHRAE 90.1 baseline system types.
        All 10 ASHRAE 90.1 Appendix G baseline systems supported:
        - System 1: PTAC (Packaged Terminal Air Conditioner)
        - System 2: PTHP (Packaged Terminal Heat Pump)
        - System 3: PSZ-AC (Packaged Single Zone Air Conditioner)
        - System 4: PSZ-HP (Packaged Single Zone Heat Pump)
        - System 5: Packaged VAV w/ Reheat
        - System 6: Packaged VAV w/ PFP Boxes
        - System 7: VAV w/ Reheat (Chiller/Boiler/Tower)
        - System 8: VAV w/ PFP (Chiller/Boiler/Tower)
        - System 9: Heating & Ventilation (Gas Unit Heaters)
        - System 10: Heating & Ventilation (Electric Unit Heaters)

        Args:
            system_type: ASHRAE baseline system type (1-10)
            thermal_zone_names: List of thermal zone names to serve
            heating_fuel: "NaturalGas", "Electricity", or "DistrictHeating"
            cooling_fuel: "Electricity" or "DistrictCooling"
            economizer: Enable air-side economizer where applicable
            system_name: Optional custom system name (auto-generated if None)

        Returns:
            JSON string with system details or error
        """
        result = operations.add_baseline_system(
            system_type=system_type,
            thermal_zone_names=thermal_zone_names,
            heating_fuel=heating_fuel,
            cooling_fuel=cooling_fuel,
            economizer=economizer,
            system_name=system_name,
        )
        return json.dumps(result, indent=2)

    @mcp.tool(name="list_baseline_systems")
    def list_baseline_systems_tool() -> str:
        """List all ASHRAE 90.1 Appendix G baseline system types.

        Returns information about all 10 baseline system types including:
        - System name and full name
        - Description
        - Heating/cooling technologies
        - Typical applications

        Returns:
            JSON string with baseline systems catalog
        """
        result = operations.list_baseline_systems()
        return json.dumps(result, indent=2)

    @mcp.tool(name="get_baseline_system_info")
    def get_baseline_system_info_tool(system_type: int) -> str:
        """Get detailed information about a specific ASHRAE baseline system type.

        Args:
            system_type: ASHRAE baseline system type (1-10)

        Returns:
            JSON string with system metadata including typical use cases,
            heating/cooling types, and distribution methods
        """
        result = operations.get_baseline_system_info(system_type)
        return json.dumps(result, indent=2)

    @mcp.tool(name="replace_air_terminals")
    def replace_air_terminals_tool(
        air_loop_name: str,
        terminal_type: str,
        terminal_options: dict | None = None,
    ) -> str:
        """Replace air terminals on an existing air loop.

        Removes existing terminals and installs new type on all zones served by the air loop.
        Useful for converting VAV reheat to PFP boxes, or changing terminal configurations.

        Args:
            air_loop_name: Name of air loop to modify
            terminal_type: Type of terminals to install. Options:
                - "VAV_Reheat": VAV with hot water reheat coils (requires HW loop)
                - "VAV_NoReheat": VAV without reheat
                - "PFP_Electric": Parallel fan-powered with electric reheat
                - "PFP_HotWater": Parallel fan-powered with HW reheat (requires HW loop)
                - "CAV": Constant air volume (uncontrolled)
            terminal_options: Optional configuration dict with keys:
                - min_airflow_fraction: 0.0-1.0 (default: 0.3 for VAV, 0.5 for PFP)
                - fan_power_w_per_cfm: Power for PFP fan boxes (optional)

        Returns:
            JSON string with replacement results including number of terminals replaced,
            old/new terminal types, and affected zones
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
        """Replace the air terminal on a single zone.

        Unlike replace_air_terminals_tool which replaces ALL terminals on an air loop,
        this tool replaces only one zone's terminal. Enables mixed terminal types on
        the same air loop (e.g., VAV reheat for perimeter, VAV no-reheat for core).

        Args:
            zone_name: Name of the thermal zone to modify
            terminal_type: Type of terminal to install. Options:
                - "VAV_Reheat": VAV with hot water reheat coils (requires HW loop)
                - "VAV_NoReheat": VAV without reheat
                - "PFP_Electric": Parallel fan-powered with electric reheat
                - "PFP_HotWater": Parallel fan-powered with HW reheat (requires HW loop)
                - "CAV": Constant air volume (uncontrolled)
            terminal_options: Optional configuration dict with keys:
                - min_airflow_fraction: 0.0-1.0 (default: 0.3 for VAV, 0.5 for PFP)

        Returns:
            JSON string with zone name, air loop, old/new terminal types
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
    ) -> str:
        """Add Dedicated Outdoor Air System with zone equipment.

        Creates 100% outdoor air ventilation loop with optional energy recovery,
        plus zone-level sensible conditioning (fan coils, radiant panels, or chilled beams).

        DOAS decouples ventilation from sensible load, enabling:
        - Lower airflow rates (ventilation-only CFM vs cooling CFM)
        - Energy recovery from exhaust air
        - Independent control of humidity and temperature

        Args:
            thermal_zone_names: List of thermal zone names to serve
            system_name: Name prefix for DOAS components (default "DOAS")
            energy_recovery: Add energy recovery ventilator (default True)
            sensible_effectiveness: ERV sensible effectiveness 0-1 (default 0.75)
            zone_equipment_type: FanCoil | Radiant | Chiller_Beams (default FanCoil)

        Returns:
            JSON string with system details including DOAS loop, plant loops, and zone equipment

        Example:
            {
              "ok": true,
              "system": {
                "name": "DOAS",
                "type": "DOAS",
                "doas_loop": "DOAS DOAS Loop",
                "energy_recovery": true,
                "erv_name": "DOAS ERV",
                "sensible_effectiveness": 0.75,
                "zone_equipment_type": "FanCoil",
                "chilled_water_loop": "DOAS CHW Loop",
                "hot_water_loop": "DOAS HW Loop",
                "num_zones": 4,
                "zone_equipment": [...]
              }
            }
        """
        result = operations.add_doas_system(
            thermal_zone_names=thermal_zone_names,
            system_name=system_name,
            energy_recovery=energy_recovery,
            sensible_effectiveness=sensible_effectiveness,
            zone_equipment_type=zone_equipment_type,
        )
        return json.dumps(result, indent=2)

    @mcp.tool(name="add_vrf_system")
    def add_vrf_system_tool(
        thermal_zone_names: list[str],
        system_name: str = "VRF",
        heat_recovery: bool = True,
        outdoor_unit_capacity_w: float | None = None,
    ) -> str:
        """Add Variable Refrigerant Flow multi-zone heat pump system.

        Creates single outdoor unit with individual zone terminals. Heat recovery mode
        allows simultaneous heating/cooling across zones with heat transfer via refrigerant.

        VRF advantages:
        - High efficiency (COP 3-5 typical)
        - Zonal control (independent setpoints per zone)
        - Heat recovery between zones
        - No ductwork or plant loops required

        Args:
            thermal_zone_names: List of thermal zone names to serve (max ~20 per outdoor unit)
            system_name: Name prefix for VRF components (default "VRF")
            heat_recovery: Enable heat recovery mode (default True)
            outdoor_unit_capacity_w: Outdoor unit capacity in Watts (autosize if None)

        Returns:
            JSON string with system details including outdoor unit and terminals

        Example:
            {
              "ok": true,
              "system": {
                "name": "VRF",
                "type": "VRF",
                "outdoor_unit": "VRF VRF Outdoor Unit HR",
                "heat_recovery": true,
                "capacity_w": "autosized",
                "num_zones": 8,
                "terminals": [...]
              }
            }
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
    ) -> str:
        """Add low-temperature radiant heating/cooling system.

        Creates hydronic radiant surfaces (floor, ceiling, or walls) with low-temperature
        plant loops. Optionally adds DOAS for ventilation/dehumidification.

        Radiant advantages:
        - High thermal comfort (radiant heat transfer)
        - Energy efficiency (low-temp heating, high-temp cooling)
        - Silent operation (no fans in zones)
        - Aesthetic (hidden distribution)

        Considerations:
        - Slow response time (thermal mass)
        - Requires ventilation system (DOAS recommended)
        - Floor coverings affect performance

        Args:
            thermal_zone_names: List of thermal zone names to serve
            system_name: Name prefix for radiant components (default "Radiant")
            radiant_type: Floor | Ceiling | Walls (default Floor)
            ventilation_system: DOAS | None (default DOAS, if None ventilation added separately)

        Returns:
            JSON string with system details including radiant surfaces and plant loops

        Example:
            {
              "ok": true,
              "system": {
                "name": "Radiant",
                "type": "Radiant",
                "radiant_type": "Floor",
                "hot_water_loop": "Radiant Low-Temp HW Loop",
                "chilled_water_loop": "Radiant Low-Temp CHW Loop",
                "hw_supply_temp_f": 120,
                "chw_supply_temp_f": 58,
                "ventilation_system": "DOAS",
                "doas_loop": "Radiant Ventilation DOAS Loop",
                "num_zones": 6,
                "radiant_equipment": [...]
              }
            }
        """
        result = operations.add_radiant_system(
            thermal_zone_names=thermal_zone_names,
            system_name=system_name,
            radiant_type=radiant_type,
            ventilation_system=ventilation_system,
        )
        return json.dumps(result, indent=2)
