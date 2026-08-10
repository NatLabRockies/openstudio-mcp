"""Reconstruct surfaces missing outright from a space's own polyhedron edges.

Investigation this session (Space.polyhedron().edgesNotTwo(), the same manifold check
Space.isEnclosedVolume() uses internally) found that most non-enclosed-space defects
remaining after weld_coincident_vertices() and merge_coplanar_sliver_surfaces() aren't
tolerance gaps or fragmentation at all — they're surfaces missing outright from the
gbXML/Revit export (e.g. a partition wall exported for one instance of a repeated
apartment unit type but dropped from others on different floors).

edgesNotTwo() takes an includeCreatedEdges argument — passing False hides edges
Polyhedron's own internal colinear-point auto-heal step creates, which can understate
the real defect (confirmed directly: one space reported 6 bad edges with False, the true
8 with True). Always pass True here.

A space's unpaired edges (each used by exactly one surface, not the two a closed volume
requires) trace the outline of whatever's missing. Handled, in increasing order of
uncertainty:
- Multiple separate holes in the same space (independent connected components) — each
  resolved on its own, not required to form a single global loop.
- A closed loop that isn't planar — recursively split into planar facets via chords
  (pairs of non-adjacent vertices), the same shape as "two adjacent walls both missing,
  meeting at a shared corner."
- A branch point (more than one missing surface converging on one vertex) — resolved via
  a bounded search over ways to pair up the incident edges, kept only when every
  resulting facet is unambiguously planar; a small residual cluster of near-duplicate
  points right at the branch is welded first (a tighter tolerance already ran globally in
  weld_coincident_vertices(); this is a second, locally-scoped pass on just this space's
  own unpaired-edge points, safe to be looser since it can't affect already-good
  geometry elsewhere).
Edges used three or more times (a same-space overlap/duplicate defect — a different
problem, see trim_overlapping_surfaces) are excluded before any of the above and reported
separately; they don't block reconstructing whatever else in the same space IS just
missing.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.operations import match_surfaces
from mcp_server.skills.geometry.winding import match_normal

# Kept local (not imported from repair.py's constants) to match this skill's existing
# one-way-dependency policy: each geometry-repair module owns its own tolerances.
PLANARITY_TOLERANCE_M = 0.01
# Deliberately much smaller than the other repair tools' 0.01 m2 degenerate-result guard:
# a facet here is computed exactly from the model's own unpaired edges, not guessed, so a
# genuinely tiny sliver isn't wrong, just physically small — leaving it unpatched would
# mean a topological hole survives for no benefit. Only true near-zero/collinear results
# (the actual "this isn't a real polygon" case) get rejected.
MIN_PATCHED_SURFACE_AREA_M2 = 0.0001
# Looser than weld_coincident_vertices' WELD_TOLERANCE_M (0.02) — safe here because this
# only ever runs on a single space's own already-broken unpaired-edge points, never
# touching geometry that's already fine elsewhere in the model.
LOCAL_WELD_TOLERANCE_M = 0.15
MAX_SPLIT_DEPTH = 4

Point3d = openstudio.Point3d
PointPair = tuple[Point3d, Point3d]


def _point_key(p: Point3d, nd: int = 4) -> tuple[float, float, float]:
    return (round(p.x(), nd), round(p.y(), nd), round(p.z(), nd))


def _local_weld_pairs(pairs: list[PointPair], tol: float) -> list[PointPair]:
    """Snap a space's own unpaired-edge endpoints to each other within tol.

    Same openstudio.getCombinedPoint()-against-a-running-pool primitive as
    weld_coincident_vertices(), just scoped to one already-broken space's leftover
    points instead of a whole space's full vertex set.
    """
    pool = openstudio.Point3dVector()
    welded = []
    for s, e in pairs:
        welded.append((
            openstudio.getCombinedPoint(s, pool, tol),
            openstudio.getCombinedPoint(e, pool, tol),
        ))
    return welded


def _dedupe_zero_length(pairs: list[PointPair]) -> list[PointPair]:
    """Drop edges welding collapsed into a zero-length (start == end) degenerate pair."""
    return [(s, e) for s, e in pairs if _point_key(s) != _point_key(e)]


def _degree_map(pairs: list[PointPair]) -> dict[tuple[float, float, float], int]:
    deg: dict[tuple[float, float, float], int] = defaultdict(int)
    for s, e in pairs:
        deg[_point_key(s)] += 1
        deg[_point_key(e)] += 1
    return deg


def _connected_components(pairs: list[PointPair]) -> list[list[int]]:
    """Group edge indices sharing a vertex into independent components (union-find)."""
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
        by_point[_point_key(s)].append(i)
        by_point[_point_key(e)].append(i)
    for indices in by_point.values():
        for i in indices[1:]:
            union(indices[0], i)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return list(groups.values())


def _trace_simple_loop(pairs: list[PointPair]) -> list[Point3d] | None:
    """Walk edges into one closed loop, or None if they don't form exactly one.

    Requires every vertex touched by exactly two of the given edges (no branching) and
    the walk to consume every edge exactly once before returning to its start.
    """
    if not pairs:
        return None
    deg = _degree_map(pairs)
    if any(d != 2 for d in deg.values()):
        return None

    adjacency: dict[tuple[float, float, float], list[int]] = defaultdict(list)
    for i, (s, e) in enumerate(pairs):
        adjacency[_point_key(s)].append(i)
        adjacency[_point_key(e)].append(i)

    start_key = _point_key(pairs[0][0])
    current_key = _point_key(pairs[0][1])
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
        sk, ek = _point_key(s), _point_key(e)
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
        adjacency[_point_key(s)].append(i)
        adjacency[_point_key(e)].append(i)

    n = len(pairs)
    used: set[int] = set()
    loops: list[list[Point3d]] = []

    for start_i in range(n):
        if start_i in used:
            continue
        used.add(start_i)
        s0, e0 = pairs[start_i]
        start_key = _point_key(s0)
        ordered = [s0, e0]
        current_key = _point_key(e0)
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
            sk, ek = _point_key(s), _point_key(e)
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
    if not items:
        yield []
        return
    first, rest = items[0], items[1:]
    for k in range(len(rest)):
        pair = (first, rest[k])
        remaining = rest[:k] + rest[k + 1:]
        for sub in _all_pairings(remaining):
            yield [pair, *sub]


def _try_branch_decomposition(pairs: list[PointPair]) -> list[list[Point3d]] | None:
    """Resolve a component with exactly one branch vertex into multiple simple loops.

    Bounded search: tries every way of pairing up the branch vertex's incident edges
    (3 ways for a degree-4 vertex, 15 for degree-6 — small enough to brute force), and
    keeps the first pairing where the whole component decomposes into closed loops
    consuming every edge. More than one branch vertex, or an odd-degree branch vertex,
    isn't attempted — reported as skipped rather than guessed at.
    """
    deg = _degree_map(pairs)
    branch_points = [k for k, d in deg.items() if d > 2]
    if len(branch_points) != 1:
        return None
    branch = branch_points[0]
    if deg[branch] % 2 != 0:
        return None

    incident = [i for i, (s, e) in enumerate(pairs)
                if _point_key(s) == branch or _point_key(e) == branch]

    for pairing in _all_pairings(incident):
        loops = _trace_with_pairing(pairs, branch, pairing)
        if loops is not None:
            return loops
    return None


def _is_planar(points: list[Point3d], tol: float) -> bool:
    pv = openstudio.Point3dVector()
    for p in points:
        pv.append(p)
    try:
        plane = openstudio.Plane(pv)
    except Exception:
        return False
    return all(plane.pointOnPlane(p, tol) for p in points)


def _split_planar_facets(loop: list[Point3d], depth: int = 0) -> list[list[Point3d]] | None:
    """Recursively decompose a non-planar closed loop into planar facets via chords.

    Peels off one planar arc at a time (a contiguous run of the loop, closed by a new
    chord connecting its two ends) and recurses on the remainder. Candidates are tried
    largest-arc-first: any 3 points are trivially planar, so searching small-to-large
    would always peel off a minimal triangle first and fragment far more than the
    geometry actually needs — the natural "two walls meeting at a corner" case should
    resolve to two arcs of roughly half the loop each, not a fan of triangles. Bounded by
    MAX_SPLIT_DEPTH — gives up rather than searching indefinitely on a loop that may not
    be decomposable this way at all.
    """
    if _is_planar(loop, PLANARITY_TOLERANCE_M):
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
        if not _is_planar(arc1, PLANARITY_TOLERANCE_M):
            continue
        rest = _split_planar_facets(arc2, depth + 1)
        if rest is not None:
            return [arc1, *rest]
    return None


def _resolve_component(pairs: list[PointPair]) -> tuple[list[list[Point3d]] | None, str | None]:
    """Turn one connected component's unpaired edges into a list of planar facets."""
    deg = _degree_map(pairs)
    if any(d > 2 for d in deg.values()):
        loops = _try_branch_decomposition(pairs)
        if loops is None:
            branch_points = [k for k, d in deg.items() if d > 2]
            return None, (
                f"branch point at {branch_points[0]} ({len(pairs)} unpaired edges) — "
                "no unambiguous decomposition found"
            )
    else:
        loop = _trace_simple_loop(pairs)
        if loop is None:
            return None, (
                f"{len(pairs)} unpaired edge(s) do not form a single simple closed loop"
            )
        loops = [loop]

    facets: list[list[Point3d]] = []
    for loop in loops:
        split = _split_planar_facets(loop)
        if split is None:
            return None, (
                f"the {len(loop)}-vertex missing-surface outline is not planar "
                "(no valid facet decomposition found)"
            )
        facets.extend(split)
    return facets, None


