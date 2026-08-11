"""Trim same-space surfaces that genuinely overlap, instead of leaving a duplicate.

A different defect from anything else in this skill: two surfaces in the same space
occupying (some of) the same footprint on the same plane. Typically a wall exported
once per neighboring room instead of split at the boundary between them
(shared-wall duplication); also how a chord-based reconstruction in patch_missing_surfaces()
can occasionally end up sharing an edge with an already-ambiguous pre-existing sliver.
match_surfaces() can't fix this (it only reconciles surfaces between spaces, never
within one), and neither can anything additive — there's too much material here, not
too little.

Uses the same same-plane + true-2D-overlap-area detection already proven in
gbxml_import/operations.py's repair_and_validate_gbxml_geometry (coincident-plane check
via Plane.equal()/reverseEqual(), then openstudio.intersect() for the actual overlap
area — openstudio.intersects() alone is too loose, returning True for surfaces that
merely touch along a shared edge). The tolerances stay local per this skill's convention
that each repair module owns its own; the winding normalization both sides need is shared
from geometry/winding.py, which gbxml_import can import without inverting the one-way
geometry <- gbxml_import dependency direction.

Once a genuine overlap is found, the safest correction is not to guess which surface is
"right" — openstudio.intersect()'s newPolygons1()/newPolygons2() already compute each
surface's own non-overlapping remainder; this replaces each surface's vertices with that
remainder (or removes it outright if the remainder is empty — fully contained within the
other). Only the simple case (each surface's remainder is a single polygon) is handled;
a remainder that splits into multiple disjoint pieces is reported as skipped rather than
guessed at.

Two surfaces overlapping in space are not automatically interchangeable, so a pair is
only trimmed when it is genuinely the same thing twice: same surface type, same boundary
condition, same construction, and neither carrying a subsurface. Those guards mirror
merge_coplanar_sliver_surfaces' and exist because the alternative is silent data loss —
removing a parent surface cascades to its child windows and doors, and shrinking one
leaves them stranded outside their parent.
"""
from __future__ import annotations

import itertools
from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.operations import match_surfaces
from mcp_server.skills.geometry.winding import (
    align_to_reference_normal,
    normalize_local_frame_winding,
)

PLANE_TOLERANCE_M = 0.01
MIN_OVERLAP_AREA_M2 = 0.01
MIN_REMAINDER_AREA_M2 = 0.0001


def _to_vector(points: Any) -> openstudio.Point3dVector:
    pv = openstudio.Point3dVector()
    for p in points:
        pv.append(p)
    return pv


def _incompatibility_reason(
    s1: openstudio.model.Surface, s2: openstudio.model.Surface,
) -> str | None:
    """Why this pair must not be trimmed against each other, or None if compatible.

    Same guards as merge_coplanar_sliver_surfaces: overlapping in space does not make two
    surfaces interchangeable. Checked before any mutation — in particular before the
    fully-contained removal path, because Surface is a ParentObject whose remove()
    cascades to its child subsurfaces.
    """
    if s1.surfaceType() != s2.surfaceType():
        return (
            f"different surface types ({s1.surfaceType()} vs {s2.surfaceType()}); "
            "trimming these against each other would blend distinct thermal semantics"
        )

    boundary_conditions = {s1.outsideBoundaryCondition(), s2.outsideBoundaryCondition()}
    if len(boundary_conditions) > 1:
        return (
            f"mixed boundary conditions ({', '.join(sorted(boundary_conditions))}); "
            "refusing to blend them"
        )

    construction_handles = {
        c.get().handle() if (c := s.construction()).is_initialized() else None
        for s in (s1, s2)
    }
    if len(construction_handles) > 1:
        return "different constructions across the pair; refusing to blend them"

    with_subsurfaces = [s.nameString() for s in (s1, s2) if len(s.subSurfaces()) > 0]
    if with_subsurfaces:
        return (
            f"carries subsurfaces ({', '.join(with_subsurfaces)}); trimming would strand "
            "windows/doors outside their parent and removing would silently delete them"
        )

    return None


