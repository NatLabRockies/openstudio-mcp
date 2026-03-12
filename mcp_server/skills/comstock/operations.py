"""ComStock measure operations — discovery and high-leverage wrappers.

Provides:
- list_comstock_measures: scan COMSTOCK_MEASURES_DIR for available measures
- create_bar_building: wrapper around create_bar_from_building_type_ratios measure
- create_typical_building: wrapper around create_typical_building_from_model measure
- create_new_building: convenience chain (weather → bar → typical)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import openstudio

from mcp_server import model_manager
from mcp_server.config import RUN_ROOT
from mcp_server.model_manager import get_model
from mcp_server.skills.measures.operations import apply_measure
from mcp_server.stdout_suppression import suppress_openstudio_warnings

# Category classification for ComStock measures
_BASELINE_PREFIXES = (
    "set_wall_template", "set_roof_template", "set_hvac_template",
    "set_interior_lighting_template", "set_exterior_lighting_template",
    "set_service_water_heating_template", "set_electric_equipment_template",
    "set_gas_equipment_template", "set_refrigeration_template",
    "set_elevator_template", "set_transformer_template",
    "replace_baseline_windows",
)
_SETUP_NAMES = {
    "create_typical_building_from_model",
    "create_bar_from_building_type_ratios",
    "simulation_settings",
    "ChangeBuildingLocation",
    "change_building_location",
    "prototype_space_type_assignment",
    "hardsize_model",
    "add_thermostats",
    "create_deer_prototype_building",
}


def _categorize(measure_name: str) -> str:
    """Categorize a measure by its directory name."""
    if measure_name in _SETUP_NAMES:
        return "setup"
    if measure_name.startswith("upgrade_"):
        return "upgrade"
    for prefix in _BASELINE_PREFIXES:
        if measure_name.startswith(prefix):
            return "baseline"
    return "other"


def list_comstock_measures(category: str | None = None) -> dict[str, Any]:
    """List available ComStock measures with names, descriptions, paths.

    Args:
        category: Optional filter — "baseline", "upgrade", "setup", "other", or None for all
    """
    measures_dir = Path(os.environ.get("COMSTOCK_MEASURES_DIR", "/opt/comstock-measures"))
    if not measures_dir.is_dir():
        return {
            "ok": False,
            "error": f"ComStock measures directory not found: {measures_dir}. "
                     "Ensure COMSTOCK_MEASURES_DIR is set and measures are installed.",
        }

    results = []
    for d in sorted(measures_dir.iterdir()):
        if not d.is_dir() or not (d / "measure.rb").is_file():
            continue
        cat = _categorize(d.name)
        if category and cat != category:
            continue

        # Read BCLMeasure for metadata
        entry: dict[str, Any] = {
            "name": d.name,
            "category": cat,
        }
        try:
            with suppress_openstudio_warnings():
                bcl = openstudio.BCLMeasure(openstudio.toPath(str(d)))
            entry["display_name"] = bcl.name()
            entry["description"] = bcl.description()[:200]
            entry["num_arguments"] = len(bcl.arguments())
        except Exception:
            # If BCLMeasure can't parse it, still list it with basic info
            entry["display_name"] = d.name
            entry["description"] = ""
            entry["num_arguments"] = -1

        results.append(entry)

    return {"ok": True, "count": len(results), "measures": results}


# --- Argument mapping for create_typical_building_from_model ---
# Maps our Python kwarg names to the measure's argument names.
_TYPICAL_ARG_MAP = {
    "template": "template",
    "system_type": "system_type",
    "climate_zone": "climate_zone",
    "htg_src": "htg_src",
    "clg_src": "clg_src",
    "swh_src": "swh_src",
    "add_constructions": "add_constructions",
    "add_space_type_loads": "add_space_type_loads",
    "add_hvac": "add_hvac",
    "add_swh": "add_swh",
    "add_exterior_lights": "add_exterior_lights",
    "add_thermostat": "add_thermostat",
    "remove_objects": "remove_objects",
}


def create_typical_building(
    template: str = "90.1-2019",
    building_type: str = "SmallOffice",
    system_type: str = "Inferred",
    climate_zone: str = "Lookup From Model",
    htg_src: str = "NaturalGas",
    clg_src: str = "Electricity",
    swh_src: str = "Inferred",
    add_constructions: bool = True,
    add_space_type_loads: bool = True,
    add_hvac: bool = True,
    add_swh: bool = True,
    add_exterior_lights: bool = True,
    add_thermostat: bool = True,
    remove_objects: bool = True,
) -> dict[str, Any]:
    """Create a typical building from the loaded model using ComStock measure.

    Wraps the create_typical_building_from_model measure which adds
    constructions, loads, HVAC, schedules, and SWH to a model that
    already has geometry and space types assigned.

    If the model's building or space types lack standardsBuildingType,
    this tool sets it from building_type before running the measure.

    Args:
        template: ASHRAE standard year — "90.1-2019", "90.1-2016", "90.1-2013", etc.
        building_type: DOE prototype building type — "SmallOffice", "LargeOffice",
            "RetailStandalone", "PrimarySchool", "Hospital", etc. Sets
            standardsBuildingType on building and space types if not already set.
        system_type: HVAC system type — "Inferred" lets the measure pick based on area/stories
        climate_zone: ASHRAE climate zone — "Lookup From Model" or e.g. "ASHRAE 169-2013-4A"
        htg_src: Heating fuel — "NaturalGas", "Electricity", "DistrictHeating", etc.
        clg_src: Cooling fuel — "Electricity" or "DistrictCooling"
        swh_src: Service water heating fuel — "Inferred", "NaturalGas", "Electricity"
        add_constructions: Add standard constructions
        add_space_type_loads: Add people, lights, equipment loads
        add_hvac: Add HVAC system
        add_swh: Add service water heating
        add_exterior_lights: Add exterior lighting
        add_thermostat: Add thermostat schedules
        remove_objects: Remove existing objects before adding new ones
    """
    measures_dir = Path(os.environ.get("COMSTOCK_MEASURES_DIR", "/opt/comstock-measures"))
    measure_path = measures_dir / "create_typical_building_from_model"
    if not measure_path.is_dir():
        return {
            "ok": False,
            "error": f"Measure not found: {measure_path}. "
                     "Ensure ComStock measures are installed.",
        }

    # Ensure building and space types have standardsBuildingType set.
    # The measure fails with nil error if these are missing.
    try:
        model = get_model()
        bldg = model.getBuilding()
        # Set building-level standards info if missing
        if not bldg.standardsBuildingType().is_initialized():
            bldg.setStandardsBuildingType(building_type)
        if not bldg.standardsNumberOfStories().is_initialized():
            bldg.setStandardsNumberOfStories(len(model.getBuildingStorys()))
        # Set space type standards info if missing
        for st in model.getSpaceTypes():
            if not st.standardsBuildingType().is_initialized():
                st.setStandardsBuildingType(building_type)
            if not st.standardsSpaceType().is_initialized():
                # Default space type for the building type
                st.setStandardsSpaceType("WholeBuilding")
        # Set climate zone on model — always override any existing value.
        # The measure's infiltration step reads it from the model object.
        # change_building_location may have set a zone from .stat file;
        # the explicit arg here (e.g. "2A") is more authoritative and
        # avoids openstudio-standards pump sizing bugs.
        if climate_zone != "Lookup From Model":
            czs = model.getClimateZones()
            # Parse "ASHRAE 169-2013-4A" → "4A"
            cz_value = climate_zone.rsplit("-", maxsplit=1)[-1] if "-" in climate_zone else climate_zone
            czs.setClimateZone("ASHRAE", cz_value)
    except RuntimeError as e:
        return {"ok": False, "error": f"Failed to prepare model: {e}"}

    # Build arguments dict from kwargs, mapping to measure arg names
    local_vars = {
        "template": template,
        "system_type": system_type,
        "climate_zone": climate_zone,
        "htg_src": htg_src,
        "clg_src": clg_src,
        "swh_src": swh_src,
        "add_constructions": add_constructions,
        "add_space_type_loads": add_space_type_loads,
        "add_hvac": add_hvac,
        "add_swh": add_swh,
        "add_exterior_lights": add_exterior_lights,
        "add_thermostat": add_thermostat,
        "remove_objects": remove_objects,
    }
    arguments = {}
    for py_name, measure_name in _TYPICAL_ARG_MAP.items():
        val = local_vars[py_name]
        # Convert bools to strings for OSW
        if isinstance(val, bool):
            arguments[measure_name] = str(val).lower()
        else:
            arguments[measure_name] = str(val)

    # ComStock measures use openstudio-standards from the CLI's built-in gems.
    # The bundled gems (--bundle) load a different standards version that has
    # a pump sizing bug, so skip the bundle for ComStock measures.
    result = apply_measure(measure_dir=str(measure_path), arguments=arguments,
                           use_bundle=False)

    # Enhance the response with context about what was applied
    if result.get("ok"):
        result["template"] = template
        result["system_type"] = system_type
        result["climate_zone"] = climate_zone

    return result


# --- Argument mapping for create_bar_from_building_type_ratios ---
# Maps our Python kwarg names to the measure's argument names.
_BAR_ARG_MAP = {
    "building_type": "bldg_type_a",
    "total_bldg_floor_area": "total_bldg_floor_area",
    "num_stories_above_grade": "num_stories_above_grade",
    "num_stories_below_grade": "num_stories_below_grade",
    "floor_height": "floor_height",
    "template": "template",
    "climate_zone": "climate_zone",
    "wwr": "wwr",
    "ns_to_ew_ratio": "ns_to_ew_ratio",
    "building_rotation": "building_rotation",
    "bar_division_method": "bar_division_method",
    "story_multiplier": "story_multiplier",
    "bar_width": "bar_width",
}


def _read_climate_zone_from_model() -> str | None:
    """Read ASHRAE climate zone from the in-memory model."""
    model = get_model()
    czs = model.getClimateZones()
    ashrae_czs = czs.getClimateZones("ASHRAE")
    if len(ashrae_czs) > 0:
        val = ashrae_czs[0].value()
        # If just a number (e.g. "2"), add "A" (humid) as default
        if val.isdigit():
            return val + "A"
        return val
    return None


def _expand_climate_zone(cz: str) -> str:
    """Expand short climate zone codes to full Choice values.

    The create_bar measure uses Choice args, so "4A" must become
    "ASHRAE 169-2013-4A". Pass-through for already-full strings
    and special values like "Lookup From Stat File".
    """
    # Already a full string or special value
    if cz.startswith(("ASHRAE", "CEC")) or "Lookup" in cz:
        return cz
    # Short code like "4A", "2A", "7" — expand to ASHRAE format
    return f"ASHRAE 169-2013-{cz}"



def _create_empty_model() -> Path:
    """Create an empty OSM, save it, and load it as current model.

    Returns the path to the saved OSM file.
    """
    run_dir = RUN_ROOT / "examples" / "bar_building"
    run_dir.mkdir(parents=True, exist_ok=True)
    osm_path = run_dir / "empty.osm"
    with suppress_openstudio_warnings():
        empty = openstudio.model.Model()
        empty.save(str(osm_path), True)
    model_manager.load_model(osm_path)
    return osm_path


def create_bar_building(
    building_type: str = "SmallOffice",
    total_bldg_floor_area: float = 10000,
    num_stories_above_grade: float = 1.0,
    num_stories_below_grade: int = 0,
    floor_height: float = 0,
    template: str = "90.1-2019",
    climate_zone: str = "Lookup From Stat File",
    wwr: float = 0,
    ns_to_ew_ratio: float = 0,
    building_rotation: float = 0,
    bar_division_method: str = "Multiple Space Types - Individual Stories Sliced",
    story_multiplier: str = "Basements Ground Mid Top",
    bar_width: float = 0,
) -> dict[str, Any]:
    """Create bar building geometry from building type and parameters.

    Wraps the create_bar_from_building_type_ratios measure which creates
    spaces, surfaces, fenestration, thermal zones, building stories, and
    space types from high-level parameters. Does NOT create constructions,
    loads, HVAC, or schedules — use create_typical_building for that.

    Creates an empty model internally if no model is loaded.

    Args:
        building_type: DOE prototype — "SmallOffice", "LargeOffice",
            "RetailStandalone", "PrimarySchool", "Hospital", etc.
        total_bldg_floor_area: Total floor area in ft² (default 10000)
        num_stories_above_grade: Stories above grade, fractional OK (default 1)
        num_stories_below_grade: Basement stories (default 0)
        floor_height: Floor-to-floor height in ft (0 = smart default by type)
        template: Standards template — "90.1-2019", "90.1-2016", etc.
        climate_zone: ASHRAE climate zone or "Lookup From Stat File"
        wwr: Window-to-wall ratio (0 = smart default by building type)
        ns_to_ew_ratio: North-south to east-west aspect ratio (0 = smart default)
        building_rotation: Clockwise rotation from north in degrees (default 0)
        bar_division_method: How to divide bar into spaces —
            "Multiple Space Types - Individual Stories Sliced" or
            "Multiple Space Types - Building Type Ratios"
        story_multiplier: Story grouping — "Basements Ground Mid Top" or "None"
        bar_width: Bar width in ft (0 = auto-calculate from perimeter multiplier)
    """
    measures_dir = Path(os.environ.get("COMSTOCK_MEASURES_DIR", "/opt/comstock-measures"))
    measure_path = measures_dir / "create_bar_from_building_type_ratios"
    if not measure_path.is_dir():
        return {
            "ok": False,
            "error": f"Measure not found: {measure_path}. "
                     "Ensure ComStock measures are installed.",
        }

    # Create empty model if none loaded
    if model_manager.get_model_if_loaded() is None:
        try:
            _create_empty_model()
        except Exception as e:
            return {"ok": False, "error": f"Failed to create empty model: {e}"}

    # Expand short climate zone codes to full Choice values
    climate_zone = _expand_climate_zone(climate_zone)

    # Build arguments dict from kwargs
    local_vars = {
        "building_type": building_type,
        "total_bldg_floor_area": total_bldg_floor_area,
        "num_stories_above_grade": num_stories_above_grade,
        "num_stories_below_grade": num_stories_below_grade,
        "floor_height": floor_height,
        "template": template,
        "climate_zone": climate_zone,
        "wwr": wwr,
        "ns_to_ew_ratio": ns_to_ew_ratio,
        "building_rotation": building_rotation,
        "bar_division_method": bar_division_method,
        "story_multiplier": story_multiplier,
        "bar_width": bar_width,
    }
    arguments = {}
    for py_name, measure_name in _BAR_ARG_MAP.items():
        val = local_vars[py_name]
        if isinstance(val, bool):
            arguments[measure_name] = str(val).lower()
        else:
            arguments[measure_name] = str(val)

    # use_upstream_args=false — we pass all args explicitly
    arguments["use_upstream_args"] = "false"

    result = apply_measure(measure_dir=str(measure_path), arguments=arguments,
                           use_bundle=False)

    if result.get("ok"):
        # Add summary info from the resulting model
        try:
            model = get_model()
            result["building_type"] = building_type
            result["floor_area_ft2"] = total_bldg_floor_area
            result["template"] = template
            result["spaces"] = len(model.getSpaces())
            result["thermal_zones"] = len(model.getThermalZones())
            result["surfaces"] = len(model.getSurfaces())
            result["building_stories"] = len(model.getBuildingStorys())
        except Exception:
            pass

    return result


def create_new_building(
    # Bar geometry args
    building_type: str = "SmallOffice",
    total_bldg_floor_area: float = 10000,
    num_stories_above_grade: float = 1.0,
    num_stories_below_grade: int = 0,
    floor_height: float = 0,
    wwr: float = 0,
    ns_to_ew_ratio: float = 0,
    building_rotation: float = 0,
    bar_division_method: str = "Multiple Space Types - Individual Stories Sliced",
    story_multiplier: str = "Basements Ground Mid Top",
    bar_width: float = 0,
    # Weather/location args
    weather_file: str | None = None,
    climate_zone: str = "Lookup From Stat File",
    # Typical building args
    template: str = "90.1-2019",
    system_type: str = "Inferred",
    htg_src: str = "NaturalGas",
    clg_src: str = "Electricity",
    swh_src: str = "Inferred",
    add_hvac: bool = True,
    add_swh: bool = True,
) -> dict[str, Any]:
    """Create a complete building from scratch in one call.

    Chains: empty model → [change_building_location] → create_bar → create_typical.
    Creates geometry, space types, constructions, loads, HVAC, schedules, and SWH.

    Args:
        building_type: DOE prototype — "SmallOffice", "LargeOffice",
            "RetailStandalone", "PrimarySchool", "Hospital", etc.
        total_bldg_floor_area: Total floor area in ft² (default 10000)
        num_stories_above_grade: Stories above grade (default 1)
        num_stories_below_grade: Basement stories (default 0)
        floor_height: Floor-to-floor height in ft (0 = smart default)
        wwr: Window-to-wall ratio (0 = smart default by building type)
        ns_to_ew_ratio: Aspect ratio (0 = smart default)
        building_rotation: Clockwise rotation from north in degrees
        bar_division_method: Bar division method
        story_multiplier: Story multiplier grouping
        bar_width: Bar width in ft (0 = auto)
        weather_file: Absolute path to EPW weather file (optional)
        climate_zone: ASHRAE climate zone — "Lookup From Stat File" or e.g. "4A"
        template: ASHRAE standard — "90.1-2019", etc.
        system_type: HVAC system — "Inferred" or specific type
        htg_src: Heating fuel — "NaturalGas", "Electricity", etc.
        clg_src: Cooling fuel — "Electricity" or "DistrictCooling"
        swh_src: SWH fuel — "Inferred", "NaturalGas", "Electricity"
        add_hvac: Add HVAC system (default True)
        add_swh: Add service water heating (default True)
    """
    # Step 1: Create empty model
    try:
        _create_empty_model()
    except Exception as e:
        return {"ok": False, "error": f"Failed to create empty model: {e}"}

    # Step 2: Create bar geometry (before weather — apply_measure
    # saves/reloads model, which breaks relative weather file paths)
    bar_result = create_bar_building(
        building_type=building_type,
        total_bldg_floor_area=total_bldg_floor_area,
        num_stories_above_grade=num_stories_above_grade,
        num_stories_below_grade=num_stories_below_grade,
        floor_height=floor_height,
        template=template,
        climate_zone=climate_zone,
        wwr=wwr,
        ns_to_ew_ratio=ns_to_ew_ratio,
        building_rotation=building_rotation,
        bar_division_method=bar_division_method,
        story_multiplier=story_multiplier,
        bar_width=bar_width,
    )
    if not bar_result.get("ok"):
        return {
            "ok": False,
            "error": f"create_bar failed: {bar_result.get('error', 'unknown')}",
            "step": "create_bar",
            "bar_result": bar_result,
        }

    # Step 3: Set weather AFTER bar (apply_measure saves/reloads model,
    # which breaks relative weather file paths — set it fresh on the
    # final model). ChangeBuildingLocation sets EPW + design days + climate zone.
    if weather_file:
        from mcp_server.skills.common_measures.wrappers import change_building_location_op
        wr = change_building_location_op(
            weather_file=weather_file, climate_zone=climate_zone,
        )
        if not wr.get("ok"):
            return {
                "ok": False,
                "error": f"change_building_location failed: {wr.get('error', 'unknown')}",
                "step": "change_building_location",
                "bar_result": bar_result,
            }

    # Step 4: Apply typical building (constructions, loads, HVAC, schedules)
    # Read climate zone from model (change_building_location already set it)
    if weather_file:
        cz_from_model = _read_climate_zone_from_model()
        typical_cz = _expand_climate_zone(cz_from_model) if cz_from_model else "Lookup From Model"
    elif climate_zone != "Lookup From Stat File":
        typical_cz = _expand_climate_zone(climate_zone)
    else:
        typical_cz = "Lookup From Model"

    typical_result = create_typical_building(
        template=template,
        building_type=building_type,
        system_type=system_type,
        climate_zone=typical_cz,
        htg_src=htg_src,
        clg_src=clg_src,
        swh_src=swh_src,
        add_hvac=add_hvac,
        add_swh=add_swh,
    )
    if not typical_result.get("ok"):
        return {
            "ok": False,
            "error": f"create_typical failed: {typical_result.get('error', 'unknown')}",
            "step": "create_typical",
            "bar_result": bar_result,
            "typical_result": typical_result,
        }

    # Build final summary
    summary: dict[str, Any] = {"ok": True}
    try:
        model = get_model()
        summary["spaces"] = len(model.getSpaces())
        summary["thermal_zones"] = len(model.getThermalZones())
        summary["surfaces"] = len(model.getSurfaces())
        summary["air_loops"] = len(model.getAirLoopHVACs())
        summary["plant_loops"] = len(model.getPlantLoops())
    except Exception:
        pass
    summary["building_type"] = building_type
    summary["floor_area_ft2"] = total_bldg_floor_area
    summary["template"] = template
    summary["system_type"] = system_type
    if weather_file:
        summary["weather_file"] = weather_file
    summary["climate_zone"] = climate_zone

    return summary
