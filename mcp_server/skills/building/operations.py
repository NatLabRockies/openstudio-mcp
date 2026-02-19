"""Building-level operations — building info, model summary, building stories.

Extraction patterns adapted from openstudio-toolkit osm_objects/building.py
and osm_objects/building_stories.py — using direct openstudio bindings.
"""
from __future__ import annotations

import math
from typing import Any

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import list_all_as_dicts, optional_name


def _safe_float(value) -> float | None:
    """Convert to float, returning None for NaN/Inf (JSON-incompatible)."""
    v = float(value)
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _extract_building_info(model, building) -> dict[str, Any]:
    """Extract building attributes to dict.

    Fields mirror OpenStudio-Toolkit's get_building_object_as_dict().
    """
    # Get optional attributes with safe access
    space_type = building.spaceType()
    default_construction_set = building.defaultConstructionSet()
    default_schedule_set = building.defaultScheduleSet()

    # Standards information (optional attributes)
    standards_building_type = None
    if building.standardsBuildingType().is_initialized():
        standards_building_type = building.standardsBuildingType().get()

    standards_number_of_stories = None
    if building.standardsNumberOfStories().is_initialized():
        standards_number_of_stories = int(building.standardsNumberOfStories().get())

    standards_number_of_above_ground_stories = None
    if building.standardsNumberOfAboveGroundStories().is_initialized():
        standards_number_of_above_ground_stories = int(building.standardsNumberOfAboveGroundStories().get())

    return {
        "handle": str(building.handle()),
        "name": building.nameString(),
        "space_type": optional_name(space_type),
        "default_construction_set": optional_name(default_construction_set),
        "default_schedule_set": optional_name(default_schedule_set),
        "floor_area_m2": float(building.floorArea()),
        "conditioned_floor_area_m2": float(building.conditionedFloorArea()),
        "exterior_surface_area_m2": float(building.exteriorSurfaceArea()),
        "exterior_wall_area_m2": float(building.exteriorWallArea()),
        "air_volume_m3": float(building.airVolume()),
        "number_of_people": _safe_float(building.numberOfPeople()),
        "people_per_floor_area": _safe_float(building.peoplePerFloorArea()),
        "floor_area_per_person_m2": _safe_float(building.floorAreaPerPerson()),
        "lighting_power_w": _safe_float(building.lightingPower()),
        "lighting_power_per_floor_area_w_m2": _safe_float(building.lightingPowerPerFloorArea()),
        "electric_equipment_power_w": _safe_float(building.electricEquipmentPower()),
        "electric_equipment_power_per_floor_area_w_m2": _safe_float(building.electricEquipmentPowerPerFloorArea()),
        "gas_equipment_power_w": _safe_float(building.gasEquipmentPower()),
        "gas_equipment_power_per_floor_area_w_m2": _safe_float(building.gasEquipmentPowerPerFloorArea()),
        "infiltration_design_flow_rate_m3_s": _safe_float(building.infiltrationDesignFlowRate()),
        "infiltration_design_flow_per_exterior_surface_area": _safe_float(building.infiltrationDesignFlowPerExteriorSurfaceArea()),
        "infiltration_design_flow_per_exterior_wall_area": _safe_float(building.infiltrationDesignFlowPerExteriorWallArea()),
        "north_axis_deg": float(building.northAxis()),
        "standards_building_type": standards_building_type,
        "standards_number_of_stories": standards_number_of_stories,
        "standards_number_of_above_ground_stories": standards_number_of_above_ground_stories,
    }


def _extract_building_story(model, story) -> dict[str, Any]:
    """Extract building story attributes to dict.

    Fields mirror OpenStudio-Toolkit's get_building_story_object_as_dict().
    """
    return {
        "handle": str(story.handle()),
        "name": story.nameString(),
        "nominal_z_coordinate_m": float(story.nominalZCoordinate().get()) if story.nominalZCoordinate().is_initialized() else None,
        "nominal_floor_to_floor_height_m": float(story.nominalFloortoFloorHeight().get()) if story.nominalFloortoFloorHeight().is_initialized() else None,
        "nominal_floor_to_ceiling_height_m": float(story.nominalFloortoCeilingHeight().get()) if story.nominalFloortoCeilingHeight().is_initialized() else None,
        "default_construction_set": optional_name(story.defaultConstructionSet()),
        "default_schedule_set": optional_name(story.defaultScheduleSet()),
        "rendering_color": story.renderingColor().name() if story.renderingColor().is_initialized() else None,
        "num_spaces": len(story.spaces()),
    }


def get_building_info() -> dict[str, Any]:
    """Get detailed information about the building object.

    Returns building-level attributes like floor area, people density,
    lighting power, equipment power, infiltration rates, etc.
    """
    try:
        model = get_model()
        building = model.getBuilding()

        return {
            "ok": True,
            "building": _extract_building_info(model, building)
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get building info: {e}"}


def get_model_summary() -> dict[str, Any]:
    """Get a high-level summary of the model.

    Returns counts of major object types: spaces, zones, surfaces,
    constructions, schedules, HVAC systems, etc.
    """
    try:
        model = get_model()
        building = model.getBuilding()

        summary = {
            "building_name": building.nameString(),
            "floor_area_m2": float(building.floorArea()),
            "conditioned_floor_area_m2": float(building.conditionedFloorArea()),

            # Spaces and zones
            "spaces": len(model.getSpaces()),
            "building_stories": len(model.getBuildingStorys()),
            "thermal_zones": len(model.getThermalZones()),

            # Geometry
            "surfaces": len(model.getSurfaces()),
            "sub_surfaces": len(model.getSubSurfaces()),
            "shading_surfaces": len(model.getShadingSurfaces()),

            # Constructions
            "materials": len(model.getMaterials()),
            "constructions": len(model.getConstructions()),
            "construction_sets": len(model.getDefaultConstructionSets()),

            # Loads
            "space_types": len(model.getSpaceTypes()),
            "people": len(model.getPeoples()),
            "lights": len(model.getLightss()),
            "electric_equipment": len(model.getElectricEquipments()),
            "gas_equipment": len(model.getGasEquipments()),

            # Schedules
            "schedule_rulesets": len(model.getScheduleRulesets()),
            "schedule_constants": len(model.getScheduleConstants()),

            # HVAC
            "air_loops": len(model.getAirLoopHVACs()),
            "plant_loops": len(model.getPlantLoops()),
            "zone_hvac_equipment": len(model.getZoneHVACComponents()),
        }

        return {
            "ok": True,
            "summary": summary
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get model summary: {e}"}


def list_building_stories() -> dict[str, Any]:
    """List all building stories in the model.

    Returns array of building story objects with name, z-coordinate,
    floor-to-floor height, and number of spaces.
    """
    try:
        model = get_model()
        stories = list_all_as_dicts(model, "getBuildingStorys", _extract_building_story)

        return {
            "ok": True,
            "count": len(stories),
            "building_stories": stories
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list building stories: {e}"}
