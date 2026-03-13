"""Public API for HVAC systems skill."""
from __future__ import annotations

from typing import Any

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object
from mcp_server.skills.hvac_systems import (
    air_terminals,
    baseline,
    catalog,
    templates,
    validation,
)
from mcp_server.stdout_suppression import suppress_openstudio_warnings


def add_baseline_system(
    system_type: int,
    thermal_zone_names: list[str],
    heating_fuel: str = "NaturalGas",
    cooling_fuel: str = "Electricity",
    economizer: bool = True,
    system_name: str | None = None,
) -> dict[str, Any]:
    """Add ASHRAE 90.1 Appendix G baseline HVAC system.

    Args:
        system_type: ASHRAE baseline system type (1-10)
        thermal_zone_names: List of thermal zone names to serve
        heating_fuel: "NaturalGas", "Electricity", or "DistrictHeating"
        cooling_fuel: "Electricity" or "DistrictCooling"
        economizer: Enable air-side economizer (where applicable)
        system_name: Optional custom name (auto-generated if None)

    Returns:
        dict with {"ok": True, "system": {...}} or {"ok": False, "error": "..."}
    """
    try:
        model = get_model()

        # Validate system type
        if system_type not in range(1, 11):
            return {
                "ok": False,
                "error": f"Invalid system_type: {system_type}. Must be 1-10.",
            }

        # Fetch thermal zones
        zones = []
        for zone_name in thermal_zone_names:
            zone = fetch_object(model, "ThermalZone", name=zone_name)
            if zone is None:
                return {
                    "ok": False,
                    "error": f"Thermal zone '{zone_name}' not found",
                }
            zones.append(zone)

        if len(zones) == 0:
            return {
                "ok": False,
                "error": "At least one thermal zone required",
            }

        # Auto-generate name if not provided
        if system_name is None:
            system_info = catalog.get_baseline_system_info(system_type)
            system_name = f"{system_info['system']['name']} HVAC"

        # Route to appropriate baseline system implementation
        # Suppress SWIG stdout warnings that corrupt MCP JSON-RPC stream
        with suppress_openstudio_warnings():
            if system_type == 1:
                result = baseline.create_baseline_system_1(
                    model, zones, heating_fuel, cooling_fuel, economizer, system_name,
                )
            elif system_type == 2:
                result = baseline.create_baseline_system_2(
                    model, zones, heating_fuel, cooling_fuel, economizer, system_name,
                )
            elif system_type == 3:
                result = baseline.create_baseline_system_3(
                    model, zones, heating_fuel, cooling_fuel, economizer, system_name,
                )
            elif system_type == 4:
                result = baseline.create_baseline_system_4(
                    model, zones, heating_fuel, cooling_fuel, economizer, system_name,
                )
            elif system_type == 5:
                result = baseline.create_baseline_system_5(
                    model, zones, heating_fuel, cooling_fuel, economizer, system_name,
                )
            elif system_type == 6:
                result = baseline.create_baseline_system_6(
                    model, zones, heating_fuel, cooling_fuel, economizer, system_name,
                )
            elif system_type == 7:
                result = baseline.create_baseline_system_7(
                    model, zones, heating_fuel, cooling_fuel, economizer, system_name,
                )
            elif system_type == 8:
                result = baseline.create_baseline_system_8(
                    model, zones, heating_fuel, cooling_fuel, economizer, system_name,
                )
            elif system_type == 9:
                result = baseline.create_baseline_system_9(
                    model, zones, heating_fuel, cooling_fuel, economizer, system_name,
                )
            elif system_type == 10:
                result = baseline.create_baseline_system_10(
                    model, zones, heating_fuel, cooling_fuel, economizer, system_name,
                )
            else:
                return {
                    "ok": False,
                    "error": f"System type {system_type} not yet implemented. Currently supporting systems 1-10.",
                }

        # Validate system if creation succeeded
        if result.get("ok"):
            # Enable sizing calculations — all baseline systems use autosizing
            sim_control = model.getSimulationControl()
            sim_control.setDoZoneSizingCalculation(True)
            sim_control.setDoSystemSizingCalculation(True)
            sim_control.setDoPlantSizingCalculation(True)

            validation_result = validation.validate_system(model, system_name)
            result["validation"] = validation_result

        return result

    except RuntimeError as e:
        return {"ok": False, "error": f"Runtime error: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add baseline system: {e}"}


