"""Space types operations — templates for space characteristics.

Extraction patterns adapted from openstudio-toolkit osm_objects/space_types.py
— using direct openstudio bindings.
"""
from __future__ import annotations

from typing import Any

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import build_list_response, fetch_object, list_all_as_dicts, optional_name

# Max nested load items in get_space_type_details before truncation
_MAX_NESTED = 10


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


def _cap_list(items: list, max_items: int = _MAX_NESTED) -> list:
    """Cap a list and append truncation hint if needed."""
    if len(items) <= max_items:
        return items
    result = items[:max_items]
    result.append({"_truncated": f"...and {len(items) - max_items} more"})
    return result


def list_space_types(max_results: int | None = 10) -> dict[str, Any]:
    """List all space types in the model."""
    try:
        model = get_model()
        space_types = list_all_as_dicts(model, "getSpaceTypes", _extract_space_type)
        total = len(space_types)
        if max_results is not None:
            space_types = space_types[:max_results]
        return build_list_response("space_types", space_types, total, max_results)
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

        # Brief nested loads: [{name, schedule}] capped at _MAX_NESTED
        people_loads = []
        for people in space_type.people():
            people_loads.append({
                "name": people.nameString(),
                "schedule": optional_name(people.activityLevelSchedule()),
            })

        lighting_loads = []
        for lights in space_type.lights():
            lighting_loads.append({
                "name": lights.nameString(),
                "schedule": optional_name(lights.schedule()),
            })

        electric_equipment_loads = []
        for equipment in space_type.electricEquipment():
            electric_equipment_loads.append({
                "name": equipment.nameString(),
                "schedule": optional_name(equipment.schedule()),
            })

        gas_equipment_loads = []
        for equipment in space_type.gasEquipment():
            gas_equipment_loads.append({
                "name": equipment.nameString(),
                "schedule": optional_name(equipment.schedule()),
            })

        # Spaces using this type — names only, capped
        spaces = [space.nameString() for space in space_type.spaces()]

        result["people_loads"] = _cap_list(people_loads)
        result["lighting_loads"] = _cap_list(lighting_loads)
        result["electric_equipment_loads"] = _cap_list(electric_equipment_loads)
        result["gas_equipment_loads"] = _cap_list(gas_equipment_loads)
        result["spaces"] = _cap_list(spaces)

        return {
            "ok": True,
            "space_type": result,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get space type details: {e}"}
