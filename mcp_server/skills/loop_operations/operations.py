"""Operations for adding/removing equipment on plant loops and zones."""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object

# Supported supply equipment types and their constructors
SUPPLY_EQUIPMENT_TYPES = {
    "BoilerHotWater": {
        "constructor": "BoilerHotWater",
        "properties": {
            "nominal_thermal_efficiency": {"set": "setNominalThermalEfficiency", "type": "double"},
            "fuel_type": {"set": "setFuelType", "type": "string"},
            "nominal_capacity_w": {"set": "setNominalCapacity", "type": "double"},
        },
    },
    "ChillerElectricEIR": {
        "constructor": "ChillerElectricEIR",
        "properties": {
            "reference_cop": {"set": "setReferenceCOP", "type": "double"},
            "reference_capacity_w": {"set": "setReferenceCapacity", "type": "double"},
        },
    },
    "CoolingTowerSingleSpeed": {
        "constructor": "CoolingTowerSingleSpeed",
        "properties": {},
    },
}

# Supported zone equipment types
ZONE_EQUIPMENT_TYPES = {
    "ZoneHVACBaseboardConvectiveElectric": {
        "constructor": "ZoneHVACBaseboardConvectiveElectric",
        "properties": {
            "nominal_capacity_w": {"set": "setNominalCapacity", "type": "double"},
        },
    },
    "ZoneHVACUnitHeater": {
        "constructor": "ZoneHVACUnitHeater",
        "needs_schedule_and_fan": True,
        "properties": {},
    },
}


def _apply_properties(obj: Any, props: dict, type_def: dict) -> list[str]:
    """Apply optional properties to a newly created object. Returns errors."""
    errors = []
    if not props:
        return errors
    for prop_name, value in props.items():
        if prop_name not in type_def.get("properties", {}):
            errors.append(f"Unknown property '{prop_name}'")
            continue
        prop_def = type_def["properties"][prop_name]
        try:
            if prop_def["type"] == "double":
                getattr(obj, prop_def["set"])(float(value))
            elif prop_def["type"] == "string":
                getattr(obj, prop_def["set"])(str(value))
        except Exception as e:
            errors.append(f"Failed to set {prop_name}: {e}")
    return errors


