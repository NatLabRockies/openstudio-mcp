"""Which surfaces EnergyPlus Kiva will accept, and the exposed perimeter of each foundation floor.

Split from kiva_foundation.py to keep both files inside the ~250/400 line budget (CLAUDE.md rule 1).
This half answers "may this surface be a Kiva surface, and how much slab edge is exposed"; the other
half writes the objects.

## The segfault

`Surface.exposedPerimeter()` takes an `openstudio::Polygon3d`, and **it segfaults the interpreter
when the surface has no parent Space** — no Python exception, no error dict, the MCP session dies.
Reproduced twice on OpenStudio 3.11.0. gbXML imports genuinely produce parentless surfaces (that is
why `patch_missing_surfaces` exists), so every path here checks `space().is_initialized()` before
touching that method. `_has_space()` is the guard and it is not optional.

## Computing exposed perimeter

For every candidate floor (ALL at-or-below-grade floors, not just the selected ones), project its
edges to z = 0; a floor's exposed perimeter is the length of its edges minus the intervals that lie
under a collinear edge of another floor. Partial overlaps and T-junctions are handled by interval
subtraction, and a courtyard keeps its edges because no floor lies on their other side.

Neither `Surface.exposedPerimeter()` nor `joinAllPolygons()` is used, for two separate reasons:
both assert |z| <= tolerance on every point, so a basement floor scores 0.0 through them; and the
join fills holes, so a building around an open courtyard lost the courtyard's 40 m entirely
(3x3 ring of 10 m slabs: 120 m instead of 160 m). On `exampleModel()` the interval method gives
each quadrant floor 20.0 and 80.0 in total, matching the SDK where the SDK is right.

## The EnergyPlus rules, from the 25.2 binary's own error strings

  - only one floor per Foundation:Kiva object
  - only floor and wall surfaces may reference a Foundation boundary condition
  - a Foundation surface with no SurfaceProperty:ExposedFoundationPerimeter is fatal
  - Kiva walls must have no more than four vertices
  - "Foundation" boundary condition must use only regular material objects (no massless/no-mass)
  - "Foundation" is not allowed with windows
  - Kiva requires a weather file; it cannot run design-day-only
  - paired wall lengths must not exceed the floor's exposed perimeter

Everything cheap to check is checked here and the surface is refused with a reason. Nothing is
half-written and nothing is guessed — the same posture as ground_contact.py, which refuses to decide
whether a slab is on grade or over a crawlspace.
"""
from __future__ import annotations

from typing import Any

from mcp_server.skills.geometry.edge_graph import point_key
from mcp_server.skills.geometry.ground_contact import (
    GRADE_TOLERANCE_M,
    MIN_BURIED_WALL_FRACTION,
    world_z_range,
)

MAX_KIVA_WALL_VERTICES = 4

# A matched interior boundary condition: the surface has a partner, not soil. Never a Kiva
# candidate regardless of depth, and never part of the ground-contact footprint.
_MATCHED_INTERIOR = "Surface"

# Collinearity and overlap tolerance for the exposed-perimeter edge scoring. Matches the value
# both vendored implementations pass to joinAllPolygons and the scale of the sibling geometry
# guards (PLANE_TOLERANCE, GRADE_TOLERANCE_M).
POLYGON_JOIN_TOLERANCE_M = 0.01

# Above this many eligible floors, EnergyPlus builds that many separate 2D finite-difference
# domains (one Kiva object per floor is its rule, not a choice) and the run time stops being
# incidental. The caller must opt in past this.
KIVA_DOMAIN_WARN_THRESHOLD = 20


def _has_space(surface) -> bool:
    """Guard for the exposedPerimeter segfault. Never call that method without this."""
    return surface.space().is_initialized()


def _world_vertices(surface):
    """Surface vertices in world coordinates, or None when it has no parent space."""
    if not _has_space(surface):
        return None
    return surface.space().get().transformation() * surface.vertices()


def _layers_are_standard_opaque(surface) -> tuple[bool, str | None]:
    """(ok, reason). EnergyPlus refuses a Foundation surface whose construction has no-mass layers."""
    construction = surface.construction()
    if not construction.is_initialized():
        return False, "no construction assigned"
    layered = construction.get().to_LayeredConstruction()
    if not layered.is_initialized():
        return False, "construction is not a layered construction"
    layers = layered.get().layers()
    if not layers:
        return False, "construction has no layers"
    for layer in layers:
        if not layer.to_StandardOpaqueMaterial().is_initialized():
            return False, (
                f"construction layer '{layer.nameString()}' is not a standard opaque material — "
                f"EnergyPlus refuses massless layers on a Foundation surface"
            )
    return True, None


