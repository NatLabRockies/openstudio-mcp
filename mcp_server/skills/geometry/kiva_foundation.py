"""Apply an EnergyPlus Kiva foundation model to a model's ground-contact surfaces.

The detailed counterpart to weather/ground_temperatures.py. A surface whose boundary condition is
`Foundation` ignores `Site:GroundTemperature:BuildingSurface` entirely and gets a solved 2D soil
domain instead, including slab-edge losses and insulation geometry — the thing a single monthly
temperature under the whole building cannot represent.

Kiva needs foundation detail a gbXML export does not carry, so the workflow asks: the agent calls
`get_foundation_options()`, puts the archetype menu to the user, and calls `set_kiva_foundation()`
with their answer. Every applied value reports where it came from, because several of them are
conventional starting points rather than anything sourced (see kiva_archetypes.py).

SDK facts (probed, OpenStudio 3.11.0 / EnergyPlus 25.2.0):

  - `model.getFoundationKivaSettings()` CREATES the unique object; `getOptionalFoundationKivaSettings()`
    does not. Same hazard as the Site:GroundTemperature objects in Phase 1 — a read path must use
    the optional form or a "get" tool silently mutates the session model.
  - `Surface.setAdjacentFoundation(kiva)` sets the boundary condition to `Foundation` but **leaves
    SunExposed/WindExposed intact** — fictitious solar gain on a buried slab. Call
    `setOutsideBoundaryCondition("Foundation")` FIRST (that one derives NoSun/NoWind), then
    `setAdjacentFoundation`.
  - `Surface.createSurfacePropertyExposedFoundationPerimeter(method, value)` **returns an
    initialized optional even when it rejected the input**. `"Calculate"` and any other unknown
    string read back as `''`; an out-of-range fraction leaves the value unset. `is_initialized()` is
    not a success signal — whitelist the method, range-check the value, then read both back and
    compare. A second call returns an empty optional rather than overwriting, so re-applying needs
    `resetSurfacePropertyExposedFoundationPerimeter()` first.
  - `FoundationKiva.surfaces()` exists; EnergyPlus allows exactly one floor per Foundation object.
  - `Surface.exposedPerimeter()` segfaults on a space-less surface — see kiva_eligibility.py.

`BySegment` is a legal IDD method but is not offered: EnergyPlus cannot auto-correct a clockwise
floor polygon under BySegment, OpenStudio exposes no segment API, and gbXML winding is exactly what
`weld_coincident_vertices` exists to clean up.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.config import OSCLI_GEM_PATH
from mcp_server.model_manager import ensure_generation_unchanged, get_model_with_generation
from mcp_server.skills.geometry.kiva_archetypes import (
    MATCH_WALL_DEPTH,
    MIN_EXPOSED_PERIMETER_M,
    POSITION_EXTERIOR_VERTICAL,
    POSITION_INTERIOR_HORIZONTAL,
    PROVENANCE_COMPUTED,
    PROVENANCE_COMPUTED_CLAMPED,
    PROVENANCE_FALLBACK_FRACTION,
    PROVENANCE_USER,
    XPS_CONDUCTIVITY_W_MK,
    XPS_DENSITY_KG_M3,
    XPS_ROUGHNESS,
    XPS_SPECIFIC_HEAT_J_KGK,
    archetype_menu,
    xps_thickness_m,
)
from mcp_server.skills.geometry.kiva_eligibility import (
    KIVA_DOMAIN_WARN_THRESHOLD,
    classify_foundation_candidates,
    compute_exposed_perimeters,
)

# The two methods OpenStudio actually accepts. BySegment is legal in the IDD but deliberately not
# offered (see the module docstring). Anything else is silently discarded by the SDK.
PERIMETER_METHOD_TOTAL = "TotalExposedPerimeter"
PERIMETER_METHOD_FRACTION = "ExposedPerimeterFraction"
VALID_PERIMETER_METHODS = (PERIMETER_METHOD_TOTAL, PERIMETER_METHOD_FRACTION)

PERIMETER_MODES = ("auto", "total", "fraction")

_CODE_TARGET_GLOB = (
    "ruby/*/gems/openstudio-standards-*/lib/openstudio-standards/standards/"
    "ashrae_90_1/ashrae_90_1_2019/data/ashrae_90_1_2019.construction_properties.json"
)


def _model_climate_zone(model) -> str | None:
    zones = model.getClimateZones().getClimateZones("ASHRAE")
    if not zones:
        return None
    value = zones[0].value()
    return value or None


def code_ground_targets(climate_zone: str | None) -> dict[str, Any] | None:
    """ASHRAE 90.1-2019 F-factor / C-factor targets for this climate zone.

    Reported alongside the applied values as a cross-check, never used to derive them: the vendored
    data is code *performance* per unit perimeter, and converting it into Kiva insulation geometry
    would mean inverting Appendix A tables that are not vendored here. Returns None when the
    standards gem or the climate zone is unavailable — this is a nicety, not a dependency.
    """
    if not climate_zone:
        return None
    digits = "".join(c for c in climate_zone if c.isdigit())
    if not digits:
        return None
    wanted = f"ClimateZone {digits}"

    matches = sorted(Path(OSCLI_GEM_PATH).glob(_CODE_TARGET_GLOB))
    if not matches:
        return None
    try:
        data = json.loads(matches[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    rows = next((v for v in data.values() if isinstance(v, list)), [])
    targets: dict[str, Any] = {"standard": "90.1-2019", "climate_zone": climate_zone}
    for row in rows:
        if not isinstance(row, dict) or row.get("climate_zone_set") != wanted:
            continue
        kind = row.get("standards_construction_type")
        if row.get("intended_surface_type") == "GroundContactFloor" and row.get(
            "assembly_maximum_f_factor",
        ):
            targets.setdefault("slab_max_f_factor", {})[kind] = row["assembly_maximum_f_factor"]
        if row.get("intended_surface_type") == "GroundContactWall" and row.get(
            "assembly_maximum_c_factor",
        ):
            targets.setdefault("below_grade_wall_max_c_factor", {})[kind] = row[
                "assembly_maximum_c_factor"
            ]
    if len(targets) == 2:
        return None
    targets["note"] = (
        "Code performance targets for comparison only — these are not the source of the insulation "
        "values applied, and F/C-factor cannot be converted to Kiva geometry without ASHRAE 90.1 "
        "Appendix A tables that are not available here."
    )
    return targets


def existing_soil_properties(model) -> dict[str, float | None]:
    """The soil values already chosen on FoundationKivaSettings, None where still defaulted.

    Optional getter, so calling this never creates the settings object.
    """
    optional = model.getOptionalFoundationKivaSettings()
    if not optional.is_initialized():
        return {"soil_conductivity_w_mk": None, "soil_density_kg_m3": None,
                "soil_specific_heat_j_kgk": None}
    settings = optional.get()
    return {
        "soil_conductivity_w_mk": (
            None if settings.isSoilConductivityDefaulted() else settings.soilConductivity()),
        "soil_density_kg_m3": (
            None if settings.isSoilDensityDefaulted() else settings.soilDensity()),
        "soil_specific_heat_j_kgk": (
            None if settings.isSoilSpecificHeatDefaulted() else settings.soilSpecificHeat()),
    }


def read_kiva_state(model) -> dict[str, Any]:
    """What Kiva content the model already carries. Creates nothing."""
    settings = model.getOptionalFoundationKivaSettings()
    foundations = model.getFoundationKivas()
    kiva_surfaces = [
        s.nameString() for s in model.getSurfaces()
        if s.outsideBoundaryCondition() == "Foundation"
    ]
    return {
        "settings_present": settings.is_initialized(),
        "foundation_count": len(foundations),
        "foundation_names": sorted(f.nameString() for f in foundations),
        "kiva_surface_count": len(kiva_surfaces),
        "kiva_surfaces": sorted(kiva_surfaces),
    }


def _insulation_material(model, r_si: float):
    """Get or create the XPS material for this R-value.

    Named deterministically so re-running the tool reuses the material rather than accumulating a
    new one each time — the same reuse pattern the vendored tbd gem applies to its "XPS 25mm".
    Built directly rather than through constructions.create_standard_opaque_material, which fetches
    its own model and returns a dict with no handle to attach to a FoundationKiva.
    """
    thickness = xps_thickness_m(r_si)
    name = f"Kiva XPS R-SI {r_si:.2f} ({round(thickness * 1000)} mm)"
    existing = model.getStandardOpaqueMaterialByName(name)
    if existing.is_initialized():
        return existing.get(), "reused"

    material = openstudio.model.StandardOpaqueMaterial(model)
    material.setName(name)
    material.setRoughness(XPS_ROUGHNESS)
    material.setThickness(thickness)
    material.setConductivity(XPS_CONDUCTIVITY_W_MK)
    material.setDensity(XPS_DENSITY_KG_M3)
    material.setSpecificHeat(XPS_SPECIFIC_HEAT_J_KGK)
    return material, "created"


def _wall_depth_for(model, wall_names: list[str]) -> float | None:
    """How far below grade the paired walls reach — the depth a full-height insulation run needs."""
    from mcp_server.skills.geometry.ground_contact import world_z_range

    depths = []
    for name in wall_names:
        optional = model.getSurfaceByName(name)
        if not optional.is_initialized():
            continue
        z_range = world_z_range(optional.get())
        if z_range is not None:
            depths.append(-z_range[0])
    return round(max(depths), 3) if depths and max(depths) > 0 else None


def _apply_insulation(model, kiva, specs, wall_depth_m, provenance, warnings) -> str | None:
    """Attach the insulation layers to one FoundationKiva. Returns an error string, or None.

    A setter refusal is an error, not a warning: recording the requested extent while the object
    kept its default would report insulation that is not in the model.
    """
    for spec in specs:
        depth = spec.depth_m
        if depth == MATCH_WALL_DEPTH:
            depth = wall_depth_m
            if depth is None:
                warnings.append(
                    f"{spec.position} insulation asked to match the below-grade wall depth, but no "
                    f"below-grade wall was paired to this floor; the insulation was not applied.",
                )
                continue
        # Resolve the depth first: a layer that is skipped must not leave an unused XPS material.
        material, disposition = _insulation_material(model, spec.r_si_m2k_w)
        if spec.position == POSITION_EXTERIOR_VERTICAL:
            if not kiva.setExteriorVerticalInsulationMaterial(material):
                return f"OpenStudio refused the exterior vertical insulation material on {kiva.nameString()}"
            if depth is not None and not kiva.setExteriorVerticalInsulationDepth(depth):
                return f"OpenStudio refused an exterior vertical insulation depth of {depth} m"
        elif spec.position == POSITION_INTERIOR_HORIZONTAL:
            if not kiva.setInteriorHorizontalInsulationMaterial(material):
                return f"OpenStudio refused the interior horizontal insulation material on {kiva.nameString()}"
            if spec.width_m is not None and not kiva.setInteriorHorizontalInsulationWidth(spec.width_m):
                return f"OpenStudio refused an interior horizontal insulation width of {spec.width_m} m"
        depth_provenance = spec.provenance.get("depth_m")
        if spec.depth_m == MATCH_WALL_DEPTH:
            depth_provenance = PROVENANCE_COMPUTED
        provenance[f"{spec.position}_insulation"] = {
            "r_si_m2k_w": spec.r_si_m2k_w,
            "material": material.nameString(),
            "material_disposition": disposition,
            "depth_m": depth,
            "width_m": spec.width_m,
            "provenance": {
                "r_si_m2k_w": spec.provenance.get("r_si_m2k_w"),
                "depth_m": depth_provenance,
                "width_m": spec.provenance.get("width_m"),
            },
        }
    return None


def _write_exposed_perimeter(surface, method: str, value: float) -> str | None:
    """Create the perimeter object and verify it took. Returns an error string, or None."""
    if surface.surfacePropertyExposedFoundationPerimeter().is_initialized():
        surface.resetSurfacePropertyExposedFoundationPerimeter()
    created = surface.createSurfacePropertyExposedFoundationPerimeter(method, value)
    if not created.is_initialized():
        return f"OpenStudio would not create an exposed perimeter object on '{surface.nameString()}'"

    obj = created.get()
    # is_initialized() is NOT a success signal here — an unknown method or an out-of-range value
    # still hands back an object with the field silently unset. Read both fields back.
    if obj.exposedPerimeterCalculationMethod() != method:
        return (
            f"Exposed perimeter method did not take on '{surface.nameString()}': asked for "
            f"{method!r}, model holds {obj.exposedPerimeterCalculationMethod()!r}"
        )
    if method == PERIMETER_METHOD_TOTAL:
        stored = obj.totalExposedPerimeter()          # OptionalDouble
        held = stored.get() if stored.is_initialized() else None
    else:
        held = obj.exposedPerimeterFraction()         # plain double, defaulted to 1.0
    if held is None or not math.isclose(held, value, rel_tol=1e-9, abs_tol=1e-9):
        return (
            f"Exposed perimeter value did not take on '{surface.nameString()}': asked for "
            f"{value}, model holds {held}"
        )
    return None


def get_foundation_options(include_adiabatic: bool = False) -> dict[str, Any]:
    """What the caller needs to decide before set_kiva_foundation, and what is already known."""
    try:
        model, generation = get_model_with_generation()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    try:
        candidates = classify_foundation_candidates(model, include_adiabatic=include_adiabatic)
        floor_names = [f["surface"] for f in candidates["eligible_floors"]]
        perimeters, perimeter_warnings = compute_exposed_perimeters(model, floor_names)
        for floor in candidates["eligible_floors"]:
            floor["exposed_perimeter_m"] = perimeters.get(floor["surface"])

        climate_zone = _model_climate_zone(model)
        warnings = list(perimeter_warnings)
        if len(floor_names) > KIVA_DOMAIN_WARN_THRESHOLD:
            warnings.append(
                f"{len(floor_names)} eligible floors means {len(floor_names)} separate Kiva 2D "
                f"domains — EnergyPlus allows only one floor per Foundation object. Expect a large "
                f"run-time increase; set_kiva_foundation requires confirm_many_domains=True above "
                f"{KIVA_DOMAIN_WARN_THRESHOLD}.",
            )
        if not floor_names:
            warnings.append(
                "No eligible foundation floors. Check `blocked` for the reason, and note that a "
                "slab still typed Outdoors is not at grade as far as this check is concerned — "
                "repair_and_validate_gbxml_geometry reports those under ground_contact_missing.",
            )

        # Read-only: getOptional* throughout, so calling this never creates a settings object.
        from mcp_server.skills.weather.ground_temperatures import read_ground_temperature_state

        result = {
            "ok": True,
            **candidates,
            "eligible_floor_count": len(floor_names),
            "eligible_wall_count": len(candidates["eligible_walls"]),
            "kiva_domains_if_applied": len(floor_names),
            "existing_kiva": read_kiva_state(model),
            "archetypes": archetype_menu(),
            "climate_zone": climate_zone,
            "code_targets": code_ground_targets(climate_zone),
            "ground_temperatures": read_ground_temperature_state(model),
            "warnings": warnings,
            "next_step": (
                "Show the archetype list and its parameter values to the user, ask which describes "
                "their foundation, then call set_kiva_foundation with their answer. The insulation "
                "R-values are conventional starting points, not code-derived — say so."
            ),
        }
        ensure_generation_unchanged(generation)
        return result
    except Exception as e:
        return {"ok": False, "error": f"Failed to read foundation options: {e}"}


def _resolve_perimeter(model, floor_names, mode, total_m, fraction, warnings):
    """(per-floor {method, value, provenance}, error). Never guesses silently."""
    if mode not in PERIMETER_MODES:
        return None, f"Unknown exposed_perimeter_method '{mode}'. Valid: {list(PERIMETER_MODES)}"

    if mode == "total":
        if total_m is None:
            return None, "exposed_perimeter_method='total' requires exposed_perimeter_m"
        if total_m <= 0:
            return None, f"exposed_perimeter_m must be greater than 0, got {total_m}"
        if len(floor_names) > 1:
            return None, (
                f"exposed_perimeter_method='total' takes one number, but {len(floor_names)} floors "
                f"were selected — one perimeter cannot describe several slabs. Use 'auto', or apply "
                f"to one floor at a time."
            )
        return {floor_names[0]: (PERIMETER_METHOD_TOTAL, total_m, PROVENANCE_USER)}, None

    if mode == "fraction":
        if fraction is None:
            return None, "exposed_perimeter_method='fraction' requires exposed_perimeter_fraction"
        if not 0.0 < fraction <= 1.0:
            return None, (
                f"exposed_perimeter_fraction must be greater than 0 and at most 1, got {fraction} "
                f"— OpenStudio discards an out-of-range fraction without reporting it, and Kiva "
                f"refuses a zero exposed perimeter (the computed path clamps zero to "
                f"{MIN_EXPOSED_PERIMETER_M} m for the same reason)."
            )
        return dict.fromkeys(floor_names, (PERIMETER_METHOD_FRACTION, fraction, PROVENANCE_USER)), None

    computed, compute_warnings = compute_exposed_perimeters(model, floor_names)
    warnings.extend(compute_warnings)
    resolved = {}
    for name in floor_names:
        value = computed.get(name)
        if value is None:
            resolved[name] = (PERIMETER_METHOD_FRACTION, 1.0, PROVENANCE_FALLBACK_FRACTION)
            warnings.append(
                f"Could not compute an exposed perimeter for '{name}'; fell back to an exposed "
                f"fraction of 1.0. Supply exposed_perimeter_m if you have a measured value.",
            )
        elif value <= 0.0:
            resolved[name] = (PERIMETER_METHOD_TOTAL, MIN_EXPOSED_PERIMETER_M,
                              PROVENANCE_COMPUTED_CLAMPED)
            warnings.append(
                f"Floor '{name}' has no exposed edge (it is an interior bay); its perimeter was "
                f"clamped to {MIN_EXPOSED_PERIMETER_M} m. Nearly all of its heat transfer is "
                f"through the slab core.",
            )
        else:
            resolved[name] = (PERIMETER_METHOD_TOTAL, value, PROVENANCE_COMPUTED)
    return resolved, None