def _space_interior_point(space: openstudio.model.Space) -> Point3d | None:
    """Average of the space's existing surface vertices — an interior reference point.

    Computed from the pre-patch surfaces (call BEFORE adding any reconstructed facet)
    and used to orient each new facet's outward normal away from the space's inside.
    Heuristic, not exact: for a strongly concave space the vertex average can fall
    outside the volume and misorient a facet near the concavity — accepted limitation,
    still strictly better than the arbitrary traced-loop winding it replaces.
    """
    x = y = z = 0.0
    count = 0
    for surface in space.surfaces():
        for p in surface.vertices():
            x += p.x()
            y += p.y()
            z += p.z()
            count += 1
    if count == 0:
        return None
    return openstudio.Point3d(x / count, y / count, z / count)


def _donor_construction(model: openstudio.model.Model, surface_type: str):
    return next(
        (c.get() for s in model.getSurfaces()
         if s.surfaceType() == surface_type and (c := s.construction()).is_initialized()),
        None,
    )


def _build_surface(
    model: openstudio.model.Model, space: openstudio.model.Space, points: list[Point3d],
    interior_point: Point3d | None,
) -> tuple[bool, Any, float | None]:
    """Construct and place one reconstructed surface, or return a skip reason."""
    candidate = openstudio.Point3dVector()
    for p in points:
        candidate.append(p)
    area = openstudio.getArea(candidate)
    if not area.is_initialized() or area.get() <= MIN_PATCHED_SURFACE_AREA_M2:
        area_val = area.get() if area.is_initialized() else 0.0
        return False, f"degenerate reconstructed polygon (area={area_val:.4f} m2)", None

    # The traced loop's winding is arbitrary, but openstudio.model.Surface(vertices,
    # model) infers surfaceType from it (+z RoofCeiling, -z Floor) and the winding IS
    # the outward normal — left arbitrary, a missing ceiling can come back as a
    # downward-facing "Floor" and a wall can face into the space, with wrong solar and
    # film behavior isEnclosedVolume() can't detect. Orient the facet away from the
    # space's interior before constructing.
    if interior_point is not None:
        facet_centroid = openstudio.Point3d(
            sum(p.x() for p in points) / len(points),
            sum(p.y() for p in points) / len(points),
            sum(p.z() for p in points) / len(points),
        )
        candidate = match_normal(candidate, facet_centroid - interior_point)

    try:
        surface = openstudio.model.Surface(candidate, model)
    except Exception as e:
        return False, f"failed to construct surface: {e}", None

    surface.setSpace(space)
    surface.setOutsideBoundaryCondition("Outdoors")
    surface_type = surface.surfaceType()
    donor_construction = _donor_construction(model, surface_type)
    if not surface.construction().is_initialized() and donor_construction is not None:
        surface.setConstruction(donor_construction)
    return True, surface, area.get()