def kiva_surface_blockers(surface) -> list[str]:
    """Every reason EnergyPlus would refuse this surface as a Kiva surface. Empty means eligible."""
    blockers: list[str] = []

    surface_type = surface.surfaceType()
    if surface_type not in ("Floor", "Wall"):
        blockers.append(f"surface type is {surface_type}; Kiva accepts only Floor and Wall")

    if not _has_space(surface):
        blockers.append("surface has no parent space")

    if len(surface.subSurfaces()) > 0:
        blockers.append(
            "surface carries windows or doors; the Foundation boundary condition is not allowed "
            "with subsurfaces",
        )

    if surface_type == "Wall" and len(surface.vertices()) > MAX_KIVA_WALL_VERTICES:
        blockers.append(
            f"wall has {len(surface.vertices())} vertices; Kiva walls are limited to "
            f"{MAX_KIVA_WALL_VERTICES}",
        )

    ok, reason = _layers_are_standard_opaque(surface)
    if not ok:
        blockers.append(reason)

    return blockers


def _floor_is_at_or_below_grade(surface) -> bool:
    z_range = world_z_range(surface)
    if z_range is None:
        return False
    return z_range[1] <= GRADE_TOLERANCE_M


def _wall_buried_fraction(surface) -> float | None:
    """Fraction of a wall's height that sits below grade, or None when it has no parent space."""
    z_range = world_z_range(surface)
    if z_range is None:
        return None
    z_min, z_max = z_range
    height = z_max - z_min
    if height <= 0:
        return None
    below = max(0.0, min(z_max, 0.0) - z_min)
    return below / height


def _edge_keys(surface) -> set[frozenset]:
    """The surface's edges as unordered, rounded endpoint pairs.

    Uses edge_graph.point_key for rounding so this agrees with the repo's other edge work rather
    than inventing a third tolerance.
    """
    vertices = _world_vertices(surface)
    if vertices is None:
        return set()
    keys = [point_key(v) for v in vertices]
    return {
        frozenset((keys[i], keys[(i + 1) % len(keys)]))
        for i in range(len(keys))
        if keys[i] != keys[(i + 1) % len(keys)]
    }


def _shared_edge_length(surface_a, surface_b) -> float:
    """Total length of edges the two surfaces share, in metres."""
    vertices = _world_vertices(surface_a)
    if vertices is None:
        return 0.0
    other = _edge_keys(surface_b)
    total = 0.0
    count = len(vertices)
    for i in range(count):
        p, q = vertices[i], vertices[(i + 1) % count]
        if frozenset((point_key(p), point_key(q))) in other:
            total += (p - q).length()
    return total


def _xy_extent(vertices) -> float:
    """Longest horizontal distance between any two vertices — a rectangular wall's width."""
    best = 0.0
    for i in range(len(vertices)):
        for j in range(i + 1, len(vertices)):
            dx = vertices[i].x() - vertices[j].x()
            dy = vertices[i].y() - vertices[j].y()
            best = max(best, (dx * dx + dy * dy) ** 0.5)
    return best


def paired_wall_length(model, wall_names: list[str]) -> float:
    """Combined horizontal length of the named walls, in metres.

    EnergyPlus compares the walls' combined length against the floor's exposed perimeter and
    refuses the Foundation:Kiva at run time when it is larger; this is the number it compares.
    Kiva walls are limited to four vertices, so the XY extent is the wall's width.
    """
    total = 0.0
    for name in wall_names:
        optional = model.getSurfaceByName(name)
        if not optional.is_initialized():
            continue
        vertices = _world_vertices(optional.get())
        if vertices is not None:
            total += _xy_extent(vertices)
    return total


def floor_perimeter(model, floor_name: str) -> float | None:
    """The floor polygon's full perimeter in metres, or None when it has no parent space."""
    optional = model.getSurfaceByName(floor_name)
    if not optional.is_initialized():
        return None
    vertices = _world_vertices(optional.get())
    if vertices is None:
        return None
    count = len(vertices)
    return sum((vertices[i] - vertices[(i + 1) % count]).length() for i in range(count))


