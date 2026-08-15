"""Re-synchronize the two sides of an interior surface pair after a repair desynchronized them.

A different defect from the four this package's other repair tools address, and the only one
that is invisible until EnergyPlus runs. An interior boundary is two OpenStudio Surfaces that
point at each other via `adjacentSurface()`; E+ requires both to describe the same polygon with
the same vertex count. When they disagree it aborts before simulating at all:

    RoofCeiling:Detailed="...", Vertex size mismatch between base surface ... and outside
    boundary surface ...  The vertex sizes are 4 for base surface and 5 for outside boundary
    surface.  GetSurfaceData: Errors discovered, program terminates.

Nothing else catches this. `validate_model` has no geometry checks, and `match_surfaces()` does
not help despite calling `intersectSurfaces` — it hands the SDK surfaces that are ALREADY paired
("Surface" boundary condition with a live `adjacentSurface` pointer) with no unmatch pass first,
so `intersectSurfaces` never re-splits them; and its returned count is a count of *surfaces*
whose boundary condition string is "Surface", not of consistent *pairs*, so a mismatched pair
increments it twice and looks healthy.

The repair tools create the defect because each mutates one side of a pair in isolation:
`merge_coplanar_sliver_surfaces` replaces a survivor's vertices while the survivor keeps its live
`adjacentSurface` pointer, and `weld_coincident_vertices` runs a per-space vertex pool (so one
physical corner can snap to different coordinates in two adjacent spaces) and can skip one side
as degenerate while rewriting the other.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.operations import match_surfaces

# Same scale as the sibling repair tools' area guards (MIN_WELDED_SURFACE_AREA_M2,
# MIN_MERGED_SURFACE_AREA_M2) — below this a mirrored polygon is degenerate, not geometry.
MIN_SYNCED_SURFACE_AREA_M2 = 0.01
# Area disagreement between two sides that DO have matching vertex counts. Reported only,
# never repaired: matchSurfaces() has its own ~0.0125m internal tolerance, so small positional
# drift between paired surfaces is expected and harmless, and E+ accepts it.
PAIR_AREA_TOLERANCE_M2 = 0.01
# A polygon needs three points; fewer means the source surface is already corrupt.
MIN_VERTICES = 3


def choose_authoritative_index(sides: list[tuple[str, int, float]]) -> int:
    """Pick which side of a desynchronized pair to keep, from (name, vertex_count, area_m2).

    Deterministic so a repair run is reproducible and its results can be pinned exactly in
    tests: largest area wins, then the higher vertex count, then the lexicographically smaller
    name. Area leads because the side that drifted is typically the one a weld shrank or a
    degenerate-skip left behind, while a merge survivor is the larger, more complete polygon.

    Pure by design — no OpenStudio objects — so the selection rule is unit-testable without
    the SDK.
    """
    ranked = sorted(range(len(sides)), key=lambda i: (-sides[i][2], -sides[i][1], sides[i][0]))
    return ranked[0]


def _pair_key(surface: openstudio.model.Surface, partner: openstudio.model.Surface) -> tuple:
    """Canonical, order-independent identity for a pair, so it is examined once."""
    return tuple(sorted((str(surface.handle()), str(partner.handle()))))


def _space_name(surface: openstudio.model.Surface) -> str:
    space = surface.space()
    return space.get().nameString() if space.is_initialized() else ""


def mirror_onto_partner(
    keep: openstudio.model.Surface,
    rewrite: openstudio.model.Surface,
) -> openstudio.Point3dVector | None:
    """The kept side's polygon expressed in the partner's own coordinates, reversed.

    Surface.vertices() are relative to the owning Space's origin and relative north, so
    copying them across spaces verbatim is only correct when both spaces have an identity
    transformation. gbXML imports do produce identity transforms (verified: the OS:Space
    origin and Direction of Relative North fields come through empty), which is why the
    verbatim copy happened to work — but a model that has been through a tool which sets
    a space origin would have had a surface silently teleported by the difference. Going
    through world coordinates is correct either way and costs one matrix multiply.

    Returns None when either side has no parent space, since there is then no frame to
    convert between.
    """
    keep_space, rewrite_space = keep.space(), rewrite.space()
    if not keep_space.is_initialized() or not rewrite_space.is_initialized():
        return None
    world = keep_space.get().transformation() * keep.vertices()
    return openstudio.reverse(rewrite_space.get().transformation().inverse() * world)


def sync_paired_surface_vertices() -> dict[str, Any]:
    """Mirror one side of each vertex-count-mismatched interior pair onto the other.

    Walks every Surface whose outsideBoundaryCondition is "Surface" and which has an
    adjacentSurface, examining each pair once. A pair whose two sides carry different vertex
    counts is repaired: the authoritative side is chosen by choose_authoritative_index() and the
    partner's vertices are replaced by mirror_onto_partner(), the same polygon in the partner's
    own coordinate frame with reversed winding — the correspondence matchSurfaces() itself
    establishes.

    A pair whose counts agree but whose areas differ by more than PAIR_AREA_TOLERANCE_M2 is
    REPORTED and NOT repaired. E+ accepts it, and silently reshaping a surface on that weaker
    signal would be exactly the kind of guess the sibling repair tools refuse to make.

    Two guards prevent turning a recoverable defect into a worse one: a side carrying
    subsurfaces is never rewritten (its windows and doors are positioned against the polygon it
    has, and would be orphaned outside a replacement), and a mirrored result that collapses
    below MIN_SYNCED_SURFACE_AREA_M2 is abandoned. Both are reported as skipped with a reason
    rather than applied.

    match_surfaces() is re-run once, batched, if anything changed.
    """
    try:
        model = get_model()
        repaired: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        area_mismatches: list[dict[str, Any]] = []
        seen: set[tuple] = set()

        for surface in model.getSurfaces():
            if surface.outsideBoundaryCondition() != "Surface":
                continue
            adjacent = surface.adjacentSurface()
            if not adjacent.is_initialized():
                continue
            partner = adjacent.get()

            key = _pair_key(surface, partner)
            if key in seen:
                continue
            seen.add(key)

            a_vertices = list(surface.vertices())
            b_vertices = list(partner.vertices())
            a_name, b_name = surface.nameString(), partner.nameString()

            if len(a_vertices) < MIN_VERTICES or len(b_vertices) < MIN_VERTICES:
                skipped.append({
                    "surface": a_name, "partner": b_name,
                    "reason": "one side has fewer than three vertices (already degenerate); "
                              "left unchanged",
                })
                continue

            a_area, b_area = float(surface.grossArea()), float(partner.grossArea())

            if len(a_vertices) == len(b_vertices):
                if abs(a_area - b_area) > PAIR_AREA_TOLERANCE_M2:
                    area_mismatches.append({
                        "surface": a_name, "partner": b_name,
                        "area_m2": round(a_area, 4), "partner_area_m2": round(b_area, 4),
                    })
                continue

            sides = [(a_name, len(a_vertices), a_area), (b_name, len(b_vertices), b_area)]
            keep_index = choose_authoritative_index(sides)
            keep = surface if keep_index == 0 else partner
            rewrite = partner if keep_index == 0 else surface

            if rewrite.subSurfaces():
                skipped.append({
                    "surface": keep.nameString(), "partner": rewrite.nameString(),
                    "reason": "the side that would be rewritten carries subsurfaces "
                              "(windows/doors); replacing its vertices could orphan them "
                              "outside the new polygon, not attempted",
                })
                continue

            mirrored = mirror_onto_partner(keep, rewrite)
            if mirrored is None:
                skipped.append({
                    "surface": keep.nameString(), "partner": rewrite.nameString(),
                    "reason": "one side has no parent space, so its vertices cannot be "
                              "converted into the other's coordinate frame; left unchanged",
                })
                continue

            area = openstudio.getArea(mirrored)
            if not area.is_initialized() or area.get() <= MIN_SYNCED_SURFACE_AREA_M2:
                skipped.append({
                    "surface": keep.nameString(), "partner": rewrite.nameString(),
                    "reason": "mirrored result was degenerate (near-zero area); left unchanged",
                })
                continue

            vertices_before = len(rewrite.vertices())
            area_before = float(rewrite.grossArea())
            rewrite.setVertices(mirrored)
            repaired.append({
                "surface": rewrite.nameString(),
                "space": _space_name(rewrite),
                "partner": keep.nameString(),
                "partner_space": _space_name(keep),
                "kept": keep.nameString(),
                "vertices_before": vertices_before,
                "vertices_after": len(rewrite.vertices()),
                "area_before_m2": round(area_before, 4),
                "area_after_m2": round(float(rewrite.grossArea()), 4),
            })

        rematched: int | None = None
        if repaired:
            # Vertices have already moved, so a rematching failure must be reported rather than
            # swallowed — otherwise this returns ok:True with boundaries left unmatched against
            # the new geometry.
            match_result = match_surfaces()
            if match_result.get("ok"):
                # Handed back so the caller can report a post-repair count without paying for a
                # second intersectSurfaces() pass over the whole model, which is the expensive
                # part of match_surfaces() and would be pure duplicate work here.
                rematched = match_result["matched_surfaces"]
            else:
                return {
                    "ok": False,
                    "error": f"Synchronized {len(repaired)} surface pair(s) but match_surfaces() "
                             f"failed afterward, so shared boundaries may be unmatched: "
                             f"{match_result.get('error')}",
                    "paired_vertex_mismatches_repaired_count": len(repaired),
                    "paired_vertex_mismatches_repaired": repaired,
                }

        return {
            "ok": True,
            # None when nothing was repaired, i.e. no rematch was needed and the caller's own
            # earlier count still stands.
            "rematched_surfaces": rematched,
            "paired_vertex_mismatches_repaired_count": len(repaired),
            "paired_vertex_mismatches_repaired": repaired,
            "paired_vertex_mismatches_skipped_count": len(skipped),
            "paired_vertex_mismatches_skipped": skipped,
            "paired_area_mismatches_count": len(area_mismatches),
            "paired_area_mismatches": area_mismatches,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to synchronize paired surface vertices: {e}"}
