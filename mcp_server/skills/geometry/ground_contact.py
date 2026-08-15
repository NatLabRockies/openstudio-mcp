"""Find surfaces that sit at or below grade but are not connected to the ground.

Revit gbXML exports under-declare ground contact and the OpenStudio translator faithfully
reproduces the omission. Measured on this repo's own fixtures: `2026_11Ja_path1.xml` is a
building WITH a basement whose translated model carries exactly one Ground surface out of 292
(the source declares a single `UndergroundSlab`, and types the basement's own walls as plain
`ExteriorWall`); `austin_office.xml` and `austin_apartment_slivers.xml` declare no ground-contact
surface type at all. So the defect cannot be found by reading `surfaceType` back out of the
gbXML — the source is what is wrong. It has to be found geometrically.

This matters beyond bookkeeping: `Outdoors` carries `SunExposed`/`WindExposed`, so a buried slab
or basement wall left that way takes fictitious solar gain and wind convection — the same class
of error the `patch_missing_surfaces` exposure fix addressed. Nothing else reports it. The model
still simulates, so `validate_model` stays quiet and the enclosure/overlap checks in
`repair_and_validate_gbxml_geometry` never look at boundary conditions.

Report only, never repaired. Whether a slab is on grade, over a crawlspace, or over open parking
is a modeling judgment that changes energy results materially, and guessing it is exactly what
this package's other repair tools refuse to do. The output is a list of names shaped to be handed
straight to `set_surface_boundary_conditions(surface_names=[...],
outside_boundary_condition="Ground")`, which already derives `NoSun`/`NoWind` for a non-Outdoors
condition.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model

# Same scale as the sibling modules' geometric guards (MIN_WELDED_SURFACE_AREA_M2,
# PAIR_AREA_TOLERANCE_M2) — below this, a vertex is on the grade plane, not above or below it.
GRADE_TOLERANCE_M = 0.01
# The actionable list is capped far above the sibling MAX_REPORTED_ISSUES (20) on purpose: these
# names are the input to a single batched set_surface_boundary_conditions() call, and truncating
# at 20 would force an agent through repeated diagnose-and-fix rounds on a model with a hundred
# buried surfaces — costing far more context than the longer list does.
GROUND_NAME_CAP = 200
# Diagnostic-only lists keep the sibling cap, since they are read, not replayed.
MAX_REPORTED_NAMES = 20
# Share of a wall's height that must sit below grade before it is treated as a basement wall
# rather than an above-grade wall that happens to dip. Measured on the repo's own basement
# fixture (2026_11Ja_path1), every one of its 17 basement walls runs z=-3.05 to z=+0.91 — 77%
# buried. An "entirely below grade" rule finds none of them, which is to say it finds nothing at
# all on the only real basement model available.
MIN_BURIED_WALL_FRACTION = 0.5


def ground_boundary_conditions() -> frozenset[str]:
    """Every boundary condition that already means "coupled to the ground".

    Derived from the SDK rather than hardcoded, so it cannot drift from the bindings. There are
    ten of them, not one: a check written as `== "Ground"` would flag every F/C-factor and Kiva
    `Foundation` surface as defective — precisely the constructions ASHRAE 90.1 baseline work
    uses.
    """
    return frozenset(
        value for value in openstudio.model.Surface.validOutsideBoundaryConditionValues()
        if value.startswith("Ground") or value == "Foundation"
    )


def world_z_range(surface: openstudio.model.Surface) -> tuple[float, float] | None:
    """(min z, max z) of a surface in world coordinates, or None if it has no parent space.

    Surface.vertices() are relative to the owning Space's origin, so reading z off them directly
    misplaces every surface in a space that carries one — a model whose spaces are stacked by
    origin would report its top floor as buried. Building rotation is about the z axis alone and
    cannot change a vertex's height, so the space transformation is the whole correction.
    """
    space = surface.space()
    if not space.is_initialized():
        return None
    world = space.get().transformation() * surface.vertices()
    heights = [vertex.z() for vertex in world]
    if not heights:
        return None
    return min(heights), max(heights)


def find_missing_ground_contact() -> dict[str, Any]:
    """Report at-or-below-grade surfaces that are not ground-coupled. Never mutates.

    Grade is the z = 0 plane, the site-coordinate convention gbXML and OpenStudio both use.
    An `Outdoors` surface is a finding when:

    - it is a Floor or Wall entirely at or below grade, or
    - it is a Wall crossing grade with at least MIN_BURIED_WALL_FRACTION of its height buried.

    Both land in `ground_contact_missing`, the list shaped to be replayed into one batched
    `set_surface_boundary_conditions()` call. A wall crossing grade with less than that buried is
    reported separately in `partially_below_grade` — visible, but not proposed for a batch fix.

    Setting a partly-buried wall to `Ground` does bury the part above grade too. Splitting it at
    z = 0 would be strictly more correct, and no tool here does that; this is reported rather
    than repaired precisely so that call stays with the modeler.

    A below-grade Floor or Wall already set `Adiabatic` is counted in
    `adiabatic_below_grade_count` and never named — that is usually a deliberate assumption
    `patch_missing_surfaces` recorded, and listing a hundred of them would be noise. It covers
    the same Floor/Wall population as `ground_contact_missing_count`, so the two are directly
    comparable.

    Also returns `ground_surfaces_existing_count`, so an implausible result is visible next to
    the finding: "1 existing, 40 missing" reads very differently from "40 existing, 1 missing",
    and no geometric rule can tell which of those means the model's origin is not at grade.
    """
    try:
        model = get_model()
        ground_family = ground_boundary_conditions()

        missing: list[str] = []
        partial: list[str] = []
        adiabatic_below = 0
        existing_ground = 0

        # Name order — see match_surfaces() in geometry/operations.py (issue #134). Nothing here
        # mutates, so only the reported list order depends on it, but a findings list that
        # reshuffles between runs is a diff for no reason.
        for surface in sorted(model.getSurfaces(), key=lambda s: s.nameString()):
            condition = surface.outsideBoundaryCondition()
            if condition in ground_family:
                existing_ground += 1
                continue
            # "Surface" is a matched interior boundary — it has a partner, not a ground face.
            if condition not in ("Outdoors", "Adiabatic"):
                continue

            z_range = world_z_range(surface)
            if z_range is None:
                continue
            z_min, z_max = z_range

            if z_max > GRADE_TOLERANCE_M:
                # Partly above grade. Only a wall crossing grade is worth reporting, and a
                # basement wall is one that is mostly buried — see MIN_BURIED_WALL_FRACTION.
                if surface.surfaceType() != "Wall" or z_min >= -GRADE_TOLERANCE_M:
                    continue
                if condition == "Adiabatic":
                    continue
                buried_fraction = -z_min / (z_max - z_min)
                if buried_fraction >= MIN_BURIED_WALL_FRACTION:
                    missing.append(surface.nameString())
                else:
                    partial.append(surface.nameString())
                continue

            # Restricted to Floor and Wall for both buckets, so the two counts describe the same
            # population and differ only by boundary condition — a below-grade RoofCeiling is the
            # top of a space, not a candidate ground connection.
            if surface.surfaceType() not in ("Floor", "Wall"):
                continue
            if condition == "Adiabatic":
                adiabatic_below += 1
            else:
                missing.append(surface.nameString())

        result: dict[str, Any] = {
            "ok": True,
            "ground_contact_missing_count": len(missing),
            "ground_surfaces_existing_count": existing_ground,
            "partially_below_grade_count": len(partial),
            "adiabatic_below_grade_count": adiabatic_below,
        }
        # Name lists are emitted only when there is something to name, so a clean model costs
        # the caller four integers rather than four empty containers.
        if missing:
            result["ground_contact_missing"] = missing[:GROUND_NAME_CAP]
            if len(missing) > GROUND_NAME_CAP:
                result["ground_contact_missing_truncated"] = True
        if partial:
            result["partially_below_grade"] = partial[:MAX_REPORTED_NAMES]
            if len(partial) > MAX_REPORTED_NAMES:
                result["partially_below_grade_truncated"] = True
        return result
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to check ground contact: {e}"}
