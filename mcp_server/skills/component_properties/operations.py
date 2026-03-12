"""Operations for querying and modifying HVAC component properties.

This module provides the MCP-facing operations that dispatch to explicit
per-component getter/setter functions defined in components.py.

The 5B controls operations (economizer, sizing, setpoint managers) access
components via their parent objects (air loop, plant loop) rather than by
name, so they use direct OpenStudio API calls inline.
"""
from __future__ import annotations

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object
from mcp_server.skills.component_properties.components import (
    CATEGORIES,
    COMPONENT_TYPES,
)

# ===================================================================
# 5A: Component Query & Modify
# ===================================================================

def _find_all_components(model: openstudio.model.Model, category: str | None = None) -> list[dict]:
    """Scan model for all HVAC components of known types.

    Iterates each entry in COMPONENT_TYPES and calls model.get<Type>s()
    to find all instances. Returns a flat list sorted by name.
    """
    components = []
    for os_type, type_def in COMPONENT_TYPES.items():
        if category and type_def["category"] != category:
            continue
        # model.getChillerElectricEIRs(), model.getBoilerHotWaters(), etc.
        getter_name = f"get{os_type}s"
        if not hasattr(model, getter_name):
            continue
        for obj in getattr(model, getter_name)():
            components.append({
                "name": obj.nameString(),
                "type": os_type,
                "category": type_def["category"],
            })
    components.sort(key=lambda d: d["name"])
    return components


def _find_component_by_name(model: openstudio.model.Model, name: str):
    """Find a component by name across all known types.

    Tries model.get<Type>ByName(name) for each entry in COMPONENT_TYPES.
    Returns (typed_object, type_def_dict) or None if not found.
    """
    for os_type, type_def in COMPONENT_TYPES.items():
        # model.getChillerElectricEIRByName(), model.getBoilerHotWaterByName(), etc.
        getter_name = f"get{os_type}ByName"
        if not hasattr(model, getter_name):
            continue
        result = getattr(model, getter_name)(name)
        if result.is_initialized():
            return result.get(), type_def
    return None


def list_hvac_components(
    category: str | None = None,
    max_results: int = 10,
) -> dict:
    """List HVAC components with optional category filter and pagination."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    if category and category not in CATEGORIES:
        return {"ok": False, "error": f"Unknown category '{category}'. Valid: {CATEGORIES}"}

    components = _find_all_components(model, category)
    total = len(components)
    truncated = max_results is not None and total > max_results
    if truncated:
        components = components[:max_results]

    resp: dict = {
        "ok": True,
        "count": len(components),
        "categories": CATEGORIES,
        "components": components,
    }
    if truncated:
        resp["total_available"] = total
        resp["truncated"] = True
    return resp


def get_component_properties(component_name: str) -> dict:
    """Get all properties for a named component using its explicit getter."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    found = _find_component_by_name(model, component_name)
    if found is None:
        supported = list(COMPONENT_TYPES.keys())
        return {
            "ok": False,
            "error": f"Component '{component_name}' not found. "
            f"Supported types: {supported}. "
            "For setpoint managers use set_setpoint_manager_properties. "
            "For zone HVAC use get_zone_hvac_details.",
        }

    obj, type_def = found
    # Call the explicit getter function for this component type
    props = type_def["get_props"](obj)

    return {
        "ok": True,
        "component_name": component_name,
        "component_type": next(
            k for k, v in COMPONENT_TYPES.items() if v is type_def
        ),
        "category": type_def["category"],
        "properties": props,
    }


