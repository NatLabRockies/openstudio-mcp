"""Object management operations — delete, rename, list by type.

Explicit type dispatch — no dynamic getattr. Every supported type is listed
in MANAGED_TYPES with its getter method name.
"""
from __future__ import annotations

from typing import Any

from mcp_server.model_manager import get_model

# Each entry: OS type key -> model getter method (returns collection)
# The getter is model.get<Type>s() for most types.
MANAGED_TYPES: dict[str, str] = {
    # Spaces & zones
    "Space": "getSpaces",
    "ThermalZone": "getThermalZones",
    "BuildingStory": "getBuildingStorys",
    # HVAC loops
    "AirLoopHVAC": "getAirLoopHVACs",
    "PlantLoop": "getPlantLoops",
    # Coils (from component_properties registry)
    "CoilHeatingElectric": "getCoilHeatingElectrics",
    "CoilHeatingGas": "getCoilHeatingGass",  # OS pluralisation
    "CoilHeatingWater": "getCoilHeatingWaters",
    "CoilHeatingDXSingleSpeed": "getCoilHeatingDXSingleSpeeds",
    "CoilCoolingDXSingleSpeed": "getCoilCoolingDXSingleSpeeds",
    "CoilCoolingDXTwoSpeed": "getCoilCoolingDXTwoSpeeds",
    "CoilCoolingWater": "getCoilCoolingWaters",
    # Plant equipment
    "BoilerHotWater": "getBoilerHotWaters",
    "ChillerElectricEIR": "getChillerElectricEIRs",
    "CoolingTowerSingleSpeed": "getCoolingTowerSingleSpeeds",
    # Fans
    "FanConstantVolume": "getFanConstantVolumes",
    "FanVariableVolume": "getFanVariableVolumes",
    "FanOnOff": "getFanOnOffs",
    # Pumps
    "PumpVariableSpeed": "getPumpVariableSpeeds",
    "PumpConstantSpeed": "getPumpConstantSpeeds",
    # Loads
    "People": "getPeoples",
    "Lights": "getLightss",
    "ElectricEquipment": "getElectricEquipments",
    "GasEquipment": "getGasEquipments",
    "SpaceInfiltrationDesignFlowRate": "getSpaceInfiltrationDesignFlowRates",
    # Constructions & materials
    "Construction": "getConstructions",
    "StandardOpaqueMaterial": "getStandardOpaqueMaterials",
    # Schedules
    "ScheduleRuleset": "getScheduleRulesets",
}


def _find_object_by_name(model, name: str, object_type: str | None = None):
    """Find a named object. If type given, search only that type.

    Returns (object, type_key) or (None, None).
    """
    types_to_search = (
        {object_type: MANAGED_TYPES[object_type]}
        if object_type and object_type in MANAGED_TYPES
        else MANAGED_TYPES
    )
    for type_key, getter_name in types_to_search.items():
        getter = getattr(model, getter_name, None)
        if getter is None:
            continue
        for obj in getter():
            if obj.nameString() == name:
                return obj, type_key
    return None, None


def delete_object(
    object_name: str,
    object_type: str | None = None,
) -> dict[str, Any]:
    """Delete a named object from the model."""
    try:
        model = get_model()

        if object_type and object_type not in MANAGED_TYPES:
            return {
                "ok": False,
                "error": f"Unsupported type '{object_type}'. Supported: {sorted(MANAGED_TYPES.keys())}",
            }

        obj, found_type = _find_object_by_name(model, object_name, object_type)
        if obj is None:
            return {"ok": False, "error": f"Object '{object_name}' not found"}

        # Warn about child objects for cascading types
        warnings = []
        if found_type == "Space":
            n_surfaces = len(obj.surfaces())
            n_loads = len(obj.people()) + len(obj.lights()) + len(obj.electricEquipment()) + len(obj.gasEquipment())
            if n_surfaces > 0:
                warnings.append(f"{n_surfaces} surfaces will also be removed")
            if n_loads > 0:
                warnings.append(f"{n_loads} load objects will also be removed")

        obj.remove()
        result: dict[str, Any] = {
            "ok": True,
            "deleted": object_name,
            "type": found_type,
        }
        if warnings:
            result["warnings"] = warnings
        return result

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to delete object: {e}"}


def rename_object(
    object_name: str,
    new_name: str,
    object_type: str | None = None,
) -> dict[str, Any]:
    """Rename a named object in the model."""
    try:
        model = get_model()

        if object_type and object_type not in MANAGED_TYPES:
            return {
                "ok": False,
                "error": f"Unsupported type '{object_type}'. Supported: {sorted(MANAGED_TYPES.keys())}",
            }

        obj, found_type = _find_object_by_name(model, object_name, object_type)
        if obj is None:
            return {"ok": False, "error": f"Object '{object_name}' not found"}

        obj.setName(new_name)
        return {
            "ok": True,
            "old_name": object_name,
            "new_name": obj.nameString(),
            "type": found_type,
        }

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to rename object: {e}"}


def list_model_objects(object_type: str) -> dict[str, Any]:
    """List all objects of a given type."""
    try:
        model = get_model()

        if object_type not in MANAGED_TYPES:
            return {
                "ok": False,
                "error": f"Unsupported type '{object_type}'. Supported: {sorted(MANAGED_TYPES.keys())}",
            }

        getter_name = MANAGED_TYPES[object_type]
        getter = getattr(model, getter_name, None)
        if getter is None:
            return {"ok": False, "error": f"Model has no getter '{getter_name}'"}

        objects = getter()
        items = [
            {"name": obj.nameString(), "handle": str(obj.handle())}
            for obj in objects
        ]
        items.sort(key=lambda d: d["name"])
        return {"ok": True, "type": object_type, "count": len(items), "objects": items}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list objects: {e}"}
