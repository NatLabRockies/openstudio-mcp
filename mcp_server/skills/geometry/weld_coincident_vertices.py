"""Snap a space's near-coincident vertices together to close sub-centimeter corner gaps.

A different defect from merge_coplanar_sliver_surfaces' same-plane fragmentation: these
surfaces are NOT coplanar (e.g. two perpendicular walls, or a wall and the floor) and
their shared corner is off by float noise from the source export, so grouping/joining
doesn't apply and neither does match_surfaces() (which only reconciles surfaces *between*
spaces, never a space's own corners against each other).
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.operations import match_surfaces

# Looser than the merge/level tolerances (0.01) so welding actually catches gaps those
# miss, tighter than Polyhedron's own undocumented internal snap (empirically between
# 0.012m and 0.013m on a synthetic test — see weld_coincident_vertices' docstring) so this
# tool does the real work rather than relying on that undocumented behavior.
WELD_TOLERANCE_M = 0.02
MIN_WELDED_SURFACE_AREA_M2 = 0.01


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
    (setVertices()) if that actually changed one of its points. Welding moves existing
    vertices without reordering them, so a surface's winding — and therefore its outward
    normal — is preserved by construction. Two safety checks apply before rewriting: if
    two of a surface's *own* vertices snapped to the same point (degenerate edge), or the
    welded polygon's area collapses below MIN_WELDED_SURFACE_AREA_M2, that surface is
    left alone and reported as skipped rather than corrupted. match_surfaces() is re-run
    once, batched, if anything changed.

    Run repair_and_validate_gbxml_geometry() before and after to see the effect on
    non_enclosed_spaces_count.
    """
    try:
        model = get_model()
        welded: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        any_change = False

        # Name order — see match_surfaces() in geometry/operations.py (issue #134). It matters
        # here because the per-space vertex pool snaps each point to the first one it meets
        # within tolerance, so the order decides which coordinate wins.
        for space in sorted(model.getSpaces(), key=lambda s: s.nameString()):
            space_name = space.nameString()
            surfaces = sorted(space.surfaces(), key=lambda s: s.nameString())
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
            # Vertices have already moved, so a rematching failure must be reported rather
            # than swallowed — otherwise this returns ok:True with shared boundaries left
            # unmatched against the new geometry.
            match_result = match_surfaces()
            if not match_result.get("ok"):
                return {
                    "ok": False,
                    "error": f"Welded {len(welded)} space(s) but match_surfaces() failed "
                             f"afterward, so shared boundaries may be unmatched: "
                             f"{match_result.get('error')}",
                    "welded_space_count": len(welded),
                    "welded": welded,
                }

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
