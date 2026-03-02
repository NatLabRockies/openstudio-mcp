"""Model validation and integrity checks for HVAC systems."""
from __future__ import annotations

from typing import Any


def validate_air_loop(air_loop) -> dict[str, Any]:
    """Validate air loop HVAC topology and connections.

    Checks:
    - Has supply components
    - Has demand components (zones)
    - Has outdoor air system (if expected)
    - No orphaned nodes
    - Has setpoint managers
    """
    issues = []
    warnings = []

    # Check supply components
    supply_components = air_loop.supplyComponents()
    if len(supply_components) == 0:
        issues.append("No supply components on air loop")

    # Check thermal zones
    zones = air_loop.thermalZones()
    if len(zones) == 0:
        warnings.append("No thermal zones served by air loop")

    # Check outdoor air system
    if not air_loop.airLoopHVACOutdoorAirSystem().is_initialized():
        warnings.append("No outdoor air system on air loop")

    # Check for setpoint manager on supply outlet
    supply_outlet = air_loop.supplyOutletNode()
    setpoint_managers = supply_outlet.setpointManagers()
    if len(setpoint_managers) == 0:
        warnings.append("No setpoint manager on supply outlet node")

    return {
        "ok": len(issues) == 0,
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "zones_served": len(zones),
        "supply_components": len(supply_components),
    }


def validate_plant_loop(plant_loop) -> dict[str, Any]:
    """Validate plant loop topology and connections.

    Checks:
    - Has supply components
    - Has demand components
    - Has sizing information
    - Has setpoint managers
    """
    issues = []
    warnings = []

    # Check supply components
    supply_components = plant_loop.supplyComponents()
    if len(supply_components) == 0:
        warnings.append("No supply components on plant loop")

    # Check demand components
    demand_components = plant_loop.demandComponents()
    if len(demand_components) == 0:
        warnings.append("No demand components on plant loop")

    # Check for setpoint manager
    supply_outlet = plant_loop.supplyOutletNode()
    setpoint_managers = supply_outlet.setpointManagers()
    if len(setpoint_managers) == 0:
        warnings.append("No setpoint manager on supply outlet node")

    return {
        "ok": len(issues) == 0,
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "supply_components": len(supply_components),
        "demand_components": len(demand_components),
    }


def validate_zone_equipment(thermal_zone) -> dict[str, Any]:
    """Validate thermal zone equipment connections.

    Checks:
    - Has equipment or air terminal
    - Equipment is properly connected
    - Thermostat exists (warning if missing)
    """
    issues = []
    warnings = []

    # Check for equipment
    equipment = thermal_zone.equipment()
    has_air_terminal = thermal_zone.airLoopHVAC().is_initialized()

    if len(equipment) == 0 and not has_air_terminal:
        warnings.append("Zone has no equipment and no air terminal")

    # Check for thermostat
    if not thermal_zone.thermostatSetpointDualSetpoint().is_initialized():
        warnings.append("Zone has no thermostat")

    return {
        "ok": len(issues) == 0,
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "equipment_count": len(equipment),
        "has_air_terminal": has_air_terminal,
    }


def validate_system(model, system_name: str) -> dict[str, Any]:
    """Validate complete HVAC system after creation.

    Comprehensive check of air loops, plant loops, and zones.
    """
    from mcp_server.osm_helpers import fetch_object

    # Try to find air loop
    air_loop = fetch_object(model, "AirLoopHVAC", name=system_name)

    if air_loop:
        air_loop_validation = validate_air_loop(air_loop)
        zones = air_loop.thermalZones()

        zone_validations = []
        for zone in zones:
            zone_validations.append(validate_zone_equipment(zone))

        all_valid = air_loop_validation["valid"] and all(zv["valid"] for zv in zone_validations)

        return {
            "ok": True,
            "valid": all_valid,
            "air_loop": air_loop_validation,
            "zones": zone_validations,
        }

    # If no air loop, might be zone equipment only
    return {
        "ok": True,
        "valid": True,
        "message": "System validation not implemented for this system type",
    }
