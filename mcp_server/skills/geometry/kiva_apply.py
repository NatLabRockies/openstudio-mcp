"""The write half of the Kiva feature: set_kiva_foundation.

Split from kiva_foundation.py (which holds the read side, the perimeter resolution and the object
helpers) to keep both inside the ~400 line budget, CLAUDE.md rule 1.

Order of operations matters here and is not arbitrary:

  1. Validate the archetype and every argument before touching the SDK.
  2. Resolve every surface name; a single bad name aborts with nothing written — the pattern
     boundary_conditions.py::set_surface_boundary_conditions established.
  3. `setOutsideBoundaryCondition("Foundation")` BEFORE `setAdjacentFoundation`, because the latter
     leaves SunExposed/WindExposed intact and would put solar gain on a buried slab.
  4. Create the exposed-perimeter object and read it back — its constructor reports success even
     when it silently discarded the input.

`dry_run=True` returns the identical plan payload without mutating, so the agent can show the user
exactly what would happen before committing.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import ensure_generation_unchanged, get_model_with_generation
from mcp_server.osm_helpers import parse_str_list
from mcp_server.skills.geometry.kiva_archetypes import (
    ARCHETYPES,
    UnknownArchetypeError,
    get_archetype,
    resolve_insulation,
    resolve_kiva_parameters,
    resolve_soil_properties,
)
from mcp_server.skills.geometry.kiva_eligibility import (
    KIVA_DOMAIN_WARN_THRESHOLD,
    classify_foundation_candidates,
    pair_walls_to_floors,
)
from mcp_server.skills.geometry.kiva_foundation import (
    _apply_insulation,
    _model_climate_zone,
    _resolve_perimeter,
    _wall_depth_for,
    _write_exposed_perimeter,
    code_ground_targets,
)

# A basement archetype landing on a slab-on-grade model is the most likely misuse, and it writes a
# foundation wall that is not there. Above this depth we require corroborating geometry.
SUSPICIOUS_WALL_DEPTH_M = 0.5


def _epw_soil_set(model, generation: int, epw_path: str | None, warnings: list[str]):
    """The EPW's GROUND TEMPERATURES soil properties, or None.

    Reuses Phase 1's resolution chain verbatim rather than copying it — and Kiva needs a weather
    file at simulation time anyway, so a miss here is worth reporting.
    """
    from mcp_server.skills.weather.epw_ground_temperatures import (
        EpwGroundTemperatureError,
        nearest_depth_set,
        read_ground_temperature_sets,
    )
    from mcp_server.skills.weather.ground_temperatures import SHALLOW_TARGET_DEPTH_M, _resolve_epw

    epw, source = _resolve_epw(model, generation, epw_path)
    if epw is None:
        warnings.append(
            "No EPW found, so soil properties fall back to OpenStudio defaults. Note that "
            "EnergyPlus refuses to run Kiva without a weather file — set one before simulating.",
        )
        return None
    try:
        sets, _ = read_ground_temperature_sets(epw)
    except EpwGroundTemperatureError as e:
        warnings.append(f"Could not read soil properties from {source}: {e}")
        return None
    chosen, _ = nearest_depth_set(sets, SHALLOW_TARGET_DEPTH_M)
    return chosen


def _ground_temperature_interaction(model, applied: dict[str, Any]) -> dict[str, Any]:
    """What Kiva just did to the Phase 1 ground temperatures, stated rather than left implicit."""
    from mcp_server.skills.weather.ground_temperatures import read_ground_temperature_state

    state = read_ground_temperature_state(model)
    remaining = [
        s.nameString() for s in model.getSurfaces()
        if s.outsideBoundaryCondition().startswith("Ground")
    ]
    result: dict[str, Any] = {
        "surfaces_now_kiva": len(applied.get("floors", [])) + len(applied.get("walls", [])),
        "ground_surfaces_remaining": len(remaining),
        "building_surface_state": state["building_surface"]["state"],
    }
    if state["building_surface"]["state"] in ("set", "partial"):
        result["warning"] = (
            f"Site:GroundTemperature:BuildingSurface is {state['building_surface']['state']}, but "
            f"the {result['surfaces_now_kiva']} surface(s) just converted to Kiva ignore it. It "
            + (
                f"still applies to {len(remaining)} remaining Ground surface(s)."
                if remaining else "now applies to no surfaces at all."
            )
        )
    return result


def _apply(model, floor_names, walls_by_floor, geometry, insulation, soil, perimeters,
           archetype, warnings) -> tuple[dict[str, Any], str | None]:
    """Write the Kiva objects. Returns (applied, error)."""
    settings_written = {k: v for k, v in soil.items() if v.write}
    if settings_written:
        settings = model.getFoundationKivaSettings()   # creating here is the intent
        if "soil_conductivity_w_mk" in settings_written:
            settings.setSoilConductivity(settings_written["soil_conductivity_w_mk"].value)
        if "soil_density_kg_m3" in settings_written:
            settings.setSoilDensity(settings_written["soil_density_kg_m3"].value)
        if "soil_specific_heat_j_kgk" in settings_written:
            settings.setSoilSpecificHeat(settings_written["soil_specific_heat_j_kgk"].value)

    applied: dict[str, Any] = {"floors": [], "walls": [], "insulation": {}, "foundations": []}

    for floor_name in floor_names:
        floor = model.getSurfaceByName(floor_name).get()
        wall_names = walls_by_floor.get(floor_name, [])

        if floor.adjacentFoundation().is_initialized():
            floor.resetAdjacentFoundation()

        kiva = openstudio.model.FoundationKiva(model)
        kiva.setName(f"Kiva {archetype} {floor_name}")

        for field, setter in (
            ("wall_height_above_grade_m", kiva.setWallHeightAboveGrade),
            ("wall_depth_below_slab_m", kiva.setWallDepthBelowSlab),
            ("footing_depth_m", kiva.setFootingDepth),
        ):
            resolved = geometry[field]
            if resolved.write and not setter(resolved.value):
                return applied, f"OpenStudio refused {field}={resolved.value} on '{floor_name}'"

        _apply_insulation(model, kiva, insulation, _wall_depth_for(model, wall_names),
                          applied["insulation"], warnings)

        # Boundary condition FIRST: setAdjacentFoundation leaves sun/wind exposure alone, and a
        # buried slab left SunExposed takes fictitious solar gain.
        for surface, kind in [(floor, "floor")] + [
            (model.getSurfaceByName(n).get(), "wall") for n in wall_names
        ]:
            if not surface.setOutsideBoundaryCondition("Foundation"):
                return applied, (
                    f"OpenStudio refused the Foundation boundary condition on "
                    f"'{surface.nameString()}'"
                )
            if not surface.setAdjacentFoundation(kiva):
                return applied, f"OpenStudio refused to attach '{surface.nameString()}' to {kiva.nameString()}"
            applied["floors" if kind == "floor" else "walls"].append(surface.nameString())

        method, value, provenance = perimeters[floor_name]
        error = _write_exposed_perimeter(floor, method, value)
        if error is not None:
            return applied, error

        applied["foundations"].append({
            "name": kiva.nameString(),
            "floor": floor_name,
            "walls": wall_names,
            "exposed_perimeter": {"method": method, "value": value, "provenance": provenance},
        })

    applied["settings_written"] = sorted(settings_written)
    return applied, None


def set_kiva_foundation(
    archetype: str,
    floor_surface_names: list[str] | str | None = None,
    include_below_grade_walls: bool = True,
    include_adiabatic: bool = False,
    exposed_perimeter_method: str = "auto",
    exposed_perimeter_m: float | None = None,
    exposed_perimeter_fraction: float | None = None,
    wall_height_above_grade_m: float | None = None,
    wall_depth_below_slab_m: float | None = None,
    footing_depth_m: float | None = None,
    interior_horizontal_insulation_r_si: float | None = None,
    interior_horizontal_insulation_width_m: float | None = None,
    exterior_vertical_insulation_r_si: float | None = None,
    exterior_vertical_insulation_depth_m: float | None = None,
    soil_conductivity_w_mk: float | None = None,
    soil_density_kg_m3: float | None = None,
    soil_specific_heat_j_kgk: float | None = None,
    epw_path: str | None = None,
    confirm_many_domains: bool = False,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply a Kiva foundation model. See the module docstrings for the SDK hazards this navigates."""
    try:
        get_archetype(archetype)
    except UnknownArchetypeError as e:
        return {"ok": False, "error": str(e), "valid_values": sorted(ARCHETYPES)}

    try:
        model, generation = get_model_with_generation()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    try:
        warnings: list[str] = []
        candidates = classify_foundation_candidates(model, include_adiabatic=include_adiabatic)
        available = {f["surface"] for f in candidates["eligible_floors"]}

        requested = (parse_str_list(floor_surface_names)
                     if isinstance(floor_surface_names, str) else floor_surface_names)
        if requested:
            requested = list(dict.fromkeys(requested))
            blocked = {b["surface"]: b["reasons"] for b in candidates["blocked"]}
            refused = {n: blocked.get(n, ["not an eligible foundation floor at or below grade"])
                       for n in requested if n not in available}
            if refused:
                return {
                    "ok": False,
                    "error": f"{len(refused)} requested surface(s) cannot be Kiva floors; "
                             f"no changes were made.",
                    "refused_surfaces": refused,
                }
            floor_names = requested
        else:
            floor_names = sorted(available)

        if not floor_names:
            return {
                "ok": False,
                "error": "No eligible foundation floors in this model. Call get_foundation_options() "
                         "to see why each candidate was blocked.",
                "blocked": candidates["blocked"],
            }
        if len(floor_names) > KIVA_DOMAIN_WARN_THRESHOLD and not confirm_many_domains:
            return {
                "ok": False,
                "error": f"{len(floor_names)} floors would create {len(floor_names)} separate Kiva "
                         f"2D domains (EnergyPlus allows one floor per Foundation object), which "
                         f"slows simulation substantially. Pass confirm_many_domains=True to "
                         f"proceed, or narrow floor_surface_names.",
                "eligible_floor_count": len(floor_names),
            }

        wall_pairing: dict[str, Any] = {"pairs": {n: [] for n in floor_names}, "unpaired": []}
        if include_below_grade_walls:
            wall_pairing = pair_walls_to_floors(
                model, floor_names, [w["surface"] for w in candidates["eligible_walls"]],
            )
            for entry in wall_pairing["unpaired"]:
                warnings.append(
                    f"Below-grade wall '{entry['surface']}' was not applied: {entry['reason']}.",
                )

        geometry, geometry_warnings = resolve_kiva_parameters(archetype, {
            "wall_height_above_grade_m": wall_height_above_grade_m,
            "wall_depth_below_slab_m": wall_depth_below_slab_m,
            "footing_depth_m": footing_depth_m,
        })
        warnings.extend(geometry_warnings)

        depth = geometry["wall_depth_below_slab_m"]
        if depth.value and depth.value > SUSPICIOUS_WALL_DEPTH_M and not candidates["eligible_walls"]:
            return {
                "ok": False,
                "error": f"wall_depth_below_slab_m resolved to {depth.value} m but this model has "
                         f"no below-grade walls — that looks like a basement archetype applied to a "
                         f"slab-on-grade model. Pass the value explicitly if it is intended.",
            }

        insulation, insulation_warnings = resolve_insulation(archetype, {
            "interior_horizontal_r_si": interior_horizontal_insulation_r_si,
            "interior_horizontal_width_m": interior_horizontal_insulation_width_m,
            "exterior_vertical_r_si": exterior_vertical_insulation_r_si,
            "exterior_vertical_depth_m": exterior_vertical_insulation_depth_m,
        })
        warnings.extend(insulation_warnings)

        soil, soil_warnings = resolve_soil_properties(
            _epw_soil_set(model, generation, epw_path, warnings),
            {
                "soil_conductivity_w_mk": soil_conductivity_w_mk,
                "soil_density_kg_m3": soil_density_kg_m3,
                "soil_specific_heat_j_kgk": soil_specific_heat_j_kgk,
            },
        )
        warnings.extend(soil_warnings)

        perimeters, perimeter_error = _resolve_perimeter(
            model, floor_names, exposed_perimeter_method,
            exposed_perimeter_m, exposed_perimeter_fraction, warnings,
        )
        if perimeter_error is not None:
            return {"ok": False, "error": perimeter_error}

        already = [n for n in floor_names
                   if model.getSurfaceByName(n).get().adjacentFoundation().is_initialized()]
        if already and not overwrite:
            return {
                "ok": False,
                "error": f"{len(already)} floor(s) already carry a Kiva foundation; pass "
                         f"overwrite=True to replace them.",
                "already_kiva": sorted(already),
            }

        plan = {
            "archetype": archetype,
            "basis": get_archetype(archetype).basis,
            "floors": floor_names,
            "walls_by_floor": wall_pairing["pairs"],
            "geometry": {k: {"value": v.value, "provenance": v.provenance, "written": v.write}
                         for k, v in geometry.items()},
            "soil": {k: {"value": v.value, "provenance": v.provenance, "written": v.write}
                     for k, v in soil.items()},
            "exposed_perimeter": {n: {"method": m, "value": val, "provenance": p}
                                  for n, (m, val, p) in perimeters.items()},
        }
        if dry_run:
            ensure_generation_unchanged(generation)
            return {"ok": True, "dry_run": True, "plan": plan, "warnings": warnings,
                    "note": "Nothing was changed. Re-run without dry_run to apply."}

        applied, error = _apply(model, floor_names, wall_pairing["pairs"], geometry,
                                insulation, soil, perimeters, archetype, warnings)
        if error is not None:
            return {"ok": False, "error": error, "partial_state": applied}

        ensure_generation_unchanged(generation)
        return {
            "ok": True,
            "plan": plan,
            "applied": applied,
            "warnings": warnings,
            "code_targets": code_ground_targets(_model_climate_zone(model)),
            "ground_temperature_interaction": _ground_temperature_interaction(model, applied),
            "note": "Changes the in-memory model; call save_osm_model to persist. EnergyPlus "
                    "requires a weather file to run Kiva.",
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to apply Kiva foundation: {e}"}
