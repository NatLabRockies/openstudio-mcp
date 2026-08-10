"""Reconstruct surfaces missing outright from a space's own polyhedron edges.

Investigation this session (Space.polyhedron().edgesNotTwo(), the same manifold check
Space.isEnclosedVolume() uses internally) found that most non-enclosed-space defects
remaining after weld_coincident_vertices() and merge_coplanar_sliver_surfaces() aren't
tolerance gaps or fragmentation at all — they're surfaces missing outright from the
gbXML/Revit export (e.g. a partition wall exported for one instance of a repeated
apartment unit type but dropped from others on different floors). When a space's
unpaired edges (each used by exactly one surface, not the two a closed volume requires)
chain into exactly one simple, non-branching loop, that loop is the literal outline of
the missing surface. Anything more complex — a branch point where multiple missing
surfaces would meet, more than one separate loop, or edges used three or more times (a
same-space overlap/duplicate defect, a different problem entirely) — is reported as
skipped rather than guessed at.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.operations import match_surfaces

# Kept local (not imported from repair.py's constants) to match this skill's existing
# one-way-dependency policy: each geometry-repair module owns its own tolerances.
PLANARITY_TOLERANCE_M = 0.01
MIN_PATCHED_SURFACE_AREA_M2 = 0.01


def _point_key(p: openstudio.Point3d, nd: int = 4) -> tuple[float, float, float]:
    return (round(p.x(), nd), round(p.y(), nd), round(p.z(), nd))


def _trace_single_loop(edges: list[Any]) -> list[openstudio.Point3d] | None:
    """Walk edges into one closed loop, or None if they don't form exactly one.

    Requires every vertex touched by exactly two of the given edges (no branching) and
    the walk to consume every edge exactly once before returning to its start.
    """
    if not edges:
        return None

    adjacency: dict[tuple[float, float, float], list[int]] = {}
    for i, e in enumerate(edges):
        s_key, e_key = _point_key(e.start()), _point_key(e.end())
        adjacency.setdefault(s_key, []).append(i)
        adjacency.setdefault(e_key, []).append(i)
    if any(len(v) != 2 for v in adjacency.values()):
        return None  # a branch point — more than one missing surface meets here

    start_key = _point_key(edges[0].start())
    current_key = _point_key(edges[0].end())
    ordered_points = [edges[0].start(), edges[0].end()]
    used = {0}
    prev_edge = 0

    while current_key != start_key:
        if len(used) >= len(edges):
            return None
        candidates = [i for i in adjacency[current_key] if i != prev_edge]
        if len(candidates) != 1 or candidates[0] in used:
            return None
        i = candidates[0]
        used.add(i)
        e = edges[i]
        s_key, e_key = _point_key(e.start()), _point_key(e.end())
        if s_key == current_key:
            ordered_points.append(e.end())
            current_key = e_key
        else:
            ordered_points.append(e.start())
            current_key = s_key
        prev_edge = i

    if len(used) != len(edges):
        return None
    return ordered_points[:-1]  # last point duplicates the first (closes the loop)


def _is_planar(points: list[openstudio.Point3d], tol: float) -> bool:
    pv = openstudio.Point3dVector()
    for p in points:
        pv.append(p)
    try:
        plane = openstudio.Plane(pv)
    except Exception:
        return False
    return all(plane.pointOnPlane(p, tol) for p in points)


def _donor_construction(model: openstudio.model.Model, surface_type: str):
    return next(
        (c.get() for s in model.getSurfaces()
         if s.surfaceType() == surface_type and (c := s.construction()).is_initialized()),
        None,
    )


def patch_missing_wall_surfaces() -> dict[str, Any]:
    """Reconstruct a space's missing surfaces from its own unpaired polyhedron edges.

    Space.isEnclosedVolume() fails for a space missing a surface outright just as it does
    for a tolerance gap or a fragmented one — but neither weld_coincident_vertices() nor
    merge_coplanar_sliver_surfaces() can fix a hole, since there's nothing there to snap
    or join. Space.polyhedron().edgesNotTwo() finds the edges responsible: each one used
    by only one surface (not the two a closed volume requires) traces the outline of
    whatever's missing.

    Only reconstructs a space when its unpaired edges chain into exactly one simple,
    non-branching, planar loop. Reported as skipped rather than guessed at when: any
    unpaired edge is instead used three-or-more times (a same-space overlap/duplicate —
    a different defect entirely, see repair_and_validate_gbxml_geometry's
    overlapping_surfaces), the edges don't form exactly one closed loop (a branch point,
    or more than one missing surface), the loop isn't planar, or the resulting polygon is
    degenerate.

    Run repair_and_validate_gbxml_geometry() before and after to see the effect on
    non_enclosed_spaces_count. match_surfaces() is re-run once, batched, if anything
    changed — if the mirroring space on the other side of a newly-patched wall also gets
    patched in this same pass, the two should pair up into an interior boundary
    automatically; whatever's still unmatched afterward is set to "Adiabatic" rather than
    left facing outdoor weather it almost certainly isn't exposed to.
    """
    try:
        model = get_model()
        patched: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        new_surfaces: list[openstudio.model.Surface] = []

        for space in model.getSpaces():
            name = space.nameString()
            if space.isEnclosedVolume():
                continue

            bad_edges = list(space.polyhedron().edgesNotTwo(False))
            overlap_edges = [e for e in bad_edges if e.count() != 1]
            if overlap_edges:
                skipped.append({
                    "space": name,
                    "reason": f"{len(overlap_edges)} edge(s) used 3+ times — a same-space "
                              "overlap/duplicate defect, not a missing surface; not attempted",
                })
                continue

            unpaired = [e for e in bad_edges if e.count() == 1]
            loop = _trace_single_loop(unpaired)
            if loop is None:
                skipped.append({
                    "space": name,
                    "reason": f"{len(unpaired)} unpaired edge(s) do not form a single "
                              "simple closed loop (branch point or multiple missing "
                              "surfaces); not attempted",
                })
                continue

            if not _is_planar(loop, PLANARITY_TOLERANCE_M):
                skipped.append({
                    "space": name,
                    "reason": f"the {len(loop)}-vertex missing-surface outline is not planar",
                })
                continue

            candidate = openstudio.Point3dVector()
            for p in loop:
                candidate.append(p)
            area = openstudio.getArea(candidate)
            if not area.is_initialized() or area.get() <= MIN_PATCHED_SURFACE_AREA_M2:
                skipped.append({
                    "space": name,
                    "reason": f"degenerate reconstructed polygon (area="
                              f"{area.get() if area.is_initialized() else 0.0:.4f} m2)",
                })
                continue

            try:
                surface = openstudio.model.Surface(candidate, model)
            except Exception as e:
                skipped.append({"space": name, "reason": f"failed to construct surface: {e}"})
                continue

            surface.setSpace(space)
            surface.setOutsideBoundaryCondition("Outdoors")
            surface_type = surface.surfaceType()

            donor_construction = _donor_construction(model, surface_type)
            if not surface.construction().is_initialized() and donor_construction is not None:
                surface.setConstruction(donor_construction)
            resolved_construction = surface.construction()

            new_surfaces.append(surface)
            patched.append({
                "space": name,
                "surface_type": surface_type,
                "new_surface_name": surface.nameString(),
                "area_m2": round(area.get(), 4),
                "construction": resolved_construction.get().nameString()
                    if resolved_construction.is_initialized() else None,
                "construction_warning": (
                    None if resolved_construction.is_initialized()
                    else "No construction assigned — no default construction set and no "
                         "existing surface of this type to borrow one from. Assign one "
                         "before simulating or EnergyPlus will likely fail with a "
                         "missing-construction error."
                ),
            })

        if new_surfaces:
            match_surfaces()
            for entry, surface in zip(patched, new_surfaces, strict=True):
                matched = surface.outsideBoundaryCondition() == "Surface"
                if not matched:
                    surface.setOutsideBoundaryCondition("Adiabatic")
                entry["final_boundary_condition"] = surface.outsideBoundaryCondition()
                entry["boundary_condition_warning"] = (
                    None if matched
                    else "Set Adiabatic (no matching surface found on the other side) — "
                         "correct if this is genuinely an interior partition with nothing "
                         "reconstructed opposite it yet, but verify before trusting "
                         "simulation results."
                )

        return {
            "ok": True,
            "patched_count": len(patched),
            "patched": patched,
            "skipped_count": len(skipped),
            "skipped": skipped,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to patch missing wall surfaces: {e}"}
