"""Internal loads operations — people, lighting, equipment, infiltration.

Extraction patterns adapted from openstudio-toolkit osm_objects/loads.py
— using direct openstudio bindings.
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


def _extract_people(model, people) -> dict[str, Any]:
    """Extract people load attributes to dict."""
    # Determine source: space or space_type
    if people.space().is_initialized():
        source = "space"
    elif people.spaceType().is_initialized():
        source = "space_type"
    else:
        source = "unknown"

    result = {
        "handle": str(people.handle()),
        "name": people.nameString(),
        "source": source,
        "space": optional_name(people.space()),
        "activity_level_schedule": optional_name(people.activityLevelSchedule()),
        "number_of_people_schedule": optional_name(people.numberofPeopleSchedule()),
        "multiplier": float(people.multiplier()),
    }

    # Try to get definition method values
    try:
        if hasattr(people, "peopleDefinition") and people.peopleDefinition().is_initialized():
            definition = people.peopleDefinition().get()
            if hasattr(definition, "numberofPeople") and definition.numberofPeople().is_initialized():
                result["number_of_people"] = float(definition.numberofPeople().get())
            if hasattr(definition, "peopleperSpaceFloorArea") and definition.peopleperSpaceFloorArea().is_initialized():
                result["people_per_floor_area"] = float(definition.peopleperSpaceFloorArea().get())
            if hasattr(definition, "spaceFloorAreaperPerson") and definition.spaceFloorAreaperPerson().is_initialized():
                result["floor_area_per_person_m2"] = float(definition.spaceFloorAreaperPerson().get())
    except Exception:
        pass

    return result


def _extract_lights(model, lights) -> dict[str, Any]:
    """Extract lighting load attributes to dict."""
    result = {
        "handle": str(lights.handle()),
        "name": lights.nameString(),
        "space": optional_name(lights.space()),
        "schedule": optional_name(lights.schedule()),
        "multiplier": float(lights.multiplier()),
    }

    # Try to get definition method values
    try:
        if hasattr(lights, "lightsDefinition") and lights.lightsDefinition().is_initialized():
            definition = lights.lightsDefinition().get()
            if hasattr(definition, "lightingLevel") and definition.lightingLevel().is_initialized():
                result["lighting_level_w"] = float(definition.lightingLevel().get())
            if hasattr(definition, "wattsperSpaceFloorArea") and definition.wattsperSpaceFloorArea().is_initialized():
                result["watts_per_floor_area_w_m2"] = float(definition.wattsperSpaceFloorArea().get())
            if hasattr(definition, "wattsperPerson") and definition.wattsperPerson().is_initialized():
                result["watts_per_person_w"] = float(definition.wattsperPerson().get())
            if hasattr(definition, "fractionRadiant"):
                result["fraction_radiant"] = float(definition.fractionRadiant())
            if hasattr(definition, "fractionVisible"):
                result["fraction_visible"] = float(definition.fractionVisible())
            if hasattr(definition, "returnAirFraction"):
                result["return_air_fraction"] = float(definition.returnAirFraction())
    except Exception:
        pass

    return result


def _extract_electric_equipment(model, equipment) -> dict[str, Any]:
    """Extract electric equipment load attributes to dict."""
    result = {
        "handle": str(equipment.handle()),
        "name": equipment.nameString(),
        "space": optional_name(equipment.space()),
        "schedule": optional_name(equipment.schedule()),
        "multiplier": float(equipment.multiplier()),
    }

    # Try to get definition method values
    try:
        if hasattr(equipment, "electricEquipmentDefinition") and equipment.electricEquipmentDefinition().is_initialized():
            definition = equipment.electricEquipmentDefinition().get()
            if hasattr(definition, "designLevel") and definition.designLevel().is_initialized():
                result["design_level_w"] = float(definition.designLevel().get())
            if hasattr(definition, "wattsperSpaceFloorArea") and definition.wattsperSpaceFloorArea().is_initialized():
                result["watts_per_floor_area_w_m2"] = float(definition.wattsperSpaceFloorArea().get())
            if hasattr(definition, "wattsperPerson") and definition.wattsperPerson().is_initialized():
                result["watts_per_person_w"] = float(definition.wattsperPerson().get())
            if hasattr(definition, "fractionLatent"):
                result["fraction_latent"] = float(definition.fractionLatent())
            if hasattr(definition, "fractionRadiant"):
                result["fraction_radiant"] = float(definition.fractionRadiant())
            if hasattr(definition, "fractionLost"):
                result["fraction_lost"] = float(definition.fractionLost())
    except Exception:
        pass

    return result


def _extract_gas_equipment(model, equipment) -> dict[str, Any]:
    """Extract gas equipment load attributes to dict."""
    result = {
        "handle": str(equipment.handle()),
        "name": equipment.nameString(),
        "space": optional_name(equipment.space()),
        "schedule": optional_name(equipment.schedule()),
        "multiplier": float(equipment.multiplier()),
    }

    # Try to get definition method values
    try:
        if hasattr(equipment, "gasEquipmentDefinition") and equipment.gasEquipmentDefinition().is_initialized():
            definition = equipment.gasEquipmentDefinition().get()
            if hasattr(definition, "designLevel") and definition.designLevel().is_initialized():
                result["design_level_w"] = float(definition.designLevel().get())
            if hasattr(definition, "wattsperSpaceFloorArea") and definition.wattsperSpaceFloorArea().is_initialized():
                result["watts_per_floor_area_w_m2"] = float(definition.wattsperSpaceFloorArea().get())
            if hasattr(definition, "wattsperPerson") and definition.wattsperPerson().is_initialized():
                result["watts_per_person_w"] = float(definition.wattsperPerson().get())
            if hasattr(definition, "fractionLatent"):
                result["fraction_latent"] = float(definition.fractionLatent())
            if hasattr(definition, "fractionRadiant"):
                result["fraction_radiant"] = float(definition.fractionRadiant())
            if hasattr(definition, "fractionLost"):
                result["fraction_lost"] = float(definition.fractionLost())
    except Exception:
        pass

    return result


def _extract_infiltration(model, infiltration) -> dict[str, Any]:
    """Extract infiltration object attributes to dict."""
    result: dict[str, Any] = {
        "handle": str(infiltration.handle()),
        "name": infiltration.nameString(),
        "space": optional_name(infiltration.space()),
        "schedule": optional_name(infiltration.schedule()),
    }

    # These accessors may not exist on all OpenStudio versions
    for attr, key in [
        ("designFlowRate", "design_flow_rate_m3_s"),
        ("flowPerExteriorSurfaceArea", "flow_per_exterior_surface_area"),
        ("flowperExteriorSurfaceArea", "flow_per_exterior_surface_area"),
        ("flowPerExteriorWallArea", "flow_per_exterior_wall_area"),
        ("flowperExteriorWallArea", "flow_per_exterior_wall_area"),
        ("airChangesPerHour", "air_changes_per_hour"),
        ("constantTermCoefficient", "constant_term_coefficient"),
        ("temperatureTermCoefficient", "temperature_term_coefficient"),
        ("velocityTermCoefficient", "velocity_term_coefficient"),
        ("velocitySquaredTermCoefficient", "velocity_squared_term_coefficient"),
    ]:
        if key not in result:
            try:
                result[key] = float(getattr(infiltration, attr)())
            except (AttributeError, Exception):
                pass

    return result


def _load_space_filter(space_name, space_type_name):
    """Build obj_filter_fn for load list tools (shared by all 5 load types)."""
    if not space_name and not space_type_name:
        return None
    def filt(m, obj):
        if space_name and optional_name(obj.space()) != space_name:
            return False
        if space_type_name and optional_name(obj.spaceType()) != space_type_name:
            return False
        return True
    return filt


def list_people_loads(
    space_name: str | None = None,
    space_type_name: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List people loads. Loads in a space: space_name='Office 1'."""
    try:
        model = get_model()
        items, total = list_paginated(
            model, "getPeoples", _extract_people,
            max_results=max_results,
            obj_filter_fn=_load_space_filter(space_name, space_type_name),
        )
        return build_list_response("people_loads", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list people loads: {e}"}


def list_lighting_loads(
    space_name: str | None = None,
    space_type_name: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List lighting loads. Loads in a space: space_name='Office 1'."""
    try:
        model = get_model()
        items, total = list_paginated(
            model, "getLightss", _extract_lights,
            max_results=max_results,
            obj_filter_fn=_load_space_filter(space_name, space_type_name),
        )
        return build_list_response("lighting_loads", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list lighting loads: {e}"}


def list_electric_equipment(
    space_name: str | None = None,
    space_type_name: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List electric equipment. Loads in a space: space_name='Office 1'."""
    try:
        model = get_model()
        items, total = list_paginated(
            model, "getElectricEquipments", _extract_electric_equipment,
            max_results=max_results,
            obj_filter_fn=_load_space_filter(space_name, space_type_name),
        )
        return build_list_response("electric_equipment", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list electric equipment: {e}"}


def list_gas_equipment(
    space_name: str | None = None,
    space_type_name: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List gas equipment. Loads in a space: space_name='Office 1'."""
    try:
        model = get_model()
        items, total = list_paginated(
            model, "getGasEquipments", _extract_gas_equipment,
            max_results=max_results,
            obj_filter_fn=_load_space_filter(space_name, space_type_name),
        )
        return build_list_response("gas_equipment", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list gas equipment: {e}"}


def list_infiltration(
    space_name: str | None = None,
    space_type_name: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List infiltration objects. Loads in a space: space_name='Office 1'."""
    try:
        model = get_model()
        items, total = list_paginated(
            model, "getSpaceInfiltrationDesignFlowRates", _extract_infiltration,
            max_results=max_results,
            obj_filter_fn=_load_space_filter(space_name, space_type_name),
        )
        return build_list_response("infiltration", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list infiltration: {e}"}


# ---------------------------------------------------------------------------
# Load detail lookup (Part 4 — unified dispatcher)
# ---------------------------------------------------------------------------

# (type_name, getter_by_name, extract_fn)
LOAD_TYPES = [
    ("People", "getPeopleByName", _extract_people),
    ("Lights", "getLightsByName", _extract_lights),
    ("ElectricEquipment", "getElectricEquipmentByName", _extract_electric_equipment),
    ("GasEquipment", "getGasEquipmentByName", _extract_gas_equipment),
    ("SpaceInfiltrationDesignFlowRate", "getSpaceInfiltrationDesignFlowRateByName", _extract_infiltration),
]


def get_load_details(load_name: str) -> dict[str, Any]:
    """Get detailed info for any load object by name.

    Tries each load type until found. Returns load_type + all fields.
    """
    try:
        model = get_model()
        for type_name, getter_name, extract_fn in LOAD_TYPES:
            getter = getattr(model, getter_name, None)
            if getter is None:
                continue
            result = getter(load_name)
            if result.is_initialized():
                obj = result.get()
                return {"ok": True, "load_type": type_name, "load": extract_fn(model, obj)}
        return {"ok": False, "error": f"Load '{load_name}' not found"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get load details: {e}"}


# ---------------------------------------------------------------------------
# Helper: resolve space + optional schedule
# ---------------------------------------------------------------------------

def _resolve_space(model, space_name: str):
    """Return Space object or None."""
    return fetch_object(model, "Space", name=space_name)


def _resolve_schedule(model, schedule_name: str | None):
    """Return ScheduleRuleset object or None. Returns (obj|None, error|None)."""
    if not schedule_name:
        return None, None
    sched = fetch_object(model, "ScheduleRuleset", name=schedule_name)
    if sched is None:
        return None, f"Schedule '{schedule_name}' not found"
    return sched, None


# ---------------------------------------------------------------------------
# Creation operations
# ---------------------------------------------------------------------------

def create_people_definition(
    name: str,
    space_name: str,
    people_per_area: float | None = None,
    num_people: float | None = None,
    schedule_name: str | None = None,
) -> dict[str, Any]:
    """Create a People load and assign to a space.

    Exactly one of people_per_area or num_people must be provided.
    """
    try:
        if people_per_area is None and num_people is None:
            return {"ok": False, "error": "Provide people_per_area or num_people"}
        if people_per_area is not None and num_people is not None:
            return {"ok": False, "error": "Provide only one of people_per_area or num_people, not both"}
        model = get_model()
        space = _resolve_space(model, space_name)
        if space is None:
            return {"ok": False, "error": f"Space '{space_name}' not found"}
        sched, err = _resolve_schedule(model, schedule_name)
        if err:
            return {"ok": False, "error": err}

        # Create definition
        defn = openstudio.model.PeopleDefinition(model)
        defn.setName(f"{name} Definition")
        if people_per_area is not None:
            defn.setPeopleperSpaceFloorArea(people_per_area)
        elif num_people is not None:
            defn.setNumberofPeople(num_people)

        # Create People instance linked to definition
        people = openstudio.model.People(defn)
        people.setName(name)
        people.setSpace(space)
        if sched is not None:
            people.setNumberofPeopleSchedule(sched)

        return {"ok": True, "people": _extract_people(model, people)}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create people: {e}"}


def create_lights_definition(
    name: str,
    space_name: str,
    watts_per_area: float | None = None,
    lighting_level_w: float | None = None,
    schedule_name: str | None = None,
) -> dict[str, Any]:
    """Create a Lights load and assign to a space.

    Exactly one of watts_per_area or lighting_level_w must be provided.
    """
    try:
        if watts_per_area is None and lighting_level_w is None:
            return {"ok": False, "error": "Provide watts_per_area or lighting_level_w"}
        if watts_per_area is not None and lighting_level_w is not None:
            return {"ok": False, "error": "Provide only one of watts_per_area or lighting_level_w, not both"}
        model = get_model()
        space = _resolve_space(model, space_name)
        if space is None:
            return {"ok": False, "error": f"Space '{space_name}' not found"}
        sched, err = _resolve_schedule(model, schedule_name)
        if err:
            return {"ok": False, "error": err}

        defn = openstudio.model.LightsDefinition(model)
        defn.setName(f"{name} Definition")
        if watts_per_area is not None:
            defn.setWattsperSpaceFloorArea(watts_per_area)
        elif lighting_level_w is not None:
            defn.setLightingLevel(lighting_level_w)

        lights = openstudio.model.Lights(defn)
        lights.setName(name)
        lights.setSpace(space)
        if sched is not None:
            lights.setSchedule(sched)

        return {"ok": True, "lights": _extract_lights(model, lights)}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create lights: {e}"}


def create_electric_equipment(
    name: str,
    space_name: str,
    watts_per_area: float | None = None,
    design_level_w: float | None = None,
    schedule_name: str | None = None,
) -> dict[str, Any]:
    """Create an ElectricEquipment load and assign to a space.

    Exactly one of watts_per_area or design_level_w must be provided.
    """
    try:
        if watts_per_area is None and design_level_w is None:
            return {"ok": False, "error": "Provide watts_per_area or design_level_w"}
        if watts_per_area is not None and design_level_w is not None:
            return {"ok": False, "error": "Provide only one of watts_per_area or design_level_w, not both"}
        model = get_model()
        space = _resolve_space(model, space_name)
        if space is None:
            return {"ok": False, "error": f"Space '{space_name}' not found"}
        sched, err = _resolve_schedule(model, schedule_name)
        if err:
            return {"ok": False, "error": err}

        defn = openstudio.model.ElectricEquipmentDefinition(model)
        defn.setName(f"{name} Definition")
        if watts_per_area is not None:
            defn.setWattsperSpaceFloorArea(watts_per_area)
        elif design_level_w is not None:
            defn.setDesignLevel(design_level_w)

        equip = openstudio.model.ElectricEquipment(defn)
        equip.setName(name)
        equip.setSpace(space)
        if sched is not None:
            equip.setSchedule(sched)

        return {"ok": True, "electric_equipment": _extract_electric_equipment(model, equip)}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create electric equipment: {e}"}


def create_gas_equipment(
    name: str,
    space_name: str,
    watts_per_area: float | None = None,
    design_level_w: float | None = None,
    schedule_name: str | None = None,
) -> dict[str, Any]:
    """Create a GasEquipment load and assign to a space.

    Exactly one of watts_per_area or design_level_w must be provided.
    """
    try:
        if watts_per_area is None and design_level_w is None:
            return {"ok": False, "error": "Provide watts_per_area or design_level_w"}
        if watts_per_area is not None and design_level_w is not None:
            return {"ok": False, "error": "Provide only one of watts_per_area or design_level_w, not both"}
        model = get_model()
        space = _resolve_space(model, space_name)
        if space is None:
            return {"ok": False, "error": f"Space '{space_name}' not found"}
        sched, err = _resolve_schedule(model, schedule_name)
        if err:
            return {"ok": False, "error": err}

        defn = openstudio.model.GasEquipmentDefinition(model)
        defn.setName(f"{name} Definition")
        if watts_per_area is not None:
            defn.setWattsperSpaceFloorArea(watts_per_area)
        elif design_level_w is not None:
            defn.setDesignLevel(design_level_w)

        equip = openstudio.model.GasEquipment(defn)
        equip.setName(name)
        equip.setSpace(space)
        if sched is not None:
            equip.setSchedule(sched)

        return {"ok": True, "gas_equipment": _extract_gas_equipment(model, equip)}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create gas equipment: {e}"}


def create_infiltration(
    name: str,
    space_name: str,
    flow_per_exterior_surface_area: float | None = None,
    ach: float | None = None,
    schedule_name: str | None = None,
) -> dict[str, Any]:
    """Create a SpaceInfiltrationDesignFlowRate and assign to a space.

    Exactly one of flow_per_exterior_surface_area or ach must be provided.
    """
    try:
        if flow_per_exterior_surface_area is None and ach is None:
            return {"ok": False, "error": "Provide flow_per_exterior_surface_area or ach"}
        if flow_per_exterior_surface_area is not None and ach is not None:
            return {"ok": False, "error": "Provide only one of flow_per_exterior_surface_area or ach, not both"}
        model = get_model()
        space = _resolve_space(model, space_name)
        if space is None:
            return {"ok": False, "error": f"Space '{space_name}' not found"}
        sched, err = _resolve_schedule(model, schedule_name)
        if err:
            return {"ok": False, "error": err}

        infil = openstudio.model.SpaceInfiltrationDesignFlowRate(model)
        infil.setName(name)
        infil.setSpace(space)
        if flow_per_exterior_surface_area is not None:
            infil.setFlowperExteriorSurfaceArea(flow_per_exterior_surface_area)
        elif ach is not None:
            infil.setAirChangesperHour(ach)
        if sched is not None:
            infil.setSchedule(sched)

        return {"ok": True, "infiltration": _extract_infiltration(model, infil)}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create infiltration: {e}"}