def set_component_properties(component_name: str, properties: dict) -> dict:
    """Set properties on a named component using its explicit setter."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    found = _find_component_by_name(model, component_name)
    if found is None:
        return {"ok": False, "error": f"Component '{component_name}' not found"}

    obj, type_def = found
    # Call the explicit setter function for this component type
    changes, errors = type_def["set_props"](obj, properties)

    os_type = next(k for k, v in COMPONENT_TYPES.items() if v is type_def)
    result = {
        "ok": len(errors) == 0,
        "component_name": component_name,
        "component_type": os_type,
        "changes": changes,
    }
    if errors:
        result["errors"] = errors
    return result


# ===================================================================
# 5B: Controls & Setpoints
# ===================================================================
# These operations access components via their parent objects (air loop,
# plant loop) rather than by name. They use direct OpenStudio API calls
# because each controller type has unique access patterns.

def set_economizer_properties(air_loop_name: str, properties: dict) -> dict:
    """Modify outdoor air economizer properties on an air loop.

    Accesses the ControllerOutdoorAir via:
        air_loop.airLoopHVACOutdoorAirSystem().get().getControllerOutdoorAir()
    """
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    air_loop = fetch_object(model, "AirLoopHVAC", name=air_loop_name)
    if air_loop is None:
        return {"ok": False, "error": f"Air loop '{air_loop_name}' not found"}

    oa_sys_opt = air_loop.airLoopHVACOutdoorAirSystem()
    if not oa_sys_opt.is_initialized():
        return {"ok": False, "error": f"Air loop '{air_loop_name}' has no outdoor air system"}

    controller = oa_sys_opt.get().getControllerOutdoorAir()
    changes = {}
    errors = []

    for prop_name, new_value in properties.items():
        if prop_name == "economizer_control_type":
            # ControllerOutdoorAir.getEconomizerControlType() -> string
            old = str(controller.getEconomizerControlType())
            controller.setEconomizerControlType(str(new_value))
            changes[prop_name] = {"old": old, "new": str(controller.getEconomizerControlType())}

        elif prop_name == "max_limit_drybulb_temp_c":
            # ControllerOutdoorAir.getEconomizerMaximumLimitDryBulbTemperature() -> OptionalDouble
            raw = controller.getEconomizerMaximumLimitDryBulbTemperature()
            old = float(raw.get()) if raw.is_initialized() else None
            controller.setEconomizerMaximumLimitDryBulbTemperature(float(new_value))
            raw2 = controller.getEconomizerMaximumLimitDryBulbTemperature()
            changes[prop_name] = {"old": old, "new": float(raw2.get()) if raw2.is_initialized() else None}

        elif prop_name == "min_limit_drybulb_temp_c":
            # ControllerOutdoorAir.getEconomizerMinimumLimitDryBulbTemperature() -> OptionalDouble
            raw = controller.getEconomizerMinimumLimitDryBulbTemperature()
            old = float(raw.get()) if raw.is_initialized() else None
            controller.setEconomizerMinimumLimitDryBulbTemperature(float(new_value))
            raw2 = controller.getEconomizerMinimumLimitDryBulbTemperature()
            changes[prop_name] = {"old": old, "new": float(raw2.get()) if raw2.is_initialized() else None}

        else:
            errors.append(f"Unknown economizer property '{prop_name}'")

    result = {"ok": len(errors) == 0, "air_loop": air_loop_name, "changes": changes}
    if errors:
        result["errors"] = errors
    return result


def set_sizing_properties(loop_name: str, properties: dict) -> dict:
    """Modify SizingPlant properties on a plant loop.

    Accesses sizing via: plant_loop.sizingPlant()
    API verified in openstudio-resources water_economizer.py and our wiring.py.
    """
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    plant_loop = fetch_object(model, "PlantLoop", name=loop_name)
    if plant_loop is None:
        return {"ok": False, "error": f"Plant loop '{loop_name}' not found"}

    sizing = plant_loop.sizingPlant()
    changes = {}
    errors = []

    for prop_name, new_value in properties.items():
        if prop_name == "loop_type":
            # SizingPlant.loopType() -> string
            old = str(sizing.loopType())
            sizing.setLoopType(str(new_value))
            changes[prop_name] = {"old": old, "new": str(sizing.loopType())}

        elif prop_name == "design_loop_exit_temperature_c":
            # SizingPlant.designLoopExitTemperature() -> double
            old = float(sizing.designLoopExitTemperature())
            sizing.setDesignLoopExitTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(sizing.designLoopExitTemperature())}

        elif prop_name == "loop_design_temperature_difference_c":
            # SizingPlant.loopDesignTemperatureDifference() -> double
            old = float(sizing.loopDesignTemperatureDifference())
            sizing.setLoopDesignTemperatureDifference(float(new_value))
            changes[prop_name] = {"old": old, "new": float(sizing.loopDesignTemperatureDifference())}

        else:
            errors.append(f"Unknown sizing property '{prop_name}'")

    result = {"ok": len(errors) == 0, "plant_loop": loop_name, "changes": changes}
    if errors:
        result["errors"] = errors
    return result


def set_sizing_system_properties(air_loop_name: str, properties: dict) -> dict:
    """Get/set SizingSystem properties on an air loop.

    Accesses via: air_loop.sizingSystem() (auto-created with every AirLoopHVAC).
    """
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    air_loop = fetch_object(model, "AirLoopHVAC", name=air_loop_name)
    if air_loop is None:
        return {"ok": False, "error": f"Air loop '{air_loop_name}' not found"}

    sizing = air_loop.sizingSystem()
    changes = {}
    errors = []

    for prop_name, new_value in properties.items():
        if prop_name == "type_of_load_to_size_on":
            old = str(sizing.typeofLoadtoSizeOn())
            sizing.setTypeofLoadtoSizeOn(str(new_value))
            changes[prop_name] = {"old": old, "new": str(sizing.typeofLoadtoSizeOn())}
        elif prop_name == "central_cooling_design_supply_air_temperature":
            old = float(sizing.centralCoolingDesignSupplyAirTemperature())
            sizing.setCentralCoolingDesignSupplyAirTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(sizing.centralCoolingDesignSupplyAirTemperature())}
        elif prop_name == "central_heating_design_supply_air_temperature":
            old = float(sizing.centralHeatingDesignSupplyAirTemperature())
            sizing.setCentralHeatingDesignSupplyAirTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(sizing.centralHeatingDesignSupplyAirTemperature())}
        elif prop_name == "central_cooling_design_supply_air_humidity_ratio":
            old = float(sizing.centralCoolingDesignSupplyAirHumidityRatio())
            sizing.setCentralCoolingDesignSupplyAirHumidityRatio(float(new_value))
            changes[prop_name] = {"old": old, "new": float(sizing.centralCoolingDesignSupplyAirHumidityRatio())}
        elif prop_name == "central_heating_design_supply_air_humidity_ratio":
            old = float(sizing.centralHeatingDesignSupplyAirHumidityRatio())
            sizing.setCentralHeatingDesignSupplyAirHumidityRatio(float(new_value))
            changes[prop_name] = {"old": old, "new": float(sizing.centralHeatingDesignSupplyAirHumidityRatio())}
        elif prop_name == "all_outdoor_air_in_cooling":
            old = bool(sizing.allOutdoorAirinCooling())
            sizing.setAllOutdoorAirinCooling(bool(new_value))
            changes[prop_name] = {"old": old, "new": bool(sizing.allOutdoorAirinCooling())}
        elif prop_name == "all_outdoor_air_in_heating":
            old = bool(sizing.allOutdoorAirinHeating())
            sizing.setAllOutdoorAirinHeating(bool(new_value))
            changes[prop_name] = {"old": old, "new": bool(sizing.allOutdoorAirinHeating())}
        elif prop_name == "preheat_design_temperature":
            old = float(sizing.preheatDesignTemperature())
            sizing.setPreheatDesignTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(sizing.preheatDesignTemperature())}
        elif prop_name == "precool_design_temperature":
            old = float(sizing.precoolDesignTemperature())
            sizing.setPrecoolDesignTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(sizing.precoolDesignTemperature())}
        elif prop_name == "sizing_option":
            old = str(sizing.sizingOption())
            sizing.setSizingOption(str(new_value))
            changes[prop_name] = {"old": old, "new": str(sizing.sizingOption())}
        elif prop_name == "cooling_design_air_flow_method":
            old = str(sizing.coolingDesignAirFlowMethod())
            sizing.setCoolingDesignAirFlowMethod(str(new_value))
            changes[prop_name] = {"old": old, "new": str(sizing.coolingDesignAirFlowMethod())}
        elif prop_name == "heating_design_air_flow_method":
            old = str(sizing.heatingDesignAirFlowMethod())
            sizing.setHeatingDesignAirFlowMethod(str(new_value))
            changes[prop_name] = {"old": old, "new": str(sizing.heatingDesignAirFlowMethod())}
        else:
            errors.append(f"Unknown sizing system property '{prop_name}'")

    result = {"ok": len(errors) == 0, "air_loop": air_loop_name, "changes": changes}
    if errors:
        result["errors"] = errors
    return result


def get_sizing_system_properties(air_loop_name: str) -> dict:
    """Read all SizingSystem properties for an air loop."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    air_loop = fetch_object(model, "AirLoopHVAC", name=air_loop_name)
    if air_loop is None:
        return {"ok": False, "error": f"Air loop '{air_loop_name}' not found"}

    sizing = air_loop.sizingSystem()
    return {
        "ok": True,
        "air_loop": air_loop_name,
        "properties": {
            "type_of_load_to_size_on": str(sizing.typeofLoadtoSizeOn()),
            "central_cooling_design_supply_air_temperature": float(sizing.centralCoolingDesignSupplyAirTemperature()),
            "central_heating_design_supply_air_temperature": float(sizing.centralHeatingDesignSupplyAirTemperature()),
            "central_cooling_design_supply_air_humidity_ratio": float(
                sizing.centralCoolingDesignSupplyAirHumidityRatio()),
            "central_heating_design_supply_air_humidity_ratio": float(
                sizing.centralHeatingDesignSupplyAirHumidityRatio()),
            "all_outdoor_air_in_cooling": bool(sizing.allOutdoorAirinCooling()),
            "all_outdoor_air_in_heating": bool(sizing.allOutdoorAirinHeating()),
            "preheat_design_temperature": float(sizing.preheatDesignTemperature()),
            "precool_design_temperature": float(sizing.precoolDesignTemperature()),
            "sizing_option": str(sizing.sizingOption()),
            "cooling_design_air_flow_method": str(sizing.coolingDesignAirFlowMethod()),
            "heating_design_air_flow_method": str(sizing.heatingDesignAirFlowMethod()),
        },
    }


