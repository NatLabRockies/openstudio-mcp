"""Repair geometry defects that leave a space's volume non-enclosed.

Three independent, targeted fixes — all reported as skipped rather than
guessed at when the geometry is ambiguous:

- repair_missing_roof_ceiling: gbXML/Revit exports commonly carve small
  spaces (closets, cabinets) that get a Floor but no RoofCeiling — nested
  under a bigger room's ceiling in the source model — which leaves
  Space.isEnclosedVolume() failing even after match_surfaces() has already
  reconciled every shared wall it can. Targeted fix for exactly that case:
  one level Floor, uniformly level Wall tops, no existing RoofCeiling.

- merge_coplanar_sliver_surfaces: gbXML/Revit exports commonly split one
  physical wall/floor/ceiling into many tiny same-space coplanar fragments —
  one per adjacent-room boundary segment — instead of one clean surface per
  side. match_surfaces() can't fix this (it only reconciles surfaces
  *between* spaces, never within one); this groups same-space coplanar
  fragments and joins them back into fewer, larger surfaces.

- weld_coincident_vertices: a different, more common defect than either of
  the above — surfaces that are NOT coplanar (e.g. two perpendicular walls,
  or a wall and the floor) whose shared corner doesn't land on the exact
  same point, off by sub-centimeter float noise from the source export.
  Space.isEnclosedVolume() (via openstudio.model.Polyhedron) has its own
  undocumented, non-configurable internal snap tolerance, so this snaps
  each space's own vertices to a shared tolerance-deduplicated pool before
  that check ever runs, rather than relying on Polyhedron being forgiving.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.operations import match_surfaces
from mcp_server.skills.geometry.winding import clockwise, match_normal

# Kept local (not imported from gbxml_import/operations.py's PLANE_TOLERANCE)
# to preserve the existing one-way import direction: gbxml_import depends on
# geometry, never the reverse.
LEVEL_TOLERANCE_M = 0.01
MIN_NEW_SURFACE_AREA_M2 = 0.01

# Same tolerance and same one-way-dependency reasoning as above, for the
# merge helpers below.
PLANE_TOLERANCE_M = 0.01
MIN_MERGED_SURFACE_AREA_M2 = 0.01

# Looser than PLANE_TOLERANCE_M/LEVEL_TOLERANCE_M (0.01) so welding actually
# catches gaps those miss, tighter than Polyhedron's own undocumented
# internal snap (empirically between 0.012m and 0.013m on a synthetic test —
# see weld_coincident_vertices' docstring) so this tool does the real work
# rather than relying on that undocumented behavior.
WELD_TOLERANCE_M = 0.02
MIN_WELDED_SURFACE_AREA_M2 = 0.01


def _z_values(vertices: openstudio.Point3dVector) -> list[float]:
    return [p.z() for p in vertices]


def _is_level(vertices: openstudio.Point3dVector, tolerance: float = LEVEL_TOLERANCE_M) -> bool:
    zs = _z_values(vertices)
    return (max(zs) - min(zs)) <= tolerance


def repair_missing_roof_ceiling() -> dict[str, Any]:
    """Synthesize a RoofCeiling surface for spaces that have a Floor but no ceiling.

    Run repair_and_validate_gbxml_geometry() first to see which spaces need
    this (has_floor=True, has_roofceiling=False in its non_enclosed_spaces
    list), and again afterward to confirm they're now enclosed.

    Per space, requires: exactly one Floor surface, at least one Wall
    surface, a level floor, and uniformly level wall tops — a flat ceiling
    is only synthesized when the geometry actually supports one. New
    surfaces start "Outdoors"; match_surfaces() then runs once to pair any
    that truly coincide with a floor above in an adjacent space, and
    whatever's still unmatched afterward is set to "Adiabatic" rather than
    left facing outdoor weather it almost certainly isn't exposed to.
    """
    try:
        model = get_model()

        # gbXML imports typically carry per-surface constructions and no
        # default construction set, so a synthesized surface with nothing
        # assigned can hit an EnergyPlus severe/fatal ("surface has no
        # construction") the first time anyone simulates the repaired model.
        # Borrow one from an existing RoofCeiling surface elsewhere in the
        # model before falling back to whatever a default construction set
        # would resolve (there usually isn't one on these models).
        donor_construction = next(
            (c.get() for s in model.getSurfaces()
             if s.surfaceType() == "RoofCeiling" and (c := s.construction()).is_initialized()),
            None,
        )

        repaired: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        new_surfaces: list[openstudio.model.Surface] = []

        for space in model.getSpaces():
            name = space.nameString()
            surfaces = list(space.surfaces())

            if any(s.surfaceType() == "RoofCeiling" for s in surfaces):
                continue

            floors = [s for s in surfaces if s.surfaceType() == "Floor"]
            if len(floors) != 1:
                skipped.append({
                    "space": name,
                    "reason": f"expected exactly 1 Floor surface, found {len(floors)}",
                })
                continue

            walls = [s for s in surfaces if s.surfaceType() == "Wall"]
            if not walls:
                skipped.append({"space": name, "reason": "no Wall surfaces to derive ceiling height from"})
                continue

            floor_vertices = list(floors[0].vertices())
            if not _is_level(floor_vertices):
                skipped.append({"space": name, "reason": "non-planar floor, cannot derive a flat ceiling"})
                continue

            wall_max_zs = [max(_z_values(list(w.vertices()))) for w in walls]
            ceiling_z = max(wall_max_zs)
            if any((ceiling_z - z) > LEVEL_TOLERANCE_M for z in wall_max_zs):
                skipped.append({"space": name, "reason": "uneven wall heights, cannot auto-repair a flat ceiling"})
                continue

            # Floor's own vertex order, reversed (flips the outward normal),
            # with Z substituted for the derived ceiling height.
            candidate = openstudio.Point3dVector()
            for p in reversed(floor_vertices):
                candidate.append(openstudio.Point3d(p.x(), p.y(), ceiling_z))

            normal = openstudio.getOutwardNormal(candidate)
            if not normal.is_initialized():
                skipped.append({"space": name, "reason": "could not compute outward normal for candidate ceiling"})
                continue
            if normal.get().z() <= 0:
                candidate = openstudio.reverse(candidate)
                normal = openstudio.getOutwardNormal(candidate)
                if not normal.is_initialized() or normal.get().z() <= 0:
                    skipped.append({"space": name, "reason": "unexpected floor winding, cannot orient ceiling"})
                    continue

            try:
                surface = openstudio.model.Surface(candidate, model)
            except Exception as e:
                skipped.append({"space": name, "reason": f"failed to construct surface: {e}"})
                continue

            area = float(surface.grossArea())
            if area <= MIN_NEW_SURFACE_AREA_M2:
                surface.remove()
                skipped.append({"space": name, "reason": f"degenerate ceiling polygon (area={area:.4f} m2)"})
                continue

            surface.setName(f"{name} RoofCeiling (repaired)")
            surface.setSpace(space)
            surface.setSurfaceType("RoofCeiling")
            surface.setOutsideBoundaryCondition("Outdoors")

            # construction() already searches the space/space-type/building
            # default-construction-set hierarchy; only fall back to the
            # borrowed donor if that search comes up empty.
            if not surface.construction().is_initialized() and donor_construction is not None:
                surface.setConstruction(donor_construction)
            resolved_construction = surface.construction()

            new_surfaces.append(surface)
            repaired.append({
                "space": name,
                "new_surface_name": surface.nameString(),
                "area_m2": round(area, 4),
                "ceiling_z": round(ceiling_z, 4),
                "construction": resolved_construction.get().nameString() if resolved_construction.is_initialized() else None,
                "construction_warning": (
                    None if resolved_construction.is_initialized()
                    else "No construction assigned — no default construction set and no existing "
                         "RoofCeiling surface to borrow one from. Assign one before simulating or "
                         "EnergyPlus will likely fail with a missing-construction error."
                ),
            })

        if new_surfaces:
            match_surfaces()
            for entry, surface in zip(repaired, new_surfaces, strict=True):
                matched_space_above = surface.outsideBoundaryCondition() == "Surface"
                if not matched_space_above:
                    surface.setOutsideBoundaryCondition("Adiabatic")
                entry["final_boundary_condition"] = surface.outsideBoundaryCondition()
                entry["boundary_condition_warning"] = (
                    None if matched_space_above
                    else "Set Adiabatic (no matching space above) — correct for a nested space "
                         "under another room's ceiling, but wrong if this space is genuinely "
                         "top-floor with a missing roof; verify before trusting simulation results."
                )

        return {
            "ok": True,
            "repaired_count": len(repaired),
            "repaired": repaired,
            "skipped": skipped,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to repair missing roof/ceiling surfaces: {e}"}


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

                    survivor_normal = openstudio.getOutwardNormal(survivor.vertices())
                    if not survivor_normal.is_initialized():
                        skipped.append({
                            "space": space_name, "surface_type": surface_type,
                            "surfaces": [s.nameString() for s in group],
                            "reason": "could not compute the survivor's outward normal; "
                                      "refusing to merge without an orientation reference",
                        })
                        continue

                    transform = openstudio.Transformation.alignFace(survivor.vertices()).inverse()
                    polygons = openstudio.Point3dVectorVector()
                    for s in group:
                        polygons.append(clockwise(transform * s.vertices()))

                    joined = openstudio.joinAll(polygons, PLANE_TOLERANCE_M)
                    if len(joined) >= len(group):
                        continue  # nothing actually touches; leave the group alone

                    forward = transform.inverse()
                    # Mapped back to global space, joinAll's loops face opposite the
                    # survivor (alignFace put the survivor's outward normal at +z local,
                    # clockwise() put the join inputs at -z) — orient each final loop to
                    # the survivor's own pre-merge outward normal, never to a global
                    # winding convention.
                    new_loops_3d = [
                        match_normal(forward * loop, survivor_normal.get()) for loop in joined
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
            match_surfaces()

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


def weld_coincident_vertices() -> dict[str, Any]:
    """Snap each space's near-coincident vertices to a shared point, closing corner gaps.

    gbXML/Revit exports commonly leave sub-centimeter float noise between vertices that
    are supposed to coincide — e.g. two perpendicular walls, or a wall and the floor,
    whose shared corner is a few millimeters off between the two surfaces. This is a
    different defect from merge_coplanar_sliver_surfaces' same-plane fragmentation: these
    surfaces are NOT coplanar, so grouping/joining doesn't apply, and match_surfaces()
    doesn't apply either (it only reconciles surfaces *between* spaces, never a space's
    own corners against each other).

    Space.isEnclosedVolume() (via openstudio.model.Polyhedron internally) has its own
    undocumented, non-configurable vertex-merge tolerance — a synthetic box test found it
    silently collapses a 0.012m corner offset (still reports enclosed) but not a 0.013m
    one. That can't be loosened from Python, so this snaps vertices *before* the
    enclosure check ever runs, rather than hoping Polyhedron is forgiving enough.

    Per space (each space's own closure is independent — no cross-space vertex pool):
    every vertex of every surface is run through openstudio.getCombinedPoint() against a
    running per-space point pool, which snaps it to an existing pool point within
    WELD_TOLERANCE_M or adds it as a new one. A surface is only rewritten
    (setVertices()) if that actually changed one of its points. Two safety checks apply
    before rewriting: if two of a surface's *own* vertices snapped to the same point
    (degenerate edge), or the welded polygon's area collapses below
    MIN_WELDED_SURFACE_AREA_M2, that surface is left alone and reported as skipped rather
    than corrupted. match_surfaces() is re-run once, batched, if anything changed.

    Run repair_and_validate_gbxml_geometry() before and after to see the effect on
    non_enclosed_spaces_count.
    """
    try:
        model = get_model()
        welded: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        any_change = False

        for space in model.getSpaces():
            space_name = space.nameString()
            surfaces = list(space.surfaces())
            if not surfaces:
                continue

            pool = openstudio.Point3dVector()
            surfaces_modified: list[str] = []
            vertices_snapped = 0

            for surface in surfaces:
                original = list(surface.vertices())
                welded_points = [
                    openstudio.getCombinedPoint(p, pool, WELD_TOLERANCE_M) for p in original
                ]

                changed = any(
                    a.x() != b.x() or a.y() != b.y() or a.z() != b.z()
                    for a, b in zip(original, welded_points, strict=True)
                )
                if not changed:
                    continue

                seen: set[tuple[float, float, float]] = set()
                degenerate = False
                for p in welded_points:
                    key = (round(p.x(), 9), round(p.y(), 9), round(p.z(), 9))
                    if key in seen:
                        degenerate = True
                        break
                    seen.add(key)
                if degenerate:
                    skipped.append({
                        "space": space_name, "surface": surface.nameString(),
                        "reason": "welding collapsed two of this surface's own vertices "
                                  "onto the same point (degenerate edge); left unchanged",
                    })
                    continue

                new_vertices = openstudio.Point3dVector()
                for p in welded_points:
                    new_vertices.append(p)
                area = openstudio.getArea(new_vertices)
                if not area.is_initialized() or area.get() <= MIN_WELDED_SURFACE_AREA_M2:
                    skipped.append({
                        "space": space_name, "surface": surface.nameString(),
                        "reason": "welded result was degenerate (near-zero area); left unchanged",
                    })
                    continue

                surface.setVertices(new_vertices)
                surfaces_modified.append(surface.nameString())
                vertices_snapped += sum(
                    0 if (a.x() == b.x() and a.y() == b.y() and a.z() == b.z()) else 1
                    for a, b in zip(original, welded_points, strict=True)
                )

            if surfaces_modified:
                any_change = True
                welded.append({
                    "space": space_name,
                    "surfaces_modified": surfaces_modified,
                    "vertices_snapped": vertices_snapped,
                })

        if any_change:
            match_surfaces()

        return {
            "ok": True,
            "welded_space_count": len(welded),
            "welded": welded,
            "skipped_surface_count": len(skipped),
            "skipped": skipped,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to weld coincident vertices: {e}"}
