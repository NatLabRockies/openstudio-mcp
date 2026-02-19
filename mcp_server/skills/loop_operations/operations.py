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
