"""Space types operations — templates for space characteristics.

Extraction patterns adapted from openstudio-toolkit osm_objects/space_types.py
— using direct openstudio bindings.
"""
from __future__ import annotations

from typing import Any

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object, list_all_as_dicts, optional_name


def _extract_space_type(model, space_type) -> dict[str, Any]:
    """Extract space type attributes to dict."""
    return {
        "handle": str(space_type.handle()),
        "name": space_type.nameString(),
        "default_construction_set": optional_name(space_type.defaultConstructionSet()),
        "default_schedule_set": optional_name(space_type.defaultScheduleSet()),
        "rendering_color": optional_name(space_type.renderingColor()),
        "standards_building_type": space_type.standardsBuildingType().get() if space_type.standardsBuildingType().is_initialized() else None,
        "standards_space_type": space_type.standardsSpaceType().get() if space_type.standardsSpaceType().is_initialized() else None,
        "num_people": len(space_type.people()),
        "num_lights": len(space_type.lights()),
        "num_electric_equipment": len(space_type.electricEquipment()),
        "num_gas_equipment": len(space_type.gasEquipment()),
        "num_spaces_using_this_type": len(space_type.spaces()),
    }


def list_space_types() -> dict[str, Any]:
    """List all space types in the model."""
    try:
        model = get_model()
        space_types = list_all_as_dicts(model, "getSpaceTypes", _extract_space_type)
        return {
            "ok": True,
            "count": len(space_types),
            "space_types": space_types
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list space types: {e}"}


def get_space_type_details(space_type_name: str) -> dict[str, Any]:
    """Get detailed information about a specific space type."""
    try:
        model = get_model()
        space_type = fetch_object(model, "SpaceType", name=space_type_name)

        if space_type is None:
            return {"ok": False, "error": f"Space type '{space_type_name}' not found"}

        # Get basic info
        result = _extract_space_type(model, space_type)

        # Add detailed load information
        people_loads = []
        for people in space_type.people():
            load_info = {
                "name": people.nameString(),
                "activity_level_schedule": optional_name(people.activityLevelSchedule()),
            }
            try:
                if hasattr(people, 'peopleDefinition') and people.peopleDefinition().is_initialized():
                    definition = people.peopleDefinition().get()
                    if hasattr(definition, 'peopleperSpaceFloorArea') and definition.peopleperSpaceFloorArea().is_initialized():
                        load_info["people_per_floor_area"] = float(definition.peopleperSpaceFloorArea().get())
            except Exception:
                pass
            people_loads.append(load_info)

        lighting_loads = []
        for lights in space_type.lights():
            load_info = {
                "name": lights.nameString(),
                "schedule": optional_name(lights.schedule()),
            }
            try:
                if hasattr(lights, 'lightsDefinition') and lights.lightsDefinition().is_initialized():
                    definition = lights.lightsDefinition().get()
                    if hasattr(definition, 'wattsperSpaceFloorArea') and definition.wattsperSpaceFloorArea().is_initialized():
                        load_info["watts_per_floor_area_w_m2"] = float(definition.wattsperSpaceFloorArea().get())
            except Exception:
                pass
            lighting_loads.append(load_info)

        electric_equipment_loads = []
        for equipment in space_type.electricEquipment():
            load_info = {
                "name": equipment.nameString(),
                "schedule": optional_name(equipment.schedule()),
            }
            try:
                if hasattr(equipment, 'electricEquipmentDefinition') and equipment.electricEquipmentDefinition().is_initialized():
                    definition = equipment.electricEquipmentDefinition().get()
                    if hasattr(definition, 'wattsperSpaceFloorArea') and definition.wattsperSpaceFloorArea().is_initialized():
                        load_info["watts_per_floor_area_w_m2"] = float(definition.wattsperSpaceFloorArea().get())
            except Exception:
                pass
            electric_equipment_loads.append(load_info)

        gas_equipment_loads = []
        for equipment in space_type.gasEquipment():
            load_info = {
                "name": equipment.nameString(),
                "schedule": optional_name(equipment.schedule()),
            }
            try:
                if hasattr(equipment, 'gasEquipmentDefinition') and equipment.gasEquipmentDefinition().is_initialized():
                    definition = equipment.gasEquipmentDefinition().get()
                    if hasattr(definition, 'wattsperSpaceFloorArea') and definition.wattsperSpaceFloorArea().is_initialized():
                        load_info["watts_per_floor_area_w_m2"] = float(definition.wattsperSpaceFloorArea().get())
            except Exception:
                pass
            gas_equipment_loads.append(load_info)

        # Add spaces using this type
        spaces = []
        for space in space_type.spaces():
            spaces.append(space.nameString())

        result["people_loads"] = people_loads
        result["lighting_loads"] = lighting_loads
        result["electric_equipment_loads"] = electric_equipment_loads
        result["gas_equipment_loads"] = gas_equipment_loads
        result["spaces"] = spaces

        return {
            "ok": True,
            "space_type": result
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get space type details: {e}"}
