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
            components.append(
                {
                    "name": obj.nameString(),
                    "type": os_type,
                    "category": type_def["category"],
                },
            )
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


def list_hvac_components(category: str | None = None) -> dict:
    """List all HVAC components in model matching known types."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    if category and category not in CATEGORIES:
        return {"ok": False, "error": f"Unknown category '{category}'. Valid: {CATEGORIES}"}

    components = _find_all_components(model, category)
    return {
        "ok": True,
        "count": len(components),
        "categories": CATEGORIES,
        "components": components,
    }


def get_component_properties(component_name: str) -> dict:
    """Get all properties for a named component using its explicit getter."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    found = _find_component_by_name(model, component_name)
    if found is None:
        return {"ok": False, "error": f"Component '{component_name}' not found"}

    obj, type_def = found
    # Call the explicit getter function for this component type
    props = type_def["get_props"](obj)

    return {
        "ok": True,
        "component_name": component_name,
        "component_type": next(k for k, v in COMPONENT_TYPES.items() if v is type_def),
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


def set_setpoint_manager_properties(setpoint_name: str, properties: dict) -> dict:
    """Modify setpoint manager properties by name.

    Searches for the SPM across supported types:
    - SetpointManagerSingleZoneReheat: min/max supply air temperature
    - SetpointManagerScheduled: control variable
    """
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    changes = {}
    errors = []

    # Try SetpointManagerSingleZoneReheat
    result = model.getSetpointManagerSingleZoneReheatByName(setpoint_name)
    if result.is_initialized():
        spm = result.get()
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

        result_dict = {"ok": len(errors) == 0, "setpoint_manager": setpoint_name, "changes": changes}
        if errors:
            result_dict["errors"] = errors
        return result_dict

    # Try SetpointManagerScheduled
    result = model.getSetpointManagerScheduledByName(setpoint_name)
    if result.is_initialized():
        spm = result.get()
        for prop_name, new_value in properties.items():
            if prop_name == "control_variable":
                old = str(spm.controlVariable())
                spm.setControlVariable(str(new_value))
                changes[prop_name] = {"old": old, "new": str(spm.controlVariable())}
            else:
                errors.append(f"Unknown property '{prop_name}' for SetpointManagerScheduled")

        result_dict = {"ok": len(errors) == 0, "setpoint_manager": setpoint_name, "changes": changes}
        if errors:
            result_dict["errors"] = errors
        return result_dict

    return {"ok": False, "error": f"Setpoint manager '{setpoint_name}' not found"}