def patch_missing_surfaces() -> dict[str, Any]:
    """Reconstruct a space's missing surfaces from its own unpaired polyhedron edges.

    Space.isEnclosedVolume() fails for a space missing a surface outright just as it does
    for a tolerance gap or a fragmented one — but neither weld_coincident_vertices() nor
    merge_coplanar_sliver_surfaces() can fix a hole, since there's nothing there to snap
    or join. Space.polyhedron().edgesNotTwo(True) finds the edges responsible: each one
    used by only one surface (not the two a closed volume requires) traces the outline of
    whatever's missing.

    Handles, independently per connected component of a space's unpaired edges: multiple
    separate holes in the same space, a closed loop that isn't planar (recursively split
    into planar facets via chords), and a branch point where more than one missing
    surface converges (resolved via a bounded search over edge pairings, with a small
    local vertex-welding pass first to clear residual noise). Edges used three or more
    times (a same-space overlap/duplicate defect — see trim_overlapping_surfaces) are
    excluded and reported separately; they don't block patching whatever else in the same
    space is just missing. A component that still can't be resolved is reported as
    skipped with the specific reason rather than guessed at.

    Run repair_and_validate_gbxml_geometry() before and after to see the effect on
    non_enclosed_spaces_count. match_surfaces() is re-run once, batched, if anything
    changed — if the mirroring space on the other side of a newly-patched wall also gets
    patched in this same pass, the two should pair up into an interior boundary
    automatically; whatever's still unmatched afterward is set to "Adiabatic" rather than
    left facing outdoor weather it almost certainly isn't exposed to.

    Every space attempted is re-checked at the end, not just trusted from the per-component
    decisions above: chord-splitting or branch decomposition introduces new internal
    "chord" edges, and on rare, geometrically tangled spaces those can coincide with an
    already-ambiguous pre-existing edge (observed in practice: a tiny pre-existing sliver
    wall whose corner sits within a hair of a reconstructed facet's own vertex) and leave
    the space still not enclosed even though every component reported success. That gets
    reported as skipped with the real remaining edge count, not silently counted as fixed.
    """
    try:
        model = get_model()
        patched: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        new_surfaces: list[openstudio.model.Surface] = []
        attempted_spaces: list[openstudio.model.Space] = []

        for space in model.getSpaces():
            name = space.nameString()
            if space.isEnclosedVolume():
                continue
            attempted_spaces.append(space)
            # From the pre-patch surfaces only — adding facets below would drift it.
            interior_point = _space_interior_point(space)

            bad_edges = list(space.polyhedron().edgesNotTwo(True))
            overlap_edges = [e for e in bad_edges if e.count() > 2]
            unpaired_pairs = [(e.start(), e.end()) for e in bad_edges if e.count() == 1]

            if overlap_edges:
                skipped.append({
                    "space": name,
                    "reason": f"{len(overlap_edges)} edge(s) used 3+ times — a same-space "
                              "overlap/duplicate defect, not a missing surface; not "
                              "attempted here (see trim_overlapping_surfaces)",
                })

            if not unpaired_pairs:
                continue

            resolved: list[tuple[int, list[list[Point3d]] | None, str | None]] = []
            for comp_idx, indices in enumerate(_connected_components(unpaired_pairs)):
                comp_pairs = [unpaired_pairs[i] for i in indices]
                facets, reason = _resolve_component(comp_pairs)
                if facets is not None:
                    resolved.append((comp_idx, facets, None))
                    continue

                # Local welding only as a fallback for a component that failed on its
                # raw geometry — trying it unconditionally corrupted components that
                # were already fine (e.g. collapsing a tiny genuine sliver's own
                # distinct corners into each other). Welding can change connectivity,
                # so re-split into sub-components rather than assuming it's still one.
                welded = _dedupe_zero_length(_local_weld_pairs(comp_pairs, LOCAL_WELD_TOLERANCE_M))
                if len(welded) < 3:
                    resolved.append((comp_idx, None, reason))
                    continue
                any_sub_failed = False
                sub_facets: list[list[Point3d]] = []
                for sub_indices in _connected_components(welded):
                    sub_pairs = [welded[i] for i in sub_indices]
                    sub_result, sub_reason = _resolve_component(sub_pairs)
                    if sub_result is None:
                        any_sub_failed = True
                        reason = sub_reason
                        break
                    sub_facets.extend(sub_result)
                resolved.append((comp_idx, None if any_sub_failed else sub_facets, reason))

            for comp_idx, facets, reason in resolved:
                if facets is None:
                    skipped.append({"space": name, "component": comp_idx, "reason": reason})
                    continue

                for facet in facets:
                    ok, result, area_val = _build_surface(model, space, facet, interior_point)
                    if not ok:
                        skipped.append({"space": name, "component": comp_idx, "reason": result})
                        continue
                    surface = result
                    resolved_construction = surface.construction()
                    new_surfaces.append(surface)
                    patched.append({
                        "space": name,
                        "component": comp_idx,
                        "surface_type": surface.surfaceType(),
                        "new_surface_name": surface.nameString(),
                        "area_m2": round(area_val, 4),
                        "construction": resolved_construction.get().nameString()
                            if resolved_construction.is_initialized() else None,
                        "construction_warning": (
                            None if resolved_construction.is_initialized()
                            else "No construction assigned — no default construction set "
                                 "and no existing surface of this type to borrow one from. "
                                 "Assign one before simulating or EnergyPlus will likely "
                                 "fail with a missing-construction error."
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

        already_flagged_spaces = {s["space"] for s in skipped}
        for space in attempted_spaces:
            if space.isEnclosedVolume():
                continue
            name = space.nameString()
            if name in already_flagged_spaces:
                continue  # already explained by a component-level or overlap skip above
            remaining = len(list(space.polyhedron().edgesNotTwo(True)))
            skipped.append({
                "space": name,
                "reason": f"still not enclosed after patching ({remaining} bad edge(s) "
                          "remain) despite every component reporting success — likely a "
                          "new internal chord edge coinciding with an already-ambiguous "
                          "pre-existing edge; not further resolved automatically",
            })

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
        return {"ok": False, "error": f"Failed to patch missing surfaces: {e}"}
