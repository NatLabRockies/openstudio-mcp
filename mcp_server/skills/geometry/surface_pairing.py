"""Pair reconstructed surfaces the SDK's own matching narrowly missed.

`openstudio.model.matchSurfaces()` pairs surfaces between adjacent spaces, but it
compares vertices against an internal, non-configurable merge tolerance —
empirically ~0.0125 m (see weld_coincident_vertices' docstring for how that was
measured). A surface reconstructed by patch_missing_surfaces can land a few
centimetres off its counterpart in the neighbouring space: unmistakably the same
partition to any reader, but outside what the SDK will accept, so it comes back
unmatched and gets assumed Adiabatic.

This is a deliberately narrow fallback for exactly that case. A pair is only
joined when the two surfaces are essentially the same surface twice — coplanar,
and overlapping across at least MIN_TWIN_OVERLAP_FRACTION of *both* their areas.
Requiring it of both is what keeps a large surface from swallowing a small one
that merely sits on top of it: on this project's own test fixture, a 1474 m2
floor plate overlaps a 1059 m2 one by 72%, and those are genuinely different
surfaces that matchSurfaces() was right to leave alone. Forcing adjacency there
would invent an interzone pair with a 415 m2 area mismatch.

Scope is deliberately narrow in two further ways. Only surfaces created by the
same patch run are considered — never pre-existing geometry, even when it is
unmatched and coincident. An existing "Outdoors" wall is a real modelling
decision someone made; quietly converting it into an interior boundary because a
reconstructed facet happens to land on it is a bigger change than this pass has
any business making, and it fires readily whenever a patched space sits on top of
existing geometry. And both surfaces must currently be unmatched, so an existing
correct pairing is never broken to build this one.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.skills.geometry.winding import normalize_local_frame_winding

PLANE_TOLERANCE_M = 0.10
# Deliberately strict: this fallback exists to recover surfaces the SDK missed by
# a few centimetres, not to reconcile geometry that genuinely differs. At 0.99 of
# both areas the two are the same surface within rounding; anything looser starts
# pairing surfaces that merely overlap.
MIN_TWIN_OVERLAP_FRACTION = 0.99


def _to_vector(points: Any) -> openstudio.Point3dVector:
    pv = openstudio.Point3dVector()
    for p in points:
        pv.append(p)
    return pv


def _space_name(surface: openstudio.model.Surface) -> str | None:
    space = surface.space()
    return space.get().nameString() if space.is_initialized() else None


def _mutual_overlap_fraction(
    s1: openstudio.model.Surface, s2: openstudio.model.Surface,
) -> float | None:
    """Overlap area as a fraction of the LARGER of the two surfaces, or None.

    Taking the larger denominator is what makes this a two-sided test: a small
    surface fully inside a big one scores 1.0 against itself but only
    small/big against the pair, so it cannot pass as a twin.
    """
    try:
        p1, p2 = s1.plane(), s2.plane()
    except Exception:
        return None
    if not (p1.equal(p2, PLANE_TOLERANCE_M) or p1.reverseEqual(p2, PLANE_TOLERANCE_M)):
        return None

    to_local = openstudio.Transformation.alignFace(s1.vertices()).inverse()
    # Winding must be normalized before intersect(): an interior pair faces in
    # opposite directions, and the un-normalized call silently reports no overlap
    # for exactly that case.
    face1 = normalize_local_frame_winding(to_local * s1.vertices())
    face2 = normalize_local_frame_winding(to_local * s2.vertices())

    area1 = openstudio.getArea(face1)
    area2 = openstudio.getArea(face2)
    if not area1.is_initialized() or not area2.is_initialized():
        return None
    larger = max(area1.get(), area2.get())
    if larger <= 0:
        return None

    result = openstudio.intersect(face1, face2, PLANE_TOLERANCE_M)
    if not result.is_initialized():
        return None
    remainder = sum(
        a.get() for poly in result.get().newPolygons1()
        if (a := openstudio.getArea(_to_vector(poly))).is_initialized()
    )
    return max(area1.get() - remainder, 0.0) / larger


def pair_coincident_unmatched(
    candidates: list[openstudio.model.Surface],
) -> list[dict[str, Any]]:
    """Pair still-unmatched candidates with each other where they are the same surface.

    `candidates` are the surfaces one patch run created, and pairing happens only
    among them — the two halves of a partition that was missing from both sides.
    Pre-existing geometry is never read as a partner or modified. Returns one entry
    per pair joined.
    """
    paired: list[dict[str, Any]] = []

    for index, surface in enumerate(candidates):
        if surface.outsideBoundaryCondition() == "Surface":
            continue  # already matched, including by an earlier pass of this loop
        space_name = _space_name(surface)

        for other in candidates[index + 1:]:
            if other.outsideBoundaryCondition() == "Surface":
                continue  # never break an existing, correct pairing
            if _space_name(other) == space_name:
                continue  # same-space overlap is a different defect entirely

            fraction = _mutual_overlap_fraction(surface, other)
            if fraction is None or fraction < MIN_TWIN_OVERLAP_FRACTION:
                continue

            if not surface.setAdjacentSurface(other):
                continue
            paired.append({
                "surface": surface.nameString(),
                "space": space_name,
                "paired_with": other.nameString(),
                "paired_with_space": _space_name(other),
                "overlap_fraction": round(fraction, 4),
            })
            break

    return paired