def set_sizing_zone_properties(zone_names: list[str] | str, properties: dict) -> dict:
    """Set SizingZone properties on one or more thermal zones.

    Accesses via: thermal_zone.sizingZone() (auto-created with every ThermalZone).
    """
    from mcp_server.osm_helpers import parse_str_list

    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    names = parse_str_list(zone_names) if isinstance(zone_names, str) else zone_names
    results = []

    for zone_name in names:
        zone = fetch_object(model, "ThermalZone", name=zone_name)
        if zone is None:
            results.append({"zone": zone_name, "ok": False, "error": "not found"})
            continue

        sizing = zone.sizingZone()
        changes = {}
        errors = []

        for prop_name, new_value in properties.items():
            if prop_name == "zone_cooling_design_supply_air_temperature":
                old = float(sizing.zoneCoolingDesignSupplyAirTemperature())
                sizing.setZoneCoolingDesignSupplyAirTemperature(float(new_value))
                changes[prop_name] = {"old": old, "new": float(sizing.zoneCoolingDesignSupplyAirTemperature())}
            elif prop_name == "zone_heating_design_supply_air_temperature":
                old = float(sizing.zoneHeatingDesignSupplyAirTemperature())
                sizing.setZoneHeatingDesignSupplyAirTemperature(float(new_value))
                changes[prop_name] = {"old": old, "new": float(sizing.zoneHeatingDesignSupplyAirTemperature())}
            elif prop_name == "zone_cooling_sizing_factor":
                old = float(sizing.zoneCoolingSizingFactor())
                sizing.setZoneCoolingSizingFactor(float(new_value))
                changes[prop_name] = {"old": old, "new": float(sizing.zoneCoolingSizingFactor())}
            elif prop_name == "zone_heating_sizing_factor":
                old = float(sizing.zoneHeatingSizingFactor())
                sizing.setZoneHeatingSizingFactor(float(new_value))
                changes[prop_name] = {"old": old, "new": float(sizing.zoneHeatingSizingFactor())}
            elif prop_name == "zone_cooling_design_supply_air_temp_input_method":
                old = str(sizing.zoneCoolingDesignSupplyAirTemperatureInputMethod())
                sizing.setZoneCoolingDesignSupplyAirTemperatureInputMethod(str(new_value))
                changes[prop_name] = {"old": old, "new": str(sizing.zoneCoolingDesignSupplyAirTemperatureInputMethod())}
            elif prop_name == "zone_heating_design_supply_air_temp_input_method":
                old = str(sizing.zoneHeatingDesignSupplyAirTemperatureInputMethod())
                sizing.setZoneHeatingDesignSupplyAirTemperatureInputMethod(str(new_value))
                changes[prop_name] = {"old": old, "new": str(sizing.zoneHeatingDesignSupplyAirTemperatureInputMethod())}
            elif prop_name == "cooling_design_air_flow_method":
                old = str(sizing.coolingDesignAirFlowMethod())
                sizing.setCoolingDesignAirFlowMethod(str(new_value))
                changes[prop_name] = {"old": old, "new": str(sizing.coolingDesignAirFlowMethod())}
            elif prop_name == "cooling_minimum_air_flow_fraction":
                old = float(sizing.coolingMinimumAirFlowFraction())
                sizing.setCoolingMinimumAirFlowFraction(float(new_value))
                changes[prop_name] = {"old": old, "new": float(sizing.coolingMinimumAirFlowFraction())}
            elif prop_name == "account_for_dedicated_outdoor_air_system":
                old = bool(sizing.accountforDedicatedOutdoorAirSystem())
                sizing.setAccountforDedicatedOutdoorAirSystem(bool(new_value))
                changes[prop_name] = {"old": old, "new": bool(sizing.accountforDedicatedOutdoorAirSystem())}
            elif prop_name == "dedicated_outdoor_air_system_control_strategy":
                old = str(sizing.dedicatedOutdoorAirSystemControlStrategy())
                sizing.setDedicatedOutdoorAirSystemControlStrategy(str(new_value))
                changes[prop_name] = {"old": old, "new": str(sizing.dedicatedOutdoorAirSystemControlStrategy())}
            elif prop_name == "dedicated_outdoor_air_low_setpoint_temp":
                old = float(sizing.dedicatedOutdoorAirLowSetpointTemperatureforDesign())
                sizing.setDedicatedOutdoorAirLowSetpointTemperatureforDesign(float(new_value))
                new_val = float(sizing.dedicatedOutdoorAirLowSetpointTemperatureforDesign())
                changes[prop_name] = {"old": old, "new": new_val}
            elif prop_name == "dedicated_outdoor_air_high_setpoint_temp":
                old = float(sizing.dedicatedOutdoorAirHighSetpointTemperatureforDesign())
                sizing.setDedicatedOutdoorAirHighSetpointTemperatureforDesign(float(new_value))
                new_val = float(sizing.dedicatedOutdoorAirHighSetpointTemperatureforDesign())
                changes[prop_name] = {"old": old, "new": new_val}
            else:
                errors.append(f"Unknown sizing zone property '{prop_name}'")

        zone_result = {"zone": zone_name, "ok": len(errors) == 0, "changes": changes}
        if errors:
            zone_result["errors"] = errors
        results.append(zone_result)

    return {
        "ok": all(r["ok"] for r in results),
        "zones_processed": len(results),
        "results": results,
    }


