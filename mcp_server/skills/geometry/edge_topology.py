"""Trace a space's unpaired polyhedron edges into the surfaces that are missing.

Pure geometry/graph reasoning with no model mutation — `patch_missing_surfaces` owns
that half, and edge_graph.py holds the plain edge-set bookkeeping this builds on.

A space's unpaired edges (each used by exactly one surface, not the two a closed
volume requires) trace the outline of whatever is missing. Handled here, in
increasing order of uncertainty:

- Multiple separate holes in the same space (independent connected components) —
  each resolved on its own, not required to form a single global loop.
- A closed loop that isn't planar — split into planar facets via chords (see
  planar_facets.py), the same shape as "two adjacent walls both missing, meeting
  at a shared corner."
- A branch point (more than one missing surface converging on one vertex) —
  resolved by searching ways to pair up the incident edges, kept only when every
  resulting facet is unambiguously planar.

Every search here is explicitly cost-bounded (MAX_BRANCH_DEGREE,
MAX_PAIRING_CANDIDATES, and planar_facets' MAX_FACET_SPLIT_CANDIDATES): these run
on imported, attacker-influenceable geometry and the underlying enumerations grow
factorially/polynomially, so an unbounded search would let one malformed model
occupy a worker thread indefinitely. Results are also order-independent — see
edge_graph.canonical_edge_order — so a repeated run gives the same answer.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from mcp_server.skills.geometry.edge_graph import (
    Point3d,
    PointPair,
    degree_map,
    point_key,
)
from mcp_server.skills.geometry.planar_facets import (
    SearchBudgetExceeded,
    facets_for_loops,
    new_budget,
)

# Pairing a branch vertex's incident edges enumerates perfect matchings, which grow as
# (deg-1)!! — 3 ways at degree 4, 15 at degree 6, 105 at degree 8, but 654,729,075 at
# degree 20. Observed real gbXML branch degrees are 4 and 6, so 8 is already generous;
# anything above it is reported as skipped rather than searched. Without this cap a single
# malformed imported model could occupy a worker thread effectively forever (tool calls
# have no timeout and run in a thread that cannot be cancelled).
MAX_BRANCH_DEGREE = 8
# Belt-and-braces counter on candidates actually evaluated, independent of the degree
# formula above: each candidate costs O(edges) to trace, and this stays correct if
# MAX_BRANCH_DEGREE is ever raised or the enumeration changes shape.
MAX_PAIRING_CANDIDATES = 500


def _trace_simple_loop(pairs: list[PointPair]) -> list[Point3d] | None:
    """Walk edges into one closed loop, or None if they don't form exactly one.

    Requires every vertex touched by exactly two of the given edges (no branching) and
    the walk to consume every edge exactly once before returning to its start.
    """
    if not pairs:
        return None
    deg = degree_map(pairs)
    if any(d != 2 for d in deg.values()):
        return None

    adjacency: dict[tuple[float, float, float], list[int]] = defaultdict(list)
    for i, (s, e) in enumerate(pairs):
        adjacency[point_key(s)].append(i)
        adjacency[point_key(e)].append(i)

    start_key = point_key(pairs[0][0])
    current_key = point_key(pairs[0][1])
    ordered = [pairs[0][0], pairs[0][1]]
    used = {0}
    prev = 0

    while current_key != start_key:
        if len(used) >= len(pairs):
            return None
        candidates = [i for i in adjacency[current_key] if i != prev]
        if len(candidates) != 1 or candidates[0] in used:
            return None
        i = candidates[0]
        used.add(i)
        s, e = pairs[i]
        sk, ek = point_key(s), point_key(e)
        if sk == current_key:
            ordered.append(e)
            current_key = ek
        else:
            ordered.append(s)
            current_key = sk
        prev = i

    if len(used) != len(pairs):
        return None
    return ordered[:-1]  # last point duplicates the first (closes the loop)


def _trace_with_pairing(
    pairs: list[PointPair], branch_key: tuple[float, float, float], pairing: list[tuple[int, int]],
) -> list[list[Point3d]] | None:
    """Trace all loops given a specific way of pairing the branch vertex's edges.

    Away from the branch vertex, tracing works exactly like _trace_simple_loop (the
    other incident edge is the only option). At the branch vertex, only the edge this
    pairing assigns as the partner of the one just arrived on may continue — this is
    what lets more than one loop pass through the same shared vertex.
    """
    partner: dict[int, int] = {}
    for a, b in pairing:
        partner[a] = b
        partner[b] = a

    adjacency: dict[tuple[float, float, float], list[int]] = defaultdict(list)
    for i, (s, e) in enumerate(pairs):
        adjacency[point_key(s)].append(i)
        adjacency[point_key(e)].append(i)

    n = len(pairs)
    used: set[int] = set()
    loops: list[list[Point3d]] = []

    for start_i in range(n):
        if start_i in used:
            continue
        used.add(start_i)
        s0, e0 = pairs[start_i]
        start_key = point_key(s0)
        ordered = [s0, e0]
        current_key = point_key(e0)
        prev = start_i
        closed = False

        for _ in range(n + 1):
            if current_key == start_key:
                closed = True
                break
            if current_key == branch_key:
                nxt = partner.get(prev)
                if nxt is None or nxt in used:
                    return None
            else:
                candidates = [i for i in adjacency[current_key] if i != prev]
                if len(candidates) != 1:
                    return None
                nxt = candidates[0]
                if nxt in used:
                    return None
            used.add(nxt)
            s, e = pairs[nxt]
            sk, ek = point_key(s), point_key(e)
            if sk == current_key:
                ordered.append(e)
                current_key = ek
            else:
                ordered.append(s)
                current_key = sk
            prev = nxt

        if not closed:
            return None
        loops.append(ordered[:-1])

    if len(used) != n:
        return None
    return loops


def _all_pairings(items: list[int]) -> Any:
    """Yield every perfect matching of items, in a deterministic order.

    Count grows as (len(items)-1)!!, which is why callers must bound the input size
    (MAX_BRANCH_DEGREE) and the number of candidates consumed (MAX_PAIRING_CANDIDATES).
    """
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for k in range(len(rest)):
        pair = (first, rest[k])
        remaining = rest[:k] + rest[k + 1:]
        for sub in _all_pairings(remaining):
            yield [pair, *sub]


def _try_branch_decomposition(
    pairs: list[PointPair],
) -> tuple[list[list[Point3d]] | None, str | None, int]:
    """Resolve a component with exactly one branch vertex into planar facets.

    Tries ways of pairing up the branch vertex's incident edges and keeps a pairing
    only if the component decomposes into closed loops consuming every edge AND every
    resulting loop splits into planar facets. Validating planarity here rather than
    afterward matters: a pairing can be topologically closed but geometrically
    unusable, and checking later meant the first such pairing failed the whole
    component instead of falling through to the next candidate.

    Candidates are enumerated in a deterministic order — over canonically sorted edges,
    so the result never depends on the order Polyhedron emitted them in. Enumeration
    stops once a second valid decomposition turns up: the first one is what gets used,
    and one more is all it takes to know the choice was arbitrary among equals. All
    attempts share a single facet-split budget so the cap bounds the component's total
    work rather than each attempt separately.

    Returns (facets, reason, valid_candidate_count) — the count lets the caller report
    that more than one decomposition was possible. It saturates at 2 by design.

    More than one branch vertex, an odd-degree branch vertex, or a degree above
    MAX_BRANCH_DEGREE isn't attempted — reported as skipped rather than guessed at.
    """
    deg = degree_map(pairs)
    branch_points = [k for k, d in deg.items() if d > 2]
    if len(branch_points) != 1:
        return None, (
            f"{len(branch_points)} branch points (more than one missing surface "
            "converging at each of several vertices); no unambiguous decomposition"
        ), 0
    branch = branch_points[0]
    degree = deg[branch]
    if degree % 2 != 0:
        return None, (
            f"odd-degree branch point (degree {degree}); a closed decomposition would "
            "need every incident edge paired, which an odd count cannot satisfy"
        ), 0
    if degree > MAX_BRANCH_DEGREE:
        return None, (
            f"branch point degree {degree} exceeds the supported maximum of "
            f"{MAX_BRANCH_DEGREE}; enumerating its edge pairings would cost "
            "prohibitively more than the result is worth, so it is not attempted"
        ), 0

    # Canonical edge order so enumeration (and therefore the chosen decomposition) is
    # reproducible run to run, independent of Polyhedron's internal C++ edge ordering.
    incident = sorted(
        (i for i, (s, e) in enumerate(pairs)
         if point_key(s) == branch or point_key(e) == branch),
        key=lambda i: (point_key(pairs[i][0]), point_key(pairs[i][1])),
    )

    first_facets: list[list[Point3d]] | None = None
    valid_count = 0
    evaluated = 0
    budget = new_budget()

    for pairing in _all_pairings(incident):
        if evaluated >= MAX_PAIRING_CANDIDATES:
            return None, (
                f"branch-pairing search exceeded {MAX_PAIRING_CANDIDATES} candidates at "
                f"degree {degree}; not decomposed"
            ), valid_count
        evaluated += 1

        loops = _trace_with_pairing(pairs, branch, pairing)
        if loops is None:
            continue
        try:
            facets = facets_for_loops(loops, budget)
        except SearchBudgetExceeded as e:
            # Only fatal if nothing usable was found first — otherwise the budget ran out
            # while looking for a *second* decomposition, and the first is still good.
            if first_facets is None:
                return None, e.reason, valid_count
            return first_facets, None, valid_count
        if facets is None:
            continue
        valid_count += 1
        if first_facets is None:
            first_facets = facets
        else:
            break  # a second valid reading is all the ambiguity signal the caller needs

    if first_facets is None:
        return None, (
            f"degree-{degree} branch point — no edge pairing produced closed loops that "
            "all decompose into planar facets"
        ), 0
    return first_facets, None, valid_count


def resolve_component(
    pairs: list[PointPair],
) -> tuple[list[list[Point3d]] | None, str | None, int]:
    """Turn one connected component's unpaired edges into a list of planar facets.

    Returns (facets, skip_reason, valid_decomposition_count). The count is 1 for the
    unambiguous non-branching case, and for a branch point reports how many distinct
    edge pairings yielded a fully valid decomposition — more than one means the choice
    was arbitrary among equals, which callers surface rather than hide.
    """
    deg = degree_map(pairs)
    if any(d > 2 for d in deg.values()):
        return _try_branch_decomposition(pairs)

    loop = _trace_simple_loop(pairs)
    if loop is None:
        return None, (
            f"{len(pairs)} unpaired edge(s) do not form a single simple closed loop"
        ), 0

    try:
        facets = facets_for_loops([loop])
    except SearchBudgetExceeded as e:
        return None, e.reason, 0
    if facets is None:
        return None, (
            f"the {len(loop)}-vertex missing-surface outline is not planar "
            "(no valid facet decomposition found)"
        ), 0
    return facets, None, 1