def _find_overlapping_pairs(space: openstudio.model.Space) -> list[tuple[Any, Any, Any, Any]]:
    """Same-space, coincident-plane surface pairs with true 2D overlap area.

    Returns (surface1, surface2, forward_transform, IntersectionResult) — the transform
    maps the intersection result's local-frame points back to the model's global frame.
    """
    surfaces = list(space.surfaces())
    planes: list[Any] = []
    for s in surfaces:
        try:
            planes.append(s.plane())
        except Exception:
            planes.append(None)

    pairs = []
    for (i, s1), (j, s2) in itertools.combinations(enumerate(surfaces), 2):
        p1, p2 = planes[i], planes[j]
        if p1 is None or p2 is None:
            continue
        if not (p1.equal(p2, PLANE_TOLERANCE_M) or p1.reverseEqual(p2, PLANE_TOLERANCE_M)):
            continue

        to_local = openstudio.Transformation.alignFace(s1.vertices()).inverse()
        face1 = normalize_local_frame_winding(to_local * s1.vertices())
        face2 = normalize_local_frame_winding(to_local * s2.vertices())
        result = openstudio.intersect(face1, face2, PLANE_TOLERANCE_M)
        if not result.is_initialized():
            continue

        orig_area1 = openstudio.getArea(face1)
        if not orig_area1.is_initialized():
            continue
        remainder_area = sum(
            a.get() for poly in result.get().newPolygons1()
            if (a := openstudio.getArea(_to_vector(poly))).is_initialized()
        )
        overlap_area = max(orig_area1.get() - remainder_area, 0.0)
        if overlap_area <= MIN_OVERLAP_AREA_M2:
            continue

        pairs.append((s1, s2, to_local.inverse(), result.get()))
    return pairs


def _prepare_remainder(
    surface: openstudio.model.Surface, remainder_polys: list[Any], forward: openstudio.Transformation,
) -> tuple[openstudio.Point3dVector | None, float | None]:
    """Build a surface's replacement vertices from its remainder, WITHOUT mutating it.

    Separated from application so both sides of a pair can be validated before either is
    written: mutating the first and then discovering the second is unusable would leave
    the space half-trimmed while the pair got reported as merely skipped.

    The remainder comes back in the intersection's local frame, so the loop is oriented
    against the surface's own current outward normal — read here, before any setVertices
    call. Using the local-frame z-sign rule on these global points instead would flip
    every horizontal surface to face downward.
    """
    if len(remainder_polys) != 1:
        return None, None  # splits into disjoint pieces — ambiguous, not attempted

    local_points = _to_vector(remainder_polys[0])
    area = openstudio.getArea(local_points)
    if not area.is_initialized() or area.get() <= MIN_REMAINDER_AREA_M2:
        return None, None

    global_points = align_to_reference_normal(forward * local_points, surface.outwardNormal())
    return global_points, round(area.get(), 4)