def classify_foundation_candidates(model, include_adiabatic: bool = False) -> dict[str, Any]:
    """Split the model's surfaces into Kiva-eligible floors, pairable walls, and blocked.

    Adiabatic surfaces are excluded by default: `patch_missing_surfaces` sets that condition
    deliberately on facets it could not identify, and silently burying them would undo a decision
    another tool made on purpose. Matched interior surfaces (`Surface`) are always excluded: depth
    says nothing about whether a floor or wall touches soil when it has a partner on the other side.
    """
    eligible_floors: list[dict[str, Any]] = []
    eligible_walls: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []

    for surface in sorted(model.getSurfaces(), key=lambda s: s.nameString()):
        name = surface.nameString()
        surface_type = surface.surfaceType()
        if surface_type not in ("Floor", "Wall"):
            continue

        condition = surface.outsideBoundaryCondition()
        if condition == "Adiabatic" and not include_adiabatic:
            continue
        if condition == _MATCHED_INTERIOR:
            # A matched interior boundary has a partner surface, not soil, however deep it sits —
            # a two-storey basement's middle floor, a crawlspace modelled as a zone, a partition
            # between two basement zones. ground_contact.py makes the same cut. Converting one
            # would also reset the pairing and drop its partner to Outdoors/SunExposed.
            continue

        if not _has_space(surface):
            # Reported rather than skipped: a parentless surface is a real gbXML defect, and it is
            # also the input that segfaults exposedPerimeter, so it must be visible.
            blocked.append({
                "surface": name,
                "surface_type": surface_type,
                "reasons": ["surface has no parent space"],
            })
            continue

        if surface_type == "Floor":
            if not _floor_is_at_or_below_grade(surface):
                continue
        else:
            buried = _wall_buried_fraction(surface)
            if buried is None or buried < MIN_BURIED_WALL_FRACTION:
                continue

        blockers = kiva_surface_blockers(surface)
        if blockers:
            blocked.append({
                "surface": name,
                "surface_type": surface_type,
                "reasons": blockers,
            })
            continue

        entry = {
            "surface": name,
            "outside_boundary_condition": condition,
            "already_kiva": surface.adjacentFoundation().is_initialized(),
        }
        if surface_type == "Floor":
            eligible_floors.append(entry)
        else:
            entry["buried_fraction"] = round(_wall_buried_fraction(surface), 3)
            eligible_walls.append(entry)

    return {
        "eligible_floors": eligible_floors,
        "eligible_walls": eligible_walls,
        "blocked": blocked,
    }


def _zone_key(surface) -> str | None:
    """The thermal zone a surface belongs to, or its space when the space has no zone yet."""
    space = surface.space()
    if not space.is_initialized():
        return None
    zone = space.get().thermalZone()
    if zone.is_initialized():
        return f"zone:{zone.get().nameString()}"
    return f"space:{space.get().nameString()}"


def pair_walls_to_floors(model, floor_names: list[str], wall_names: list[str]) -> dict[str, Any]:
    """Attach each below-grade wall to the floor it shares an edge with, in the same zone.

    EnergyPlus requires a Kiva wall to reference the *same* Foundation object as its floor, and
    that floor must be "within the same Zone" (its own error text), so this is adjacency plus
    zone rather than selection. A wall touching no eligible floor in its zone is reported and
    dropped — never attached to an arbitrary foundation.
    """
    floors = {n: model.getSurfaceByName(n).get() for n in floor_names
              if model.getSurfaceByName(n).is_initialized()}
    pairs: dict[str, list[str]] = {n: [] for n in floors}
    unpaired: list[dict[str, str]] = []

    for wall_name in wall_names:
        optional = model.getSurfaceByName(wall_name)
        if not optional.is_initialized():
            unpaired.append({"surface": wall_name, "reason": "surface not found"})
            continue
        wall = optional.get()
        wall_zone = _zone_key(wall)
        best_floor, best_length = None, 0.0
        touches_other_zone = False
        for floor_name, floor in floors.items():
            length = _shared_edge_length(wall, floor)
            if length <= 0.0:
                continue
            if _zone_key(floor) != wall_zone:
                touches_other_zone = True
                continue
            if length > best_length:
                best_floor, best_length = floor_name, length
        if best_floor is None:
            unpaired.append({
                "surface": wall_name,
                "reason": (
                    "shares an edge only with foundation floors in a different thermal zone; "
                    "EnergyPlus requires the floor and wall of one Foundation:Kiva to be in the "
                    "same zone"
                    if touches_other_zone else
                    "shares no edge with an eligible foundation floor"
                ),
            })
            continue
        pairs[best_floor].append(wall_name)

    return {"pairs": pairs, "unpaired": unpaired}


