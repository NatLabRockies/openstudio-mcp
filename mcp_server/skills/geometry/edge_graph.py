"""Edge-set primitives shared by the missing-surface reconstruction.

Plain graph/point bookkeeping over a space's unpaired polyhedron edges: keying points
to a tolerance, welding a residual cluster of near-duplicates, splitting an edge set
into independent components, and putting edges into a reproducible order. No tracing
or facet decomposition — see edge_topology.py — and no model mutation.
"""
from __future__ import annotations

from collections import defaultdict

import openstudio

# Looser than weld_coincident_vertices' WELD_TOLERANCE_M (0.02) — safe here because this
# only ever runs on a single space's own already-broken unpaired-edge points, never
# touching geometry that's already fine elsewhere in the model.
LOCAL_WELD_TOLERANCE_M = 0.15

Point3d = openstudio.Point3d
PointPair = tuple[Point3d, Point3d]


def point_key(p: Point3d, nd: int = 4) -> tuple[float, float, float]:
    return (round(p.x(), nd), round(p.y(), nd), round(p.z(), nd))


def local_weld_pairs(pairs: list[PointPair], tol: float) -> list[PointPair]:
    """Snap a space's own unpaired-edge endpoints to each other within tol.

    A second, locally-scoped welding pass: weld_coincident_vertices() already ran a
    tighter tolerance globally, so this only cleans up a residual cluster of
    near-duplicate points among this component's own endpoints. Safe to be looser
    precisely because it cannot touch geometry outside these edges.
    """
    pool: list[Point3d] = []

    def snap(p: Point3d) -> Point3d:
        for q in pool:
            if (abs(p.x() - q.x()) <= tol and abs(p.y() - q.y()) <= tol
                    and abs(p.z() - q.z()) <= tol):
                return q
        pool.append(p)
        return p

    return [(snap(s), snap(e)) for s, e in pairs]


def dedupe_zero_length(pairs: list[PointPair]) -> list[PointPair]:
    """Drop edges welding collapsed into a zero-length (start == end) degenerate pair."""
    return [(s, e) for s, e in pairs if point_key(s) != point_key(e)]


def canonical_edge_order(pairs: list[PointPair]) -> list[PointPair]:
    """Sort edges reproducibly, independent of the order Polyhedron emitted them in.

    `Space.polyhedron().edgesNotTwo()` is C++ and its ordering is not contractual, but it
    reaches almost every decision downstream: which edge `_trace_simple_loop` starts from,
    the vertex order of the loop it produces, and therefore which chords
    `split_planar_facets` tries first. Sorting here is what makes a repeated run on the
    same model produce the same surfaces. Endpoints within each edge are normalized too;
    the graph is undirected (every traversal handles arriving from either end), so this
    only removes variation, never changes connectivity.
    """
    normalized = [
        (s, e) if point_key(s) <= point_key(e) else (e, s)
        for s, e in pairs
    ]
    return sorted(normalized, key=lambda pair: (point_key(pair[0]), point_key(pair[1])))


def degree_map(pairs: list[PointPair]) -> dict[tuple[float, float, float], int]:
    deg: dict[tuple[float, float, float], int] = defaultdict(int)
    for s, e in pairs:
        deg[point_key(s)] += 1
        deg[point_key(e)] += 1
    return deg


def connected_components(pairs: list[PointPair]) -> list[list[int]]:
    """Group edge indices sharing a vertex into independent components (union-find).

    Components come back in a canonical order (by their lowest edge index) so a
    space's holes are always processed in the same sequence regardless of the order
    Polyhedron happened to emit its edges in.
    """
    n = len(pairs)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    by_point: dict[tuple[float, float, float], list[int]] = defaultdict(list)
    for i, (s, e) in enumerate(pairs):
        by_point[point_key(s)].append(i)
        by_point[point_key(e)].append(i)
    for indices in by_point.values():
        for i in indices[1:]:
            union(indices[0], i)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return sorted(groups.values(), key=lambda g: g[0])