def trim_overlapping_surfaces() -> dict[str, Any]:
    """Trim same-space surfaces with a genuine 2D overlap to their non-overlapping remainder.

    Scoped to spaces that are currently non-enclosed — deliberately, not just for
    efficiency: a coplanar sliver artifact can coexist with an already-fully-enclosed
    space without breaking it (overlap and enclosure are independent problems), and
    trimming/removing it there would be an unrequested, unnecessary change to geometry
    that was never broken. Only spaces actually failing Space.isEnclosedVolume() are
    touched.

    Detects coincident-plane surface pairs with true overlap area (not just a shared
    edge) via the same openstudio.intersect() approach repair_and_validate_gbxml_geometry
    already uses to report overlapping_surfaces, then replaces each surface's vertices
    with its own non-overlapping remainder (openstudio.intersect()'s newPolygons1()/
    newPolygons2()) — or removes it outright if that remainder is empty, i.e. it was
    fully contained within the other. Only the simple case (each side's remainder is a
    single polygon) is handled; a remainder that splits into multiple disjoint pieces is
    reported as skipped rather than guessed at, as is a pair whose overlap-area
    computation degenerates.

    A pair is only trimmed when the two surfaces are genuinely the same thing twice:
    matching surface type, boundary condition, and construction, and neither carrying a
    subsurface. Anything else is reported as skipped — blending different thermal
    semantics, or cascading a parent removal into its windows and doors, would be silent
    data loss rather than a repair. Both sides' remainders are validated before either is
    written, so a pair is trimmed completely or not at all.

    Run repair_and_validate_gbxml_geometry() before and after to see the effect on
    overlapping_surfaces_count and non_enclosed_spaces_count — trimming an overlap can
    also close a space that was non-enclosed for that reason. match_surfaces() is re-run
    once, batched, if anything changed.
    """
    try:
        model = get_model()
        trimmed: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        any_change = False

        for space in model.getSpaces():
            if space.isEnclosedVolume():
                continue  # scoped to spaces that actually need it — see docstring
            name = space.nameString()
            already_handled: set[str] = set()
            for s1, s2, forward, ir in _find_overlapping_pairs(space):
                s1_name, s2_name = s1.nameString(), s2.nameString()
                if s1_name in already_handled or s2_name in already_handled:
                    skipped.append({
                        "space": name, "surface_1": s1_name, "surface_2": s2_name,
                        "reason": "one of these surfaces is already involved in another "
                                  "overlap handled earlier in this same run; not attempted "
                                  "to avoid compounding changes — re-run to check for more",
                    })
                    continue

                incompatible = _incompatibility_reason(s1, s2)
                if incompatible is not None:
                    skipped.append({
                        "space": name, "surface_1": s1_name, "surface_2": s2_name,
                        "reason": incompatible,
                    })
                    continue

                remainder1 = list(ir.newPolygons1())
                remainder2 = list(ir.newPolygons2())

                # Full containment is asymmetric, not a case for symmetric trimming: if
                # one side's remainder is empty, it's entirely a duplicate of the other —
                # remove just that one and leave the other's geometry untouched, rather
                # than carving a hole out of the surface that was never wrong.
                if not remainder1 or not remainder2:
                    if not remainder1:
                        s1.remove()
                        kept, removed = s2_name, s1_name
                    else:
                        s2.remove()
                        kept, removed = s1_name, s2_name
                    any_change = True
                    already_handled.update((s1_name, s2_name))
                    trimmed.append({
                        "space": name, "removed": removed, "kept_unchanged": kept,
                        "reason": "fully contained within the other — removed as a pure duplicate",
                    })
                    continue

                # Validate both sides before writing either — see _prepare_remainder.
                prepared1, area1 = _prepare_remainder(s1, remainder1, forward)
                if prepared1 is None:
                    skipped.append({
                        "space": name, "surface_1": s1_name, "surface_2": s2_name,
                        "reason": "surface_1's non-overlap remainder splits into multiple "
                                  "disjoint pieces or is degenerate; not attempted",
                    })
                    continue

                prepared2, area2 = _prepare_remainder(s2, remainder2, forward)
                if prepared2 is None:
                    skipped.append({
                        "space": name, "surface_1": s1_name, "surface_2": s2_name,
                        "reason": "surface_2's non-overlap remainder splits into multiple "
                                  "disjoint pieces or is degenerate; not attempted",
                    })
                    continue

                s1.setVertices(prepared1)
                s2.setVertices(prepared2)
                any_change = True
                already_handled.update((s1_name, s2_name))
                trimmed.append({
                    "space": name,
                    "surface_1": s1_name, "surface_1_remaining_area_m2": area1,
                    "surface_2": s2_name, "surface_2_remaining_area_m2": area2,
                })

        if any_change:
            # Geometry has already changed at this point, so a rematching failure must be
            # reported rather than swallowed — otherwise this returns ok:True while the
            # model is left with unmatched shared boundaries.
            match_result = match_surfaces()
            if not match_result.get("ok"):
                return {
                    "ok": False,
                    "error": f"Trimmed {len(trimmed)} overlap(s) but match_surfaces() "
                             f"failed afterward, so shared boundaries may be unmatched: "
                             f"{match_result.get('error')}",
                    "trimmed_count": len(trimmed),
                    "trimmed": trimmed,
                }

        return {
            "ok": True,
            "trimmed_count": len(trimmed),
            "trimmed": trimmed,
            "skipped_count": len(skipped),
            "skipped": skipped,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to trim overlapping surfaces: {e}"}