def compute_exposed_perimeters(model, floor_names: list[str]) -> tuple[dict[str, float], list[str]]:
    """Exposed perimeter per floor: the length of its edges no other ground-contact floor covers.

    Every at-or-below-grade floor in the model takes part as a neighbour, not just the requested
    ones: an interior slab bay only scores zero if its neighbours are present, and a courtyard
    edge only scores exposed if the absence of a neighbour is real.

    Each floor edge is projected to z = 0 and the intervals of it that lie under a collinear edge
    of another floor are subtracted, so partial overlaps and T-junctions (a neighbour subdivided
    differently) are handled, and a courtyard keeps its edges. The earlier recipe joined the
    floor polygons with joinAllPolygons and scored edges against the outline; that join fills
    holes, so a building around an open courtyard lost the courtyard's edges entirely (a 3x3
    ring of 10 m slabs reported 120 m, not 160 m).

    Two floors with the same footprint (a duplicated polygon) are reported and do not cover each
    other: neither has a neighbour on the other side of those edges.
    """
    warnings: list[str] = []
    candidates = [
        s for s in model.getSurfaces()
        if s.surfaceType() == "Floor" and _has_space(s) and _floor_is_at_or_below_grade(s)
        and s.outsideBoundaryCondition() != _MATCHED_INTERIOR
    ]
    if not candidates:
        return {}, ["No at-or-below-grade floors found to build a footprint from."]

    edges_by_floor = {s.nameString(): _flat_edges(_world_vertices(s)) for s in candidates}
    duplicates = _duplicate_footprints(edges_by_floor)
    for a, b in duplicates:
        warnings.append(
            f"Floors '{a}' and '{b}' have the same footprint; neither counts as the other's "
            f"neighbour, so both keep their full exposed perimeter. Check for a duplicated "
            f"floor surface.",
        )

    perimeters: dict[str, float] = {}
    for name in floor_names:
        optional = model.getSurfaceByName(name)
        if not optional.is_initialized():
            continue
        surface = optional.get()
        if not _has_space(surface):
            # The segfault guard, kept although exposedPerimeter() is no longer called: a
            # parentless floor has no world coordinates to score.
            warnings.append(f"Floor '{name}' has no parent space; its perimeter cannot be computed.")
            continue
        own = edges_by_floor.get(name) or _flat_edges(_world_vertices(surface))
        twins = {b for a, b in duplicates if a == name} | {a for a, b in duplicates if b == name}
        neighbours = [
            edge for other, edges in edges_by_floor.items()
            if other != name and other not in twins for edge in edges
        ]
        perimeters[name] = round(_exposed_length(own, neighbours), 4)

    return perimeters, warnings


def _flat_edges(vertices) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """A polygon's edges as 2D endpoint pairs (z dropped), skipping degenerate ones."""
    points = [(v.x(), v.y()) for v in vertices]
    edges = []
    for i in range(len(points)):
        p, q = points[i], points[(i + 1) % len(points)]
        if _distance(p, q) > POLYGON_JOIN_TOLERANCE_M:
            edges.append((p, q))
    return edges


def _distance(p, q) -> float:
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def _duplicate_footprints(edges_by_floor) -> list[tuple[str, str]]:
    """Pairs of floors whose edge sets coincide within tolerance, in either direction."""
    def key(edges):
        def rounded(point):
            return (round(point[0], 3), round(point[1], 3))
        return sorted(tuple(sorted((rounded(p), rounded(q)))) for p, q in edges)

    keyed = {name: key(edges) for name, edges in edges_by_floor.items()}
    names = sorted(keyed)
    return [
        (a, b) for i, a in enumerate(names) for b in names[i + 1:]
        if keyed[a] == keyed[b]
    ]


def _covered_interval(edge, other, tolerance: float) -> tuple[float, float] | None:
    """The [t0, t1] stretch of `edge` (metres from its start) lying under `other`, or None.

    `other` covers part of `edge` when both its endpoints are within `tolerance` of the line
    through `edge` and its projection overlaps the edge by more than `tolerance`. Direction is
    irrelevant: a neighbour traverses a shared edge the opposite way, but a floor with flipped
    winding is still a neighbour.
    """
    (px, py), (qx, qy) = edge
    length = _distance(edge[0], edge[1])
    ux, uy = (qx - px) / length, (qy - py) / length
    ts = []
    for (x, y) in other:
        dx, dy = x - px, y - py
        # Perpendicular distance from the edge's line.
        if abs(dx * uy - dy * ux) > tolerance:
            return None
        ts.append(dx * ux + dy * uy)
    t0, t1 = max(min(ts), 0.0), min(max(ts), length)
    if t1 - t0 <= tolerance:
        return None
    return t0, t1


def _exposed_length(own_edges, neighbour_edges, tolerance: float = POLYGON_JOIN_TOLERANCE_M) -> float:
    """Total length of `own_edges` not covered by any collinear stretch of `neighbour_edges`."""
    total = 0.0
    for edge in own_edges:
        length = _distance(edge[0], edge[1])
        intervals = sorted(
            interval for interval in (
                _covered_interval(edge, other, tolerance) for other in neighbour_edges
            ) if interval is not None
        )
        covered = 0.0
        current: tuple[float, float] | None = None
        for t0, t1 in intervals:
            if current is None or t0 > current[1]:
                if current is not None:
                    covered += current[1] - current[0]
                current = (t0, t1)
            else:
                current = (current[0], max(current[1], t1))
        if current is not None:
            covered += current[1] - current[0]
        total += max(length - covered, 0.0)
    return total
