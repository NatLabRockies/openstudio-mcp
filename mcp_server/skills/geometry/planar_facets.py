"""Decompose a closed 3D outline into planar facets.

A reconstructed surface outline traced from a space's unpaired edges is not guaranteed
to be planar — the natural "two adjacent walls both missing, meeting at a shared corner"
case traces one non-planar loop that has to become two surfaces. OpenStudio requires each
Surface to be planar, so such a loop is cut into planar pieces along chords (pairs of
non-adjacent vertices) before any surface is built.

Kept separate from edge_topology.py's connectivity reasoning: this module only answers
"is this polygon flat, and if not, how do I cut it into flat pieces" and has no notion of
edges, degrees, or components.
"""
from __future__ import annotations

import openstudio

Point3d = openstudio.Point3d

PLANARITY_TOLERANCE_M = 0.01
MAX_SPLIT_DEPTH = 4
# MAX_SPLIT_DEPTH bounds recursion depth but not total work: each level considers O(n^2)
# chord candidates, so depth alone allows ~(n^2/2)^depth planarity checks (~1.3e9 for a
# 20-vertex loop). This bounds the actual work. Necessary because these outlines come from
# imported, attacker-influenceable geometry and tool calls have no timeout.
MAX_FACET_SPLIT_CANDIDATES = 5000


class SearchBudgetExceeded(Exception):
    """A cost-bounded search hit its budget before finding an answer.

    Carries a human-readable reason so the caller can report the component as
    skipped with the specific limit that stopped it, rather than a generic failure.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def is_planar(points: list[Point3d], tol: float = PLANARITY_TOLERANCE_M) -> bool:
    pv = openstudio.Point3dVector()
    for p in points:
        pv.append(p)
    try:
        plane = openstudio.Plane(pv)
    except Exception:
        return False
    return all(plane.pointOnPlane(p, tol) for p in points)


def split_planar_facets(
    loop: list[Point3d], depth: int = 0, budget: list[int] | None = None,
) -> list[list[Point3d]] | None:
    """Recursively decompose a non-planar closed loop into planar facets via chords.

    Peels off one planar arc at a time (a contiguous run of the loop, closed by a new
    chord connecting its two ends) and recurses on the remainder. Candidates are tried
    largest-arc-first: any 3 points are trivially planar, so searching small-to-large
    would always peel off a minimal triangle first and fragment far more than the
    geometry actually needs — the natural "two walls meeting at a corner" case should
    resolve to two arcs of roughly half the loop each, not a fan of triangles.

    Bounded twice over: MAX_SPLIT_DEPTH caps recursion depth, and `budget` (a single
    mutable counter threaded through the whole recursion) caps total candidates
    evaluated. Depth alone is not enough — each level considers O(n^2) chords, so the
    product across levels is what actually needs limiting. Raises SearchBudgetExceeded
    when the counter runs out so the caller can report a specific reason.
    """
    if budget is None:
        budget = [MAX_FACET_SPLIT_CANDIDATES]

    if is_planar(loop):
        return [loop]
    if depth >= MAX_SPLIT_DEPTH or len(loop) < 4:
        return None

    n = len(loop)
    candidates = []
    for i in range(n):
        for j in range(i + 2, n):
            if i == 0 and j == n - 1:
                continue  # arc1 would be the whole loop, arc2 empty
            arc1 = loop[i:j + 1]
            arc2 = loop[j:] + loop[:i + 1]
            if len(arc1) < 3 or len(arc2) < 3:
                continue
            candidates.append((arc1, arc2))
    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)

    for arc1, arc2 in candidates:
        if budget[0] <= 0:
            raise SearchBudgetExceeded(
                f"facet-split search exceeded {MAX_FACET_SPLIT_CANDIDATES} candidates "
                f"on a {n}-vertex outline; not decomposed",
            )
        budget[0] -= 1
        if not is_planar(arc1):
            continue
        rest = split_planar_facets(arc2, depth + 1, budget)
        if rest is not None:
            return [arc1, *rest]
    return None


def new_budget() -> list[int]:
    """A fresh shared work counter for a run of related facet-split attempts.

    Pass one of these through every `facets_for_loops` call belonging to the same
    component so the cap applies to the component's total work. Letting each attempt
    start fresh would multiply the real bound by the number of attempts.
    """
    return [MAX_FACET_SPLIT_CANDIDATES]


def facets_for_loops(
    loops: list[list[Point3d]], budget: list[int] | None = None,
) -> list[list[Point3d]] | None:
    """Split every loop into planar facets, or None if any loop can't be decomposed.

    `budget` is shared across all loops here and, when the caller passes its own, across
    every attempt in the wider search — see `new_budget`.
    """
    if budget is None:
        budget = new_budget()
    facets: list[list[Point3d]] = []
    for loop in loops:
        split = split_planar_facets(loop, budget=budget)
        if split is None:
            return None
        facets.extend(split)
    return facets