def get_sizing_zone_properties(zone_name: str) -> dict:
    """Read all SizingZone properties for a thermal zone."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    zone = fetch_object(model, "ThermalZone", name=zone_name)
    if zone is None:
        return {"ok": False, "error": f"Thermal zone '{zone_name}' not found"}

    sizing = zone.sizingZone()
    return {
        "ok": True,
        "zone": zone_name,
        "properties": {
            "zone_cooling_design_supply_air_temperature": float(sizing.zoneCoolingDesignSupplyAirTemperature()),
            "zone_heating_design_supply_air_temperature": float(sizing.zoneHeatingDesignSupplyAirTemperature()),
            "zone_cooling_sizing_factor": float(sizing.zoneCoolingSizingFactor()),
            "zone_heating_sizing_factor": float(sizing.zoneHeatingSizingFactor()),
            "zone_cooling_design_supply_air_temp_input_method": str(
                sizing.zoneCoolingDesignSupplyAirTemperatureInputMethod()),
            "zone_heating_design_supply_air_temp_input_method": str(
                sizing.zoneHeatingDesignSupplyAirTemperatureInputMethod()),
            "cooling_design_air_flow_method": str(sizing.coolingDesignAirFlowMethod()),
            "cooling_minimum_air_flow_fraction": float(sizing.coolingMinimumAirFlowFraction()),
            "account_for_dedicated_outdoor_air_system": bool(sizing.accountforDedicatedOutdoorAirSystem()),
            "dedicated_outdoor_air_system_control_strategy": str(sizing.dedicatedOutdoorAirSystemControlStrategy()),
            "dedicated_outdoor_air_low_setpoint_temp": float(
                sizing.dedicatedOutdoorAirLowSetpointTemperatureforDesign()),
            "dedicated_outdoor_air_high_setpoint_temp": float(
                sizing.dedicatedOutdoorAirHighSetpointTemperatureforDesign()),
        },
    }


# ===================================================================
# 5C: Setpoint Managers (W8)
# ===================================================================
# Registry of supported SPM types: getter method, get/set functions.

def _get_spm_single_zone_reheat_props(spm) -> dict:
    return {
        "minimum_supply_air_temperature_c": {"value": float(spm.minimumSupplyAirTemperature()), "unit": "C"},
        "maximum_supply_air_temperature_c": {"value": float(spm.maximumSupplyAirTemperature()), "unit": "C"},
    }

def _set_spm_single_zone_reheat_props(spm, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for prop_name, new_value in properties.items():
        if prop_name == "minimum_supply_air_temperature_c":
            old = float(spm.minimumSupplyAirTemperature())
            spm.setMinimumSupplyAirTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.minimumSupplyAirTemperature())}
        elif prop_name == "maximum_supply_air_temperature_c":
            old = float(spm.maximumSupplyAirTemperature())
            spm.setMaximumSupplyAirTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.maximumSupplyAirTemperature())}
        else:
            errors.append(f"Unknown property '{prop_name}' for SetpointManagerSingleZoneReheat")
    return changes, errors

def _get_spm_scheduled_props(spm) -> dict:
    return {
        "control_variable": {"value": str(spm.controlVariable()), "unit": None},
    }

def _set_spm_scheduled_props(spm, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for prop_name, new_value in properties.items():
        if prop_name == "control_variable":
            old = str(spm.controlVariable())
            spm.setControlVariable(str(new_value))
            changes[prop_name] = {"old": old, "new": str(spm.controlVariable())}
        else:
            errors.append(f"Unknown property '{prop_name}' for SetpointManagerScheduled")
    return changes, errors

def _get_spm_warmest_props(spm) -> dict:
    return {
        "minimum_setpoint_temperature": {"value": float(spm.minimumSetpointTemperature()), "unit": "C"},
        "maximum_setpoint_temperature": {"value": float(spm.maximumSetpointTemperature()), "unit": "C"},
        "strategy": {"value": str(spm.strategy()), "unit": None},
    }

def _set_spm_warmest_props(spm, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for prop_name, new_value in properties.items():
        if prop_name == "minimum_setpoint_temperature":
            old = float(spm.minimumSetpointTemperature())
            spm.setMinimumSetpointTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.minimumSetpointTemperature())}
        elif prop_name == "maximum_setpoint_temperature":
            old = float(spm.maximumSetpointTemperature())
            spm.setMaximumSetpointTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.maximumSetpointTemperature())}
        elif prop_name == "strategy":
            old = str(spm.strategy())
            spm.setStrategy(str(new_value))
            changes[prop_name] = {"old": old, "new": str(spm.strategy())}
        else:
            errors.append(f"Unknown property '{prop_name}' for SetpointManagerWarmest")
    return changes, errors

def _get_spm_coldest_props(spm) -> dict:
    return {
        "minimum_setpoint_temperature": {"value": float(spm.minimumSetpointTemperature()), "unit": "C"},
        "maximum_setpoint_temperature": {"value": float(spm.maximumSetpointTemperature()), "unit": "C"},
        "strategy": {"value": str(spm.strategy()), "unit": None},
    }

def _set_spm_coldest_props(spm, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for prop_name, new_value in properties.items():
        if prop_name == "minimum_setpoint_temperature":
            old = float(spm.minimumSetpointTemperature())
            spm.setMinimumSetpointTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.minimumSetpointTemperature())}
        elif prop_name == "maximum_setpoint_temperature":
            old = float(spm.maximumSetpointTemperature())
            spm.setMaximumSetpointTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.maximumSetpointTemperature())}
        elif prop_name == "strategy":
            old = str(spm.strategy())
            spm.setStrategy(str(new_value))
            changes[prop_name] = {"old": old, "new": str(spm.strategy())}
        else:
            errors.append(f"Unknown property '{prop_name}' for SetpointManagerColdest")
    return changes, errors

def _get_spm_follow_oat_props(spm) -> dict:
    return {
        "reference_temperature_type": {"value": str(spm.referenceTemperatureType()), "unit": None},
        "offset_temperature_difference": {"value": float(spm.offsetTemperatureDifference()), "unit": "C"},
        "minimum_setpoint_temperature": {"value": float(spm.minimumSetpointTemperature()), "unit": "C"},
        "maximum_setpoint_temperature": {"value": float(spm.maximumSetpointTemperature()), "unit": "C"},
    }

def _set_spm_follow_oat_props(spm, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for prop_name, new_value in properties.items():
        if prop_name == "reference_temperature_type":
            old = str(spm.referenceTemperatureType())
            spm.setReferenceTemperatureType(str(new_value))
            changes[prop_name] = {"old": old, "new": str(spm.referenceTemperatureType())}
        elif prop_name == "offset_temperature_difference":
            old = float(spm.offsetTemperatureDifference())
            spm.setOffsetTemperatureDifference(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.offsetTemperatureDifference())}
        elif prop_name == "minimum_setpoint_temperature":
            old = float(spm.minimumSetpointTemperature())
            spm.setMinimumSetpointTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.minimumSetpointTemperature())}
        elif prop_name == "maximum_setpoint_temperature":
            old = float(spm.maximumSetpointTemperature())
            spm.setMaximumSetpointTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.maximumSetpointTemperature())}
        else:
            errors.append(f"Unknown property '{prop_name}' for SetpointManagerFollowOutdoorAirTemperature")
    return changes, errors

def _get_spm_outdoor_air_reset_props(spm) -> dict:
    return {
        "setpoint_at_outdoor_low_temperature": {"value": float(spm.setpointatOutdoorLowTemperature()), "unit": "C"},
        "outdoor_low_temperature": {"value": float(spm.outdoorLowTemperature()), "unit": "C"},
        "setpoint_at_outdoor_high_temperature": {"value": float(spm.setpointatOutdoorHighTemperature()), "unit": "C"},
        "outdoor_high_temperature": {"value": float(spm.outdoorHighTemperature()), "unit": "C"},
    }

def _set_spm_outdoor_air_reset_props(spm, properties: dict) -> tuple[dict, list]:
    changes, errors = {}, []
    for prop_name, new_value in properties.items():
        if prop_name == "setpoint_at_outdoor_low_temperature":
            old = float(spm.setpointatOutdoorLowTemperature())
            spm.setSetpointatOutdoorLowTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.setpointatOutdoorLowTemperature())}
        elif prop_name == "outdoor_low_temperature":
            old = float(spm.outdoorLowTemperature())
            spm.setOutdoorLowTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.outdoorLowTemperature())}
        elif prop_name == "setpoint_at_outdoor_high_temperature":
            old = float(spm.setpointatOutdoorHighTemperature())
            spm.setSetpointatOutdoorHighTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.setpointatOutdoorHighTemperature())}
        elif prop_name == "outdoor_high_temperature":
            old = float(spm.outdoorHighTemperature())
            spm.setOutdoorHighTemperature(float(new_value))
            changes[prop_name] = {"old": old, "new": float(spm.outdoorHighTemperature())}
        else:
            errors.append(f"Unknown property '{prop_name}' for SetpointManagerOutdoorAirReset")
    return changes, errors

def _get_spm_scheduled_dual_setpoint_props(spm) -> dict:
    high_sched = spm.highSetpointSchedule()
    low_sched = spm.lowSetpointSchedule()
    return {
        "high_setpoint_schedule": {
            "value": high_sched.nameString() if high_sched.is_initialized() else None,
            "unit": None,
        },
        "low_setpoint_schedule": {
            "value": low_sched.nameString() if low_sched.is_initialized() else None,
            "unit": None,
        },
    }

def _set_spm_scheduled_dual_setpoint_props(spm, properties: dict) -> tuple[dict, list]:
    from mcp_server.model_manager import get_model
    model = get_model()
    changes, errors = {}, []
    for prop_name, new_value in properties.items():
        if prop_name == "high_setpoint_schedule":
            sched = fetch_object(model, "Schedule", name=str(new_value))
            if sched is None:
                errors.append(f"Schedule '{new_value}' not found")
                continue
            spm.setHighSetpointSchedule(sched)
            changes[prop_name] = {"new": str(new_value)}
        elif prop_name == "low_setpoint_schedule":
            sched = fetch_object(model, "Schedule", name=str(new_value))
            if sched is None:
                errors.append(f"Schedule '{new_value}' not found")
                continue
            spm.setLowSetpointSchedule(sched)
            changes[prop_name] = {"new": str(new_value)}
        else:
            errors.append(f"Unknown property '{prop_name}' for SetpointManagerScheduledDualSetpoint")
    return changes, errors

# SPM type registry
SPM_TYPES = {
    "SetpointManagerSingleZoneReheat": {
        "getter": "getSetpointManagerSingleZoneReheats",
        "by_name": "getSetpointManagerSingleZoneReheatByName",
        "get_props": _get_spm_single_zone_reheat_props,
        "set_props": _set_spm_single_zone_reheat_props,
    },
    "SetpointManagerScheduled": {
        "getter": "getSetpointManagerScheduleds",
        "by_name": "getSetpointManagerScheduledByName",
        "get_props": _get_spm_scheduled_props,
        "set_props": _set_spm_scheduled_props,
    },
    "SetpointManagerWarmest": {
        "getter": "getSetpointManagerWarmests",
        "by_name": "getSetpointManagerWarmestByName",
        "get_props": _get_spm_warmest_props,
        "set_props": _set_spm_warmest_props,
    },
    "SetpointManagerColdest": {
        "getter": "getSetpointManagerColdests",
        "by_name": "getSetpointManagerColdestByName",
        "get_props": _get_spm_coldest_props,
        "set_props": _set_spm_coldest_props,
    },
    "SetpointManagerFollowOutdoorAirTemperature": {
        "getter": "getSetpointManagerFollowOutdoorAirTemperatures",
        "by_name": "getSetpointManagerFollowOutdoorAirTemperatureByName",
        "get_props": _get_spm_follow_oat_props,
        "set_props": _set_spm_follow_oat_props,
    },
    "SetpointManagerOutdoorAirReset": {
        "getter": "getSetpointManagerOutdoorAirResets",
        "by_name": "getSetpointManagerOutdoorAirResetByName",
        "get_props": _get_spm_outdoor_air_reset_props,
        "set_props": _set_spm_outdoor_air_reset_props,
    },
    "SetpointManagerScheduledDualSetpoint": {
        "getter": "getSetpointManagerScheduledDualSetpoints",
        "by_name": "getSetpointManagerScheduledDualSetpointByName",
        "get_props": _get_spm_scheduled_dual_setpoint_props,
        "set_props": _set_spm_scheduled_dual_setpoint_props,
    },
}


def get_setpoint_manager_properties(setpoint_name: str) -> dict:
    """Get all properties for a named setpoint manager."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    for spm_type, type_def in SPM_TYPES.items():
        by_name = getattr(model, type_def["by_name"], None)
        if by_name is None:
            continue
        result = by_name(setpoint_name)
        if result.is_initialized():
            spm = result.get()
            props = type_def["get_props"](spm)
            return {
                "ok": True,
                "setpoint_manager": setpoint_name,
                "type": spm_type,
                "properties": props,
            }

    supported = list(SPM_TYPES.keys())
    return {"ok": False, "error": f"Setpoint manager '{setpoint_name}' not found. Supported types: {supported}"}


def set_setpoint_manager_properties(setpoint_name: str, properties: dict) -> dict:
    """Modify setpoint manager properties by name.

    Searches across supported types: SetpointManagerSingleZoneReheat,
    SetpointManagerScheduled, SetpointManagerWarmest, SetpointManagerColdest,
    SetpointManagerFollowOutdoorAirTemperature, SetpointManagerOutdoorAirReset,
    SetpointManagerScheduledDualSetpoint.
    """
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    for spm_type, type_def in SPM_TYPES.items():
        by_name = getattr(model, type_def["by_name"], None)
        if by_name is None:
            continue
        result = by_name(setpoint_name)
        if result.is_initialized():
            spm = result.get()
            changes, errors = type_def["set_props"](spm, properties)
            result_dict = {
                "ok": len(errors) == 0,
                "setpoint_manager": setpoint_name,
                "type": spm_type,
                "changes": changes,
            }
            if errors:
                result_dict["errors"] = errors
            return result_dict

    supported = list(SPM_TYPES.keys())
    return {"ok": False, "error": f"Setpoint manager '{setpoint_name}' not found. Supported types: {supported}"}