def list_baseline_systems() -> dict[str, Any]:
    """List all supported ASHRAE baseline system types.

    Returns:
        dict with baseline system information
    """
    try:
        return catalog.list_all_templates()
    except Exception as e:
        return {"ok": False, "error": f"Failed to list baseline systems: {e}"}


def get_baseline_system_info(system_type: int) -> dict[str, Any]:
    """Get detailed information about a specific baseline system type.

    Args:
        system_type: ASHRAE baseline system type (1-10)

    Returns:
        dict with system metadata
    """
    try:
        return catalog.get_baseline_system_info(system_type)
    except Exception as e:
        return {"ok": False, "error": f"Failed to get system info: {e}"}


def replace_air_terminals(
    air_loop_name: str,
    terminal_type: str,
    terminal_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replace air terminals on an existing air loop.

    Args:
        air_loop_name: Name of air loop to modify
        terminal_type: Type of terminals to install
        terminal_options: Optional terminal-specific configuration

    Returns:
        dict with replacement results or error
    """
    try:
        model = get_model()

        # Fetch air loop
        air_loop = fetch_object(model, "AirLoopHVAC", name=air_loop_name)
        if air_loop is None:
            return {
                "ok": False,
                "error": f"Air loop '{air_loop_name}' not found",
            }

        # Validate terminal type
        valid_types = [
            "VAV_Reheat", "VAV_NoReheat", "PFP_Electric", "PFP_HotWater",
            "CAV", "FourPipeBeam", "CooledBeam",
        ]
        if terminal_type not in valid_types:
            return {
                "ok": False,
                "error": f"Invalid terminal_type: '{terminal_type}'. Must be one of: {', '.join(valid_types)}",
            }

        # Replace terminals (suppress SWIG stdout warnings)
        with suppress_openstudio_warnings():
            result = air_terminals.replace_terminals(
                model,
                air_loop,
                terminal_type,
                terminal_options or {},
            )

        return result

    except RuntimeError as e:
        return {"ok": False, "error": f"Runtime error: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to replace terminals: {e}"}


def replace_zone_terminal(
    zone_name: str,
    terminal_type: str,
    terminal_options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replace the air terminal on a single zone.

    Args:
        zone_name: Name of the thermal zone
        terminal_type: Type of terminal to install
        terminal_options: Optional terminal-specific configuration

    Returns:
        dict with replacement results or error
    """
    try:
        model = get_model()

        zone = fetch_object(model, "ThermalZone", name=zone_name)
        if zone is None:
            return {"ok": False, "error": f"Thermal zone '{zone_name}' not found"}

        valid_types = [
            "VAV_Reheat", "VAV_NoReheat", "PFP_Electric", "PFP_HotWater",
            "CAV", "FourPipeBeam", "CooledBeam",
        ]
        if terminal_type not in valid_types:
            return {
                "ok": False,
                "error": f"Invalid terminal_type: '{terminal_type}'. Must be one of: {', '.join(valid_types)}",
            }

        with suppress_openstudio_warnings():
            return air_terminals.replace_zone_terminal(
                model, zone, terminal_type, terminal_options or {},
            )

    except RuntimeError as e:
        return {"ok": False, "error": f"Runtime error: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to replace zone terminal: {e}"}


def add_doas_system(
    thermal_zone_names: list[str],
    system_name: str = "DOAS",
    energy_recovery: bool = True,
    sensible_effectiveness: float = 0.75,
    zone_equipment_type: str = "FanCoil",
    heating_fuel: str = "NaturalGas",
    cooling_fuel: str = "Electricity",
) -> dict[str, Any]:
    """Add Dedicated Outdoor Air System with zone equipment.

    Args:
        thermal_zone_names: Zones to serve
        system_name: Name prefix for DOAS components
        energy_recovery: Add ERV (default True)
        sensible_effectiveness: ERV sensible effectiveness 0-1 (default 0.75)
        zone_equipment_type: FanCoil | Radiant | ChilledBeams | FourPipeBeam
        heating_fuel: NaturalGas | Electricity | DistrictHeating
        cooling_fuel: Electricity | DistrictCooling

    Returns:
        dict with ok status and system details
    """
    try:
        model = get_model()

        # Fetch zones
        zones = []
        for zone_name in thermal_zone_names:
            zone = fetch_object(model, "ThermalZone", name=zone_name)
            if zone is None:
                return {"ok": False, "error": f"Thermal zone '{zone_name}' not found"}
            zones.append(zone)

        # Validate zone_equipment_type
        valid_types = ["FanCoil", "Radiant", "ChilledBeams", "FourPipeBeam"]
        if zone_equipment_type not in valid_types:
            return {"ok": False, "error": f"Invalid zone_equipment_type: '{zone_equipment_type}'"}

        # Create DOAS system (suppress SWIG stdout warnings)
        with suppress_openstudio_warnings():
            result = templates.create_doas_system(
                model, zones, system_name, energy_recovery,
                sensible_effectiveness, zone_equipment_type,
                heating_fuel, cooling_fuel,
            )

        return {"ok": True, "system": result}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add DOAS system: {e}"}


def add_vrf_system(
    thermal_zone_names: list[str],
    system_name: str = "VRF",
    heat_recovery: bool = True,
    outdoor_unit_capacity_w: float | None = None,
) -> dict[str, Any]:
    """Add Variable Refrigerant Flow multi-zone heat pump system.

    Args:
        thermal_zone_names: Zones to serve (max ~20 per outdoor unit)
        system_name: Name prefix for VRF components
        heat_recovery: Enable heat recovery mode (default True)
        outdoor_unit_capacity_w: Capacity in Watts (autosize if None)

    Returns:
        dict with ok status and system details
    """
    try:
        model = get_model()

        # Fetch zones
        zones = []
        for zone_name in thermal_zone_names:
            zone = fetch_object(model, "ThermalZone", name=zone_name)
            if zone is None:
                return {"ok": False, "error": f"Thermal zone '{zone_name}' not found"}
            zones.append(zone)

        # Create VRF system (suppress SWIG stdout warnings)
        with suppress_openstudio_warnings():
            result = templates.create_vrf_system(
                model, zones, system_name, heat_recovery, outdoor_unit_capacity_w,
            )

        return {"ok": True, "system": result}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add VRF system: {e}"}


def add_radiant_system(
    thermal_zone_names: list[str],
    system_name: str = "Radiant",
    radiant_type: str = "Floor",
    ventilation_system: str = "DOAS",
    heating_fuel: str = "NaturalGas",
    cooling_fuel: str = "Electricity",
) -> dict[str, Any]:
    """Add low-temperature radiant heating/cooling system.

    Args:
        thermal_zone_names: Zones to serve
        system_name: Name prefix for radiant components
        radiant_type: Floor | Ceiling | Walls
        ventilation_system: DOAS | None (if None, ventilation must be added separately)
        heating_fuel: NaturalGas | Electricity | DistrictHeating
        cooling_fuel: Electricity | DistrictCooling

    Returns:
        dict with ok status and system details
    """
    try:
        model = get_model()

        # Fetch zones
        zones = []
        for zone_name in thermal_zone_names:
            zone = fetch_object(model, "ThermalZone", name=zone_name)
            if zone is None:
                return {"ok": False, "error": f"Thermal zone '{zone_name}' not found"}
            zones.append(zone)

        # Validate radiant_type
        valid_types = ["Floor", "Ceiling", "Walls"]
        if radiant_type not in valid_types:
            return {"ok": False, "error": f"Invalid radiant_type: '{radiant_type}'"}

        # Validate ventilation_system
        valid_vent = ["DOAS", "None"]
        if ventilation_system not in valid_vent:
            return {"ok": False, "error": f"Invalid ventilation_system: '{ventilation_system}'"}

        # Create radiant system (suppress SWIG stdout warnings)
        with suppress_openstudio_warnings():
            result = templates.create_radiant_system(
                model, zones, system_name, radiant_type, ventilation_system,
                heating_fuel, cooling_fuel,
            )

        return {"ok": True, "system": result}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add radiant system: {e}"}