def create_plant_loop(
    name: str,
    loop_type: str,
    design_exit_temp_c: float | None = None,
    design_delta_temp_c: float | None = None,
    supply_pump_type: str = "variable",
    pump_head_pa: float = 179352.0,
    pump_motor_eff: float = 0.9,
) -> dict:
    """Create a PlantLoop with sizing, pump, bypass pipe, and setpoint manager.

    Args:
        name: Name for the plant loop
        loop_type: "Cooling" or "Heating" (sets sizing defaults)
        design_exit_temp_c: Loop design exit temperature (C). Default 7.2 for cooling, 82.0 for heating.
        design_delta_temp_c: Loop design temperature difference (C). Default 6.7 for cooling, 11.0 for heating.
        supply_pump_type: "variable" or "constant" (default "variable")
        pump_head_pa: Pump head in Pa (default 179352)
        pump_motor_eff: Pump motor efficiency 0-1 (default 0.9)
    """
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    if loop_type not in ("Cooling", "Heating"):
        return {"ok": False, "error": f"loop_type must be 'Cooling' or 'Heating', got '{loop_type}'"}

    # Defaults based on loop type
    if design_exit_temp_c is None:
        design_exit_temp_c = 7.22 if loop_type == "Cooling" else 82.0
    if design_delta_temp_c is None:
        design_delta_temp_c = 6.67 if loop_type == "Cooling" else 11.0

    try:
        # Create plant loop
        loop = openstudio.model.PlantLoop(model)
        loop.setName(name)

        # Configure sizing
        sizing = loop.sizingPlant()
        sizing.setDesignLoopExitTemperature(design_exit_temp_c)
        sizing.setLoopDesignTemperatureDifference(design_delta_temp_c)
        sizing.setLoopType(loop_type)

        # Add pump on supply inlet node
        supply_inlet = loop.supplyInletNode()
        if supply_pump_type == "constant":
            pump = openstudio.model.PumpConstantSpeed(model)
        else:
            pump = openstudio.model.PumpVariableSpeed(model)
        pump.setName(f"{name} Pump")
        pump.setRatedPumpHead(pump_head_pa)
        pump.setMotorEfficiency(pump_motor_eff)
        pump.addToNode(supply_inlet)

        # Add bypass pipe on supply side
        bypass = openstudio.model.PipeAdiabatic(model)
        bypass.setName(f"{name} Supply Bypass")
        loop.addSupplyBranchForComponent(bypass)

        # Add demand bypass pipe
        demand_bypass = openstudio.model.PipeAdiabatic(model)
        demand_bypass.setName(f"{name} Demand Bypass")
        loop.addDemandBranchForComponent(demand_bypass)

        # Add setpoint manager on supply outlet
        supply_outlet = loop.supplyOutletNode()
        spm_sched = openstudio.model.ScheduleConstant(model)
        spm_sched.setName(f"{name} SPM Schedule")
        spm_sched.setValue(design_exit_temp_c)
        spm = openstudio.model.SetpointManagerScheduled(model, spm_sched)
        spm.setName(f"{name} SPM")
        spm.addToNode(supply_outlet)

        return {
            "ok": True,
            "name": loop.nameString(),
            "loop_type": loop_type,
            "design_exit_temp_c": design_exit_temp_c,
            "design_delta_temp_c": design_delta_temp_c,
            "pump_type": supply_pump_type,
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to create plant loop: {e}"}


def add_demand_component(component_name: str, plant_loop_name: str) -> dict:
    """Add an existing component to a plant loop's demand side."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    plant_loop = fetch_object(model, "PlantLoop", name=plant_loop_name)
    if plant_loop is None:
        return {"ok": False, "error": f"Plant loop '{plant_loop_name}' not found"}

    # Search across all known component types
    component = _find_hvac_component_by_name(model, component_name)
    if component is None:
        return {"ok": False, "error": f"Component '{component_name}' not found"}

    try:
        success = plant_loop.addDemandBranchForComponent(component)
        if not success:
            return {"ok": False, "error": f"Failed to add '{component_name}' to demand side of '{plant_loop_name}'"}
    except Exception as e:
        return {"ok": False, "error": f"Error adding demand component: {e}"}

    return {
        "ok": True,
        "component": component_name,
        "plant_loop": plant_loop_name,
    }


def remove_demand_component(component_name: str, plant_loop_name: str) -> dict:
    """Remove a component from a plant loop's demand side."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    plant_loop = fetch_object(model, "PlantLoop", name=plant_loop_name)
    if plant_loop is None:
        return {"ok": False, "error": f"Plant loop '{plant_loop_name}' not found"}

    component = _find_hvac_component_by_name(model, component_name)
    if component is None:
        return {"ok": False, "error": f"Component '{component_name}' not found"}

    try:
        success = plant_loop.removeDemandBranchWithComponent(component)
        if not success:
            msg = f"Failed to remove '{component_name}' from demand side of '{plant_loop_name}'"
            return {"ok": False, "error": msg}
    except Exception as e:
        return {"ok": False, "error": f"Error removing demand component: {e}"}

    return {
        "ok": True,
        "component": component_name,
        "plant_loop": plant_loop_name,
    }


def _find_hvac_component_by_name(model, name: str):
    """Search common HVAC component types by name.

    Returns the typed OpenStudio object or None.
    """
    # List of (getter_method_name) to search
    search_types = [
        "getCoilCoolingWaters",
        "getCoilHeatingWaters",
        "getCoilCoolingDXSingleSpeeds",
        "getCoilHeatingDXSingleSpeeds",
        "getCoilCoolingFourPipeBeams",
        "getCoilHeatingFourPipeBeams",
        "getBoilerHotWaters",
        "getChillerElectricEIRs",
        "getCoolingTowerSingleSpeeds",
        "getWaterHeaterMixeds",
    ]
    for getter_name in search_types:
        getter = getattr(model, getter_name, None)
        if getter is None:
            continue
        for obj in getter():
            if hasattr(obj, "nameString") and obj.nameString() == name:
                return obj
    return None


def add_supply_equipment(
    plant_loop_name: str,
    equipment_type: str,
    equipment_name: str,
    properties: dict | None = None,
) -> dict:
    """Create equipment and add to plant loop supply side."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    if equipment_type not in SUPPLY_EQUIPMENT_TYPES:
        valid = list(SUPPLY_EQUIPMENT_TYPES.keys())
        return {"ok": False, "error": f"Unknown type '{equipment_type}'. Valid: {valid}"}

    plant_loop = fetch_object(model, "PlantLoop", name=plant_loop_name)
    if plant_loop is None:
        return {"ok": False, "error": f"Plant loop '{plant_loop_name}' not found"}

    type_def = SUPPLY_EQUIPMENT_TYPES[equipment_type]
    constructor = getattr(openstudio.model, type_def["constructor"])

    try:
        obj = constructor(model)
        obj.setName(equipment_name)
        errors = _apply_properties(obj, properties or {}, type_def)
        plant_loop.addSupplyBranchForComponent(obj)
    except Exception as e:
        return {"ok": False, "error": f"Failed to create {equipment_type}: {e}"}

    result = {
        "ok": len(errors) == 0,
        "equipment_name": equipment_name,
        "equipment_type": equipment_type,
        "plant_loop": plant_loop_name,
    }
    if errors:
        result["errors"] = errors
    return result


def remove_supply_equipment(plant_loop_name: str, equipment_name: str) -> dict:
    """Remove named equipment from plant loop supply side."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    plant_loop = fetch_object(model, "PlantLoop", name=plant_loop_name)
    if plant_loop is None:
        return {"ok": False, "error": f"Plant loop '{plant_loop_name}' not found"}

    # Look up typed object via getXByName — needed for removeSupplyBranchWithComponent
    # which requires HVACComponent, not generic ModelObject
    typed_obj = None
    for eq_type in SUPPLY_EQUIPMENT_TYPES:
        obj = fetch_object(model, SUPPLY_EQUIPMENT_TYPES[eq_type]["constructor"], name=equipment_name)
        if obj is not None:
            typed_obj = obj
            break

    if typed_obj is None:
        return {"ok": False, "error": f"Equipment '{equipment_name}' not found on supply side of '{plant_loop_name}'"}

    try:
        success = plant_loop.removeSupplyBranchWithComponent(typed_obj)
        if not success:
            return {"ok": False, "error": f"Failed to remove '{equipment_name}' from '{plant_loop_name}'"}
    except Exception as e:
        return {"ok": False, "error": f"Error removing equipment: {e}"}

    return {
        "ok": True,
        "removed": equipment_name,
        "plant_loop": plant_loop_name,
    }


def add_zone_equipment(
    zone_name: str,
    equipment_type: str,
    equipment_name: str,
    properties: dict | None = None,
) -> dict:
    """Create zone equipment and add to thermal zone."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    if equipment_type not in ZONE_EQUIPMENT_TYPES:
        valid = list(ZONE_EQUIPMENT_TYPES.keys())
        return {"ok": False, "error": f"Unknown type '{equipment_type}'. Valid: {valid}"}

    zone = fetch_object(model, "ThermalZone", name=zone_name)
    if zone is None:
        return {"ok": False, "error": f"Thermal zone '{zone_name}' not found"}

    type_def = ZONE_EQUIPMENT_TYPES[equipment_type]

    try:
        if type_def.get("needs_schedule_and_fan"):
            # Unit heater needs schedule + fan + heating coil
            always_on = model.alwaysOnDiscreteSchedule()
            fan = openstudio.model.FanConstantVolume(model, always_on)
            fan.setName(f"{equipment_name} Fan")
            htg_coil = openstudio.model.CoilHeatingElectric(model, always_on)
            htg_coil.setName(f"{equipment_name} Heating Coil")
            obj = openstudio.model.ZoneHVACUnitHeater(model, always_on, fan, htg_coil)
        else:
            constructor = getattr(openstudio.model, type_def["constructor"])
            obj = constructor(model)

        obj.setName(equipment_name)
        errors = _apply_properties(obj, properties or {}, type_def)
        obj.addToThermalZone(zone)
    except Exception as e:
        return {"ok": False, "error": f"Failed to create {equipment_type}: {e}"}

    result = {
        "ok": len(errors) == 0,
        "equipment_name": equipment_name,
        "equipment_type": equipment_type,
        "zone": zone_name,
    }
    if errors:
        result["errors"] = errors
    return result


def remove_zone_equipment(zone_name: str, equipment_name: str) -> dict:
    """Remove named equipment from thermal zone."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    zone = fetch_object(model, "ThermalZone", name=zone_name)
    if zone is None:
        return {"ok": False, "error": f"Thermal zone '{zone_name}' not found"}

    # Search zone equipment for matching name
    # zone.equipment() returns generic ModelObjects — use remove() not removeFromThermalZone()
    equipment_list = zone.equipment()
    target = None
    for equip in equipment_list:
        if hasattr(equip, "nameString") and equip.nameString() == equipment_name:
            target = equip
            break

    if target is None:
        return {"ok": False, "error": f"Equipment '{equipment_name}' not found in zone '{zone_name}'"}

    try:
        target.remove()
    except Exception as e:
        return {"ok": False, "error": f"Error removing equipment: {e}"}

    return {
        "ok": True,
        "removed": equipment_name,
        "zone": zone_name,
    }


def remove_all_zone_equipment(zone_names: list[str]) -> dict:
    """Remove ALL equipment from listed thermal zones in one call."""
    try:
        model = get_model()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    results: list[dict] = []
    total_removed = 0

    for zone_name in zone_names:
        zone = fetch_object(model, "ThermalZone", name=zone_name)
        if zone is None:
            results.append({"zone": zone_name, "error": "not found", "removed": []})
            continue

        removed_names = []
        equipment_list = list(zone.equipment())
        for equip in equipment_list:
            name = equip.nameString() if hasattr(equip, "nameString") else str(equip.name())
            try:
                equip.remove()
                removed_names.append(name)
            except Exception as e:
                results.append({"zone": zone_name, "error": f"Failed to remove {name}: {e}", "removed": removed_names})
                break
        else:
            results.append({"zone": zone_name, "removed": removed_names, "count": len(removed_names)})
            total_removed += len(removed_names)

    return {
        "ok": True,
        "total_removed": total_removed,
        "zones_processed": len(zone_names),
        "details": results,
    }
