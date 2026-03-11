"""Spaces and thermal zones operations.

Extraction patterns adapted from openstudio-toolkit osm_objects/spaces.py
and osm_objects/thermal_zones.py — using direct openstudio bindings.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import (
    build_list_response,
    fetch_object,
    list_paginated,
    optional_name,
)


def _extract_space(model, space, detailed: bool = True) -> dict[str, Any]:
    """Extract space attributes to dict.

    When detailed=False, returns only name, floor_area_m2, thermal_zone.
    """
    result = {
        "handle": str(space.handle()),
        "name": space.nameString(),
        "floor_area_m2": float(space.floorArea()),
        "thermal_zone": optional_name(space.thermalZone()),
    }
    if not detailed:
        return result
    result.update({
        "space_type": optional_name(space.spaceType()),
        "building_story": optional_name(space.buildingStory()),
        "default_construction_set": optional_name(space.defaultConstructionSet()),
        "default_schedule_set": optional_name(space.defaultScheduleSet()),
        "volume_m3": float(space.volume()),
        "ceiling_height_m": float(space.ceilingHeight()),
        "direction_of_relative_north_deg": float(space.directionofRelativeNorth()),
        "x_origin_m": float(space.xOrigin()),
        "y_origin_m": float(space.yOrigin()),
        "z_origin_m": float(space.zOrigin()),
        "part_of_total_floor_area": space.partofTotalFloorArea(),
        "num_surfaces": len(space.surfaces()),
        "num_people": len(space.people()),
        "num_lights": len(space.lights()),
        "num_electric_equipment": len(space.electricEquipment()),
        "num_gas_equipment": len(space.gasEquipment()),
    })
    return result


def _extract_thermal_zone(model, zone, detailed: bool = True) -> dict[str, Any]:
    """Extract thermal zone attributes to dict.

    When detailed=False, returns only name, floor_area_m2, num_equipment.
    """
    num_equipment = len(zone.equipment())
    result = {
        "handle": str(zone.handle()),
        "name": zone.nameString(),
        "floor_area_m2": float(zone.floorArea()),
        "num_equipment": num_equipment,
    }
    if not detailed:
        return result

    # Get thermostat info
    thermostat_name = None
    heating_setpoint_schedule = None
    cooling_setpoint_schedule = None

    if zone.thermostatSetpointDualSetpoint().is_initialized():
        thermostat = zone.thermostatSetpointDualSetpoint().get()
        thermostat_name = thermostat.nameString()
        heating_setpoint_schedule = optional_name(thermostat.heatingSetpointTemperatureSchedule())
        cooling_setpoint_schedule = optional_name(thermostat.coolingSetpointTemperatureSchedule())

    # Get air loop if connected
    air_loop_name = None
    if zone.airLoopHVAC().is_initialized():
        air_loop_name = zone.airLoopHVAC().get().nameString()

    result.update({
        "thermostat": thermostat_name,
        "heating_setpoint_schedule": heating_setpoint_schedule,
        "cooling_setpoint_schedule": cooling_setpoint_schedule,
        "air_loop_hvac": air_loop_name,
    })
    return result


def list_spaces(
    detailed: bool = False,
    thermal_zone_name: str | None = None,
    building_story_name: str | None = None,
    space_type_name: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List spaces with server-side filtering and pagination.

    Common filters:
    - Spaces on a story: building_story_name="Floor 1"
    - Spaces in a zone: thermal_zone_name="Zone 1"
    """
    try:
        model = get_model()

        filt = None
        if thermal_zone_name or building_story_name or space_type_name:
            def filt(m, s):
                if thermal_zone_name and optional_name(s.thermalZone()) != thermal_zone_name:
                    return False
                if building_story_name and optional_name(s.buildingStory()) != building_story_name:
                    return False
                if space_type_name and optional_name(s.spaceType()) != space_type_name:
                    return False
                return True

        items, total = list_paginated(
            model, "getSpaces", _extract_space,
            detailed=detailed, max_results=max_results, obj_filter_fn=filt,
        )
        return build_list_response("spaces", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list spaces: {e}"}


def get_space_details(space_name: str) -> dict[str, Any]:
    """Get detailed information about a specific space."""
    try:
        model = get_model()
        space = fetch_object(model, "Space", name=space_name)

        if space is None:
            return {"ok": False, "error": f"Space '{space_name}' not found"}

        return {
            "ok": True,
            "space": _extract_space(model, space),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get space details: {e}"}


def list_thermal_zones(
    detailed: bool = False,
    air_loop_name: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List thermal zones with server-side filtering and pagination.

    Common filters:
    - Zones on an air loop: air_loop_name="DOAS"
    """
    try:
        model = get_model()

        filt = None
        if air_loop_name:
            air_loop = fetch_object(model, "AirLoopHVAC", name=air_loop_name)
            if air_loop is None:
                return {"ok": False, "error": f"Air loop '{air_loop_name}' not found"}
            allowed = {z.nameString() for z in air_loop.thermalZones()}
            def filt(m, z):
                return z.nameString() in allowed

        items, total = list_paginated(
            model, "getThermalZones", _extract_thermal_zone,
            detailed=detailed, max_results=max_results, obj_filter_fn=filt,
        )
        return build_list_response("thermal_zones", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list thermal zones: {e}"}


def get_thermal_zone_details(zone_name: str) -> dict[str, Any]:
    """Get detailed information about a specific thermal zone."""
    try:
        model = get_model()
        zone = fetch_object(model, "ThermalZone", name=zone_name)

        if zone is None:
            return {"ok": False, "error": f"Thermal zone '{zone_name}' not found"}

        return {
            "ok": True,
            "thermal_zone": _extract_thermal_zone(model, zone),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get thermal zone details: {e}"}


def create_space(name: str, building_story_name: str | None = None,
                space_type_name: str | None = None) -> dict[str, Any]:
    """Create a new space in the model.

    Args:
        name: Name for the new space
        building_story_name: Optional name of building story to assign
        space_type_name: Optional name of space type to assign

    Returns:
        dict with ok=True and space details, or ok=False and error message
    """
    try:
        model = get_model()

        # Create space
        space = openstudio.model.Space(model)
        space.setName(name)

        # Set optional relationships
        if building_story_name:
            story = fetch_object(model, "BuildingStory", name=building_story_name)
            if story is None:
                return {"ok": False, "error": f"Building story '{building_story_name}' not found"}
            space.setBuildingStory(story)

        if space_type_name:
            space_type = fetch_object(model, "SpaceType", name=space_type_name)
            if space_type is None:
                return {"ok": False, "error": f"Space type '{space_type_name}' not found"}
            space.setSpaceType(space_type)

        # Extract and return
        result = _extract_space(model, space)
        return {"ok": True, "space": result}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create space: {e}"}


def create_thermal_zone(name: str, space_names: list[str] | None = None) -> dict[str, Any]:
    """Create a new thermal zone in the model.

    Args:
        name: Name for the new thermal zone
        space_names: Optional list of space names to assign to this zone

    Returns:
        dict with ok=True and thermal_zone details, or ok=False and error message
    """
    try:
        model = get_model()

        # Create thermal zone
        thermal_zone = openstudio.model.ThermalZone(model)
        thermal_zone.setName(name)

        # Assign spaces if provided
        if space_names:
            for space_name in space_names:
                space = fetch_object(model, "Space", name=space_name)
                if space is None:
                    return {"ok": False, "error": f"Space '{space_name}' not found"}
                space.setThermalZone(thermal_zone)

        # Extract and return
        result = _extract_thermal_zone(model, thermal_zone)
        return {"ok": True, "thermal_zone": result}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create thermal zone: {e}"}
