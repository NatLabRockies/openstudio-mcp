"""ComStock measure operations — discovery and high-leverage wrappers.

Provides:
- list_comstock_measures: scan COMSTOCK_MEASURES_DIR for available measures
- create_typical_building: wrapper around create_typical_building_from_model measure
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import openstudio

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
            "path": str(d),
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
        # Set climate zone on model if specified and not already set.
        # The measure's infiltration step reads it from the model object.
        if climate_zone != "Lookup From Model":
            czs = model.getClimateZones()
            if len(czs.getClimateZones("ASHRAE")) == 0:
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

    result = apply_measure(measure_dir=str(measure_path), arguments=arguments)

    # Enhance the response with context about what was applied
    if result.get("ok"):
        result["template"] = template
        result["system_type"] = system_type
        result["climate_zone"] = climate_zone

    return result
