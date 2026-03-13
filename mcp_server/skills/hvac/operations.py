"""HVAC operations — air loops, plant loops, zone equipment.

Extraction patterns adapted from openstudio-toolkit osm_objects/hvac.py
— using direct openstudio bindings.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import (
    build_list_response,
    fetch_object,
    list_all_as_dicts,
    list_paginated,
    optional_name,
)


def _extract_detailed_supply_components(air_loop) -> dict[str, Any]:
    """Extract detailed supply component information for validation.

    Returns dict with categorized components (fans, coils, etc.) with detailed specs.
    """
    result = {
        "fans": [],
        "heating_coils": [],
        "cooling_coils": [],
        "other": [],
    }

    for component in air_loop.supplyComponents():
        comp_type = component.iddObjectType().valueName()

        # Extract fan details
        if "Fan" in comp_type:
            fan_info = {"type": comp_type, "name": component.nameString() if hasattr(component, "nameString") else "Unnamed"}

            # Try to get fan-specific attributes
            if hasattr(component, "pressureRise") and callable(component.pressureRise):
                fan_info["pressure_rise_pa"] = component.pressureRise()
            if hasattr(component, "motorEfficiency") and callable(component.motorEfficiency):
                fan_info["motor_efficiency"] = component.motorEfficiency()

            result["fans"].append(fan_info)

        # Extract heating coil details
        # valueName() returns e.g. "OS_Coil_Heating_Gas" (underscored)
        elif "Coil_Heating" in comp_type or "CoilHeating" in comp_type:
            coil_info = {"type": comp_type, "name": component.nameString() if hasattr(component, "nameString") else "Unnamed"}

            # Try to get coil-specific attributes
            if hasattr(component, "fuelType") and callable(component.fuelType):
                coil_info["fuel_type"] = component.fuelType()

            result["heating_coils"].append(coil_info)

        # Extract cooling coil details
        elif "Coil_Cooling" in comp_type or "CoilCooling" in comp_type:
            coil_info = {"type": comp_type, "name": component.nameString() if hasattr(component, "nameString") else "Unnamed"}
            result["cooling_coils"].append(coil_info)

        else:
            result["other"].append({"type": comp_type})

    return result


def _extract_outdoor_air_system(air_loop) -> dict[str, Any] | None:
    """Extract outdoor air system details including economizer settings."""
    oa_system_optional = air_loop.airLoopHVACOutdoorAirSystem()

    if not oa_system_optional.is_initialized():
        return None

    oa_system = oa_system_optional.get()

    result = {
        "name": oa_system.nameString(),
        "economizer_enabled": False,
        "economizer_type": "NoEconomizer",
    }

    # Get controller outdoor air
    try:
        controller = oa_system.getControllerOutdoorAir()

        # Get economizer settings
        if hasattr(controller, "getEconomizerControlType"):
            econ_type = controller.getEconomizerControlType()
            result["economizer_type"] = econ_type
            result["economizer_enabled"] = (econ_type != "NoEconomizer")
    except Exception:
        pass  # Controller not available

    return result


def _extract_setpoint_managers(air_loop) -> list[dict[str, Any]]:
    """Extract setpoint manager information from air loop."""
    setpoint_mgrs = []

    # Get setpoint managers on supply outlet node
    outlet_node = air_loop.supplyOutletNode()
    for spm in outlet_node.setpointManagers():
        spm_info = {
            "type": spm.iddObjectType().valueName(),
            "name": spm.nameString() if hasattr(spm, "nameString") else "Unnamed",
        }
        setpoint_mgrs.append(spm_info)

    return setpoint_mgrs


def _extract_air_loop(model, air_loop, detailed: bool = True) -> dict[str, Any]:
    """Extract air loop HVAC attributes to dict.

    Brief (detailed=False): name, zone count, zone names, terminal type.
    Detailed: adds full supply components, demand terminals per zone,
    OA system, setpoint managers.
    """
    zones = air_loop.thermalZones()
    num_zones = len(zones)
    result = {
        "name": air_loop.nameString(),
        "num_thermal_zones": num_zones,
    }
    if not detailed:
        # Include zone names and terminal type in brief mode —
        # enough for most planning without the full component dump
        result["thermal_zones"] = [z.nameString() for z in zones]
        if zones:
            t_opt = zones[0].airLoopHVACTerminal()
            if t_opt.is_initialized():
                result["terminal_type"] = t_opt.get().iddObjectType().valueName()
        return result

    # Get thermal zone names
    thermal_zones = [zone.nameString() for zone in air_loop.thermalZones()]

    # Get basic supply components
    supply_components = []
    for component in air_loop.supplyComponents():
        supply_components.append({
            "type": component.iddObjectType().valueName(),
            "name": component.nameString() if hasattr(component, "nameString") else "Unnamed",
        })

    # Extract demand-side terminals per zone
    demand_terminals = []
    for zone in air_loop.thermalZones():
        terminal_opt = zone.airLoopHVACTerminal()
        if terminal_opt.is_initialized():
            terminal = terminal_opt.get()
            demand_terminals.append({
                "zone": zone.nameString(),
                "terminal_type": terminal.iddObjectType().valueName(),
                "terminal_name": terminal.nameString(),
            })

    result.update({
        "handle": str(air_loop.handle()),
        "thermal_zones": thermal_zones,
        "num_supply_components": len(supply_components),
        "supply_components": supply_components[:10],
        "demand_terminals": demand_terminals,
        "detailed_components": _extract_detailed_supply_components(air_loop),
        "outdoor_air_system": _extract_outdoor_air_system(air_loop),
        "setpoint_managers": _extract_setpoint_managers(air_loop),
    })
    return result


def _extract_plant_loop(model, plant_loop, detailed: bool = True) -> dict[str, Any]:
    """Extract plant loop attributes to dict.

    Brief (detailed=False): name, component counts, primary equipment type.
    Detailed: adds full supply/demand component lists with types and names.
    """
    supply_components = list(plant_loop.supplyComponents())
    demand_components = list(plant_loop.demandComponents())
    result = {
        "name": plant_loop.nameString(),
        "num_supply_components": len(supply_components),
        "num_demand_components": len(demand_components),
    }
    if not detailed:
        # Include primary supply equipment type in brief mode —
        # enough to identify CHW/HW/condenser without full component dump
        for c in supply_components:
            t = c.iddObjectType().valueName()
            if t.startswith("OS_") and t not in (
                "OS_Node", "OS_Connector_Splitter", "OS_Connector_Mixer",
                "OS_Pipe_Adiabatic",
            ):
                result["primary_equipment"] = t
                break
        return result

    result.update({
        "handle": str(plant_loop.handle()),
        "supply_components": [
            {"type": c.iddObjectType().valueName(), "name": c.nameString() if hasattr(c, "nameString") else "Unnamed"}
            for c in supply_components[:10]
        ],
        "demand_components": [
            {"type": c.iddObjectType().valueName(), "name": c.nameString() if hasattr(c, "nameString") else "Unnamed"}
            for c in demand_components[:10]
        ],
    })
    return result


def _extract_zone_hvac_component(model, component) -> dict[str, Any]:
    """Extract zone HVAC component attributes to dict."""
    result = {
        "handle": str(component.handle()),
        "type": component.iddObjectType().valueName(),
    }

    # Try to get name (not all components have nameString method)
    try:
        if hasattr(component, "nameString"):
            result["name"] = component.nameString()
        else:
            result["name"] = "Unnamed"
    except Exception:
        result["name"] = "Unnamed"

    # Try to get thermal zone
    try:
        if hasattr(component, "thermalZone"):
            zone_optional = component.thermalZone()
            if zone_optional.is_initialized():
                result["thermal_zone"] = zone_optional.get().nameString()
    except Exception:
        pass

    return result


def list_air_loops(detailed: bool = False) -> dict[str, Any]:
    """List all air loop HVAC systems in the model."""
    try:
        model = get_model()
        air_loops = list_all_as_dicts(model, "getAirLoopHVACs", _extract_air_loop, detailed=detailed)
        return {
            "ok": True,
            "count": len(air_loops),
            "air_loops": air_loops,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list air loops: {e}"}


def get_air_loop_details(air_loop_name: str) -> dict[str, Any]:
    """Get detailed information about a specific air loop."""
    try:
        model = get_model()
        air_loop = fetch_object(model, "AirLoopHVAC", name=air_loop_name)

        if air_loop is None:
            return {"ok": False, "error": f"Air loop '{air_loop_name}' not found"}

        return {
            "ok": True,
            "air_loop": _extract_air_loop(model, air_loop),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get air loop details: {e}"}


def list_plant_loops(detailed: bool = False) -> dict[str, Any]:
    """List all plant loops in the model."""
    try:
        model = get_model()
        plant_loops = list_all_as_dicts(model, "getPlantLoops", _extract_plant_loop, detailed=detailed)
        return {
            "ok": True,
            "count": len(plant_loops),
            "plant_loops": plant_loops,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list plant loops: {e}"}


def list_zone_hvac_equipment(
    thermal_zone_name: str | None = None,
    equipment_type: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List zone HVAC equipment with filtering and pagination.

    Common filters:
    - Equipment in a zone: thermal_zone_name="Zone 1"
    - All PTACs: equipment_type="ZoneHVACPackagedTerminalAirConditioner"
    """
    try:
        model = get_model()

        filt = None
        if thermal_zone_name or equipment_type:
            def filt(m, comp):
                if equipment_type:
                    if comp.iddObjectType().valueName().replace("OS_", "").replace("_", "") != equipment_type.replace("_", ""):
                        # Also try exact iddObjectType match
                        if equipment_type not in comp.iddObjectType().valueName():
                            return False
                if thermal_zone_name:
                    if hasattr(comp, "thermalZone"):
                        tz = comp.thermalZone()
                        if not tz.is_initialized() or tz.get().nameString() != thermal_zone_name:
                            return False
                    else:
                        return False
                return True

        items, total = list_paginated(
            model, "getZoneHVACComponents", _extract_zone_hvac_component,
            max_results=max_results, obj_filter_fn=filt,
        )
        return build_list_response("zone_hvac_equipment", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list zone HVAC equipment: {e}"}


def add_air_loop(name: str, thermal_zone_names: list[str] | None = None) -> dict[str, Any]:
    """Add a new air loop HVAC system to the model.

    Args:
        name: Name for the new air loop
        thermal_zone_names: Optional list of thermal zone names to serve

    Returns:
        dict with ok=True and air_loop details, or ok=False and error message
    """
    try:
        model = get_model()

        # Create air loop
        air_loop = openstudio.model.AirLoopHVAC(model)
        air_loop.setName(name)

        # Connect to thermal zones if provided
        if thermal_zone_names:
            for zone_name in thermal_zone_names:
                thermal_zone = fetch_object(model, "ThermalZone", name=zone_name)
                if thermal_zone is None:
                    return {"ok": False, "error": f"Thermal zone '{zone_name}' not found"}

                # Add terminal and connect to zone
                terminal = openstudio.model.AirTerminalSingleDuctUncontrolled(model, model.alwaysOnDiscreteSchedule())
                air_loop.addBranchForZone(thermal_zone, terminal)

        # Extract and return
        result = _extract_air_loop(model, air_loop)
        return {"ok": True, "air_loop": result}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add air loop: {e}"}


def get_plant_loop_details(plant_loop_name: str) -> dict[str, Any]:
    """Get detailed information about a specific plant loop.

    NEW for Phase 4D: Provides setpoint temperatures, loop type, and sizing info
    for validating baseline system plant loops.

    Args:
        plant_loop_name: Name of plant loop

    Returns:
        dict with plant loop details including setpoints and sizing
    """
    try:
        model = get_model()
        plant_loop = fetch_object(model, "PlantLoop", name=plant_loop_name)

        if plant_loop is None:
            return {"ok": False, "error": f"Plant loop '{plant_loop_name}' not found"}

        # Get sizing information
        sizing = plant_loop.sizingPlant()
        loop_type = sizing.loopType()

        # Extract setpoint information from supply outlet node
        supply_outlet = plant_loop.supplyOutletNode()
        setpoint_temp_c = None

        for spm in supply_outlet.setpointManagers():
            # Try to get setpoint temperature
            if hasattr(spm, "setpointTemperature") and callable(spm.setpointTemperature):
                temp_opt = spm.setpointTemperature()
                if temp_opt.is_initialized():
                    setpoint_temp_c = temp_opt.get()
                    break

        result = {
            "ok": True,
            "plant_loop": {
                "handle": str(plant_loop.handle()),
                "name": plant_loop.nameString(),
                "loop_type": loop_type,
                "supply_temp_setpoint_c": setpoint_temp_c,
                "design_loop_exit_temp_c": sizing.designLoopExitTemperature(),
                "loop_design_delta_temp_c": sizing.loopDesignTemperatureDifference(),
                **_extract_plant_loop(model, plant_loop, detailed=True),
            },
        }

        return result

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get plant loop details: {e}"}


def get_zone_hvac_details(equipment_name: str) -> dict[str, Any]:
    """Get detailed information about specific zone HVAC equipment.

    NEW for Phase 4D: Provides coil details, fan specs, and capacity information
    for validating zone equipment like PTACs and PTHPs.

    Args:
        equipment_name: Name of zone HVAC equipment

    Returns:
        dict with equipment details including coils and fans
    """
    try:
        model = get_model()

        # Find equipment by name in all zone HVAC components
        equipment = None
        for comp in model.getZoneHVACComponents():
            if hasattr(comp, "nameString") and comp.nameString() == equipment_name:
                equipment = comp
                break

        if equipment is None:
            return {"ok": False, "error": f"Zone HVAC equipment '{equipment_name}' not found"}

        result = {
            "ok": True,
            "equipment": {
                "handle": str(equipment.handle()),
                "name": equipment.nameString() if hasattr(equipment, "nameString") else "Unnamed",
                "type": equipment.iddObjectType().valueName(),
            },
        }

        # Try to extract thermal zone
        if hasattr(equipment, "thermalZone"):
            zone_opt = equipment.thermalZone()
            if zone_opt.is_initialized():
                result["equipment"]["thermal_zone"] = zone_opt.get().nameString()

        # Try to cast to specific equipment types and extract coils
        # PTAC
        ptac = equipment.to_ZoneHVACPackagedTerminalAirConditioner()
        if ptac.is_initialized():
            ptac_obj = ptac.get()
            result["equipment"]["heating_coil"] = {
                "type": ptac_obj.heatingCoil().iddObjectType().valueName(),
                "name": ptac_obj.heatingCoil().nameString() if hasattr(ptac_obj.heatingCoil(), "nameString") else "Unnamed",
            }
            result["equipment"]["cooling_coil"] = {
                "type": ptac_obj.coolingCoil().iddObjectType().valueName(),
                "name": ptac_obj.coolingCoil().nameString() if hasattr(ptac_obj.coolingCoil(), "nameString") else "Unnamed",
            }
            result["equipment"]["fan"] = {
                "type": ptac_obj.supplyAirFan().iddObjectType().valueName(),
                "name": ptac_obj.supplyAirFan().nameString() if hasattr(ptac_obj.supplyAirFan(), "nameString") else "Unnamed",
            }

        # PTHP
        pthp = equipment.to_ZoneHVACPackagedTerminalHeatPump()
        if pthp.is_initialized():
            pthp_obj = pthp.get()
            result["equipment"]["heating_coil"] = {
                "type": pthp_obj.heatingCoil().iddObjectType().valueName(),
                "name": pthp_obj.heatingCoil().nameString() if hasattr(pthp_obj.heatingCoil(), "nameString") else "Unnamed",
            }
            result["equipment"]["cooling_coil"] = {
                "type": pthp_obj.coolingCoil().iddObjectType().valueName(),
                "name": pthp_obj.coolingCoil().nameString() if hasattr(pthp_obj.coolingCoil(), "nameString") else "Unnamed",
            }
            result["equipment"]["fan"] = {
                "type": pthp_obj.supplyAirFan().iddObjectType().valueName(),
                "name": pthp_obj.supplyAirFan().nameString() if hasattr(pthp_obj.supplyAirFan(), "nameString") else "Unnamed",
            }

        # Unit Heater
        unit_heater = equipment.to_ZoneHVACUnitHeater()
        if unit_heater.is_initialized():
            uh_obj = unit_heater.get()
            result["equipment"]["heating_coil"] = {
                "type": uh_obj.heatingCoil().iddObjectType().valueName(),
                "name": uh_obj.heatingCoil().nameString() if hasattr(uh_obj.heatingCoil(), "nameString") else "Unnamed",
            }
            result["equipment"]["fan"] = {
                "type": uh_obj.supplyAirFan().iddObjectType().valueName(),
                "name": uh_obj.supplyAirFan().nameString() if hasattr(uh_obj.supplyAirFan(), "nameString") else "Unnamed",
            }

        return result

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get zone HVAC details: {e}"}
