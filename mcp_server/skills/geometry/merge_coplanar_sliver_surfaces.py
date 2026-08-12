"""Merge same-space coplanar wall/floor/ceiling fragments into fewer, larger surfaces.

gbXML/Revit exports commonly split one physical wall/floor/ceiling into many tiny
same-space coplanar fragments — one per adjacent-room boundary segment — instead of one
clean surface per side. match_surfaces() can't fix this (it only reconciles surfaces
*between* spaces, never within one); this groups same-space coplanar fragments and joins
them back into fewer, larger surfaces.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.operations import match_surfaces
from mcp_server.skills.geometry.winding import (
    align_to_reference_normal,
    normalize_local_frame_winding,
)

# Kept local (not imported from gbxml_import/operations.py's PLANE_TOLERANCE) to preserve
# the existing one-way import direction: gbxml_import depends on geometry, never the
# reverse.
PLANE_TOLERANCE_M = 0.01
MIN_MERGED_SURFACE_AREA_M2 = 0.01


def _group_coplanar_fragments(
    surfaces: list[openstudio.model.Surface],
) -> list[list[openstudio.model.Surface]]:
    """Bucket surfaces whose planes coincide (same or mirrored) within tolerance.

    O(n^2) pairwise plane comparison — same cost/frequency justification as
    gbxml_import/operations.py's _surface_overlaps: cheap per-comparison, small
    per-space surface counts, runs once per call.
    """
    planes: list[Any] = []
    for s in surfaces:
        try:
            planes.append(s.plane())
        except Exception:
            planes.append(None)

    groups: list[list[openstudio.model.Surface]] = []
    used: set[int] = set()
    for i, s1 in enumerate(surfaces):
        if i in used or planes[i] is None:
            continue
        group = [s1]
        used.add(i)
        for j in range(i + 1, len(surfaces)):
            if j in used or planes[j] is None:
                continue
            if planes[i].equal(planes[j], PLANE_TOLERANCE_M) or planes[i].reverseEqual(planes[j], PLANE_TOLERANCE_M):
                group.append(surfaces[j])
                used.add(j)
        groups.append(group)
    return groups


def merge_coplanar_sliver_surfaces() -> dict[str, Any]:
    """Merge same-space coplanar wall/floor/ceiling fragments into fewer, larger surfaces.

    gbXML/Revit exports commonly split one physical wall, floor, or ceiling into many
    tiny fragments — one per adjacent-room boundary segment — instead of one clean
    surface per side. Fragment areas still sum correctly (zero_volume_zone_count stays
    0), but the seams between fragments don't align to tight tolerance, so
    Space.isEnclosedVolume() fails even though nothing is geometrically missing.
    match_surfaces() cannot fix this: OpenStudio's intersectSurfaces()/matchSurfaces()
    explicitly skip surface pairs within the same space.

    Groups same-space, coplanar, same-type fragments that also share a boundary
    condition and construction, joins their footprints with openstudio.joinAll(), and
    rebuilds fewer/larger Surface objects in their place. Fragments that don't actually
    touch are left alone — joinAll only merges polygons that share an edge. Mixed
    boundary conditions/constructions, and any fragment carrying a subsurface (window or
    door), are reported as skipped rather than guessed at: reparenting a subsurface onto
    a newly-merged surface safely needs a containment check this doesn't attempt.

    Rebuilt surfaces keep the survivor's original outward normal. joinAll() works in a
    local frame whose winding convention is unrelated to the surface's real orientation,
    so the merged loops are re-oriented against the survivor's pre-merge normal — without
    that, every merged RoofCeiling would come back facing downward.

    Run repair_and_validate_gbxml_geometry() before and after to see the effect on
    non_enclosed_spaces_count. match_surfaces() is re-run once, batched, if anything
    changed — a wall that genuinely borders more than one neighbor along its run will
    legitimately get re-split, but against clean, mutually-consistent geometry instead
    of the original noisy tessellation.

    Runs in two passes rather than merging space-by-space as it goes: removing a
    fragment resets the boundary condition of whatever it was matched to in a
    *different* space back to "Outdoors" (OpenStudio's own cleanup, avoiding a dangling
    adjacent-surface reference) — which would otherwise make an unrelated, still-intact
    group in that other space look mismatched purely because of iteration order. Every
    group is decided from one untouched snapshot of the whole model first; only then are
    the decided merges actually applied.
    """
    try:
        model = get_model()
        skipped: list[dict[str, Any]] = []
        planned: list[dict[str, Any]] = []

        # Pass 1: decide, mutating nothing.
        for space in model.getSpaces():
            space_name = space.nameString()
            surfaces = list(space.surfaces())

            for surface_type in ("Wall", "Floor", "RoofCeiling"):
                same_type = [s for s in surfaces if s.surfaceType() == surface_type]
                if len(same_type) < 2:
                    continue

                for group in _group_coplanar_fragments(same_type):
                    if len(group) < 2:
                        continue

                    if any(len(s.subSurfaces()) > 0 for s in group):
                        skipped.append({
                            "space": space_name, "surface_type": surface_type,
                            "surfaces": [s.nameString() for s in group],
                            "reason": "a fragment has subsurfaces (windows/doors); "
                                      "merging would need to reparent them, not attempted",
                        })
                        continue

                    boundary_conditions = {s.outsideBoundaryCondition() for s in group}
                    construction_handles = {
                        c.get().handle() if (c := s.construction()).is_initialized() else None
                        for s in group
                    }
                    if len(boundary_conditions) > 1 or len(construction_handles) > 1:
                        skipped.append({
                            "space": space_name, "surface_type": surface_type,
                            "surfaces": [s.nameString() for s in group],
                            "reason": "mixed boundary conditions or constructions across "
                                      "the group; refusing to blend them",
                        })
                        continue

                    survivor = max(group, key=lambda s: float(s.grossArea()))
                    others = [s for s in group if s is not survivor]

                    # Captured before any mutation — the reference for restoring winding
                    # after joinAll() returns loops in its own local-frame convention.
                    survivor_normal = survivor.outwardNormal()

                    transform = openstudio.Transformation.alignFace(survivor.vertices()).inverse()
                    polygons = openstudio.Point3dVectorVector()
                    for s in group:
                        polygons.append(normalize_local_frame_winding(transform * s.vertices()))

                    joined = openstudio.joinAll(polygons, PLANE_TOLERANCE_M)
                    if len(joined) >= len(group):
                        continue  # nothing actually touches; leave the group alone

                    forward = transform.inverse()
                    new_loops_3d = [
                        align_to_reference_normal(forward * loop, survivor_normal)
                        for loop in joined
                    ]
                    new_loops_3d.sort(
                        key=lambda v: (a.get() if (a := openstudio.getArea(v)).is_initialized() else 0.0),
                        reverse=True,
                    )

                    largest_area = openstudio.getArea(new_loops_3d[0])
                    if not largest_area.is_initialized() or largest_area.get() <= MIN_MERGED_SURFACE_AREA_M2:
                        skipped.append({
                            "space": space_name, "surface_type": surface_type,
                            "surfaces": [s.nameString() for s in group],
                            "reason": "joined result was degenerate (near-zero area)",
                        })
                        continue

                    planned.append({
                        "space": space, "space_name": space_name, "surface_type": surface_type,
                        "fragments_before": len(group), "survivor": survivor, "others": others,
                        "new_loops_3d": new_loops_3d,
                        "boundary_condition": survivor.outsideBoundaryCondition(),
                        "construction": survivor.construction(),
                    })

        # Pass 2: apply. Each plan was already fully decided from pristine state, so a
        # boundary-condition reset triggered by an earlier plan's removal here has no
        # bearing on plans decided in pass 1.
        merged: list[dict[str, Any]] = []
        for plan in planned:
            survivor = plan["survivor"]
            new_loops_3d = plan["new_loops_3d"]

            survivor.setVertices(new_loops_3d[0])
            rebuilt_names = [survivor.nameString()]

            for extra_loop in new_loops_3d[1:]:
                extra_area = openstudio.getArea(extra_loop)
                if not extra_area.is_initialized() or extra_area.get() <= MIN_MERGED_SURFACE_AREA_M2:
                    continue
                extra = openstudio.model.Surface(extra_loop, model)
                extra.setSpace(plan["space"])
                extra.setSurfaceType(plan["surface_type"])
                extra.setOutsideBoundaryCondition(plan["boundary_condition"])
                if plan["construction"].is_initialized():
                    extra.setConstruction(plan["construction"].get())
                rebuilt_names.append(extra.nameString())

            for s in plan["others"]:
                s.remove()

            merged.append({
                "space": plan["space_name"],
                "surface_type": plan["surface_type"],
                "fragments_before": plan["fragments_before"],
                "surfaces_after": len(rebuilt_names),
                "survivor": survivor.nameString(),
            })

        if merged:
            # Geometry has already changed at this point, so a rematching failure must be
            # reported rather than swallowed — otherwise this returns ok:True while the
            # model is left with unmatched shared boundaries.
            match_result = match_surfaces()
            if not match_result.get("ok"):
                return {
                    "ok": False,
                    "error": f"Merged {len(merged)} group(s) but match_surfaces() failed "
                             f"afterward, so shared boundaries may be unmatched: "
                             f"{match_result.get('error')}",
                    "merged_group_count": len(merged),
                    "merged": merged,
                }

        return {
            "ok": True,
            "merged_group_count": len(merged),
            "merged": merged,
            "skipped_group_count": len(skipped),
            "skipped": skipped,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to merge coplanar sliver surfaces: {e}"}
