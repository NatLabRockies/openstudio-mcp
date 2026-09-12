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

Verified recipe, and the only one that works:

    polys = openstudio.Point3dVectorVector()
    for f in every_candidate_floor:                  # ALL of them, not just the selected ones
        polys.append(f.space().get().transformation() * f.vertices())
    joined = openstudio.joinAllPolygons(polys, 0.01)
    exposed = sum(f.exposedPerimeter(j) for j in joined)

On `exampleModel()` this gives each of the four quadrant floors 20.0 and a total of 80.0 — exactly
the footprint. A hand-built `Polygon3d` returns 0.0 because the winding does not match, so the join
is mandatory. Neighbouring floors must be in the join or an interior slab bay will not correctly
score zero. A disjoint-wing model produces several polygons and each floor scores against exactly
one, so summing across them is both required and safe.

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

import openstudio

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

# joinAllPolygons tolerance. Matches the value both vendored implementations use and the scale of
# the sibling geometry guards (PLANE_TOLERANCE, GRADE_TOLERANCE_M).
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


def pair_walls_to_floors(model, floor_names: list[str], wall_names: list[str]) -> dict[str, Any]:
    """Attach each below-grade wall to the floor it shares an edge with.

    EnergyPlus requires a Kiva wall to reference the *same* Foundation object as its floor, so this
    is adjacency rather than selection. A wall touching no eligible floor is reported and dropped —
    never attached to an arbitrary foundation.
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
        best_floor, best_length = None, 0.0
        for floor_name, floor in floors.items():
            length = _shared_edge_length(wall, floor)
            if length > best_length:
                best_floor, best_length = floor_name, length
        if best_floor is None:
            unpaired.append({
                "surface": wall_name,
                "reason": "shares no edge with an eligible foundation floor",
            })
            continue
        pairs[best_floor].append(wall_name)

    return {"pairs": pairs, "unpaired": unpaired}


def compute_exposed_perimeters(model, floor_names: list[str]) -> tuple[dict[str, float], list[str]]:
    """Exposed perimeter per floor, from the joined footprint of every candidate floor.

    The join deliberately spans every at-or-below-grade floor in the model, not just the requested
    ones: an interior slab bay only scores zero if its neighbours are present in the footprint.
    """
    warnings: list[str] = []
    candidates = [
        s for s in model.getSurfaces()
        if s.surfaceType() == "Floor" and _has_space(s) and _floor_is_at_or_below_grade(s)
        and s.outsideBoundaryCondition() != _MATCHED_INTERIOR
    ]
    if not candidates:
        return {}, ["No at-or-below-grade floors found to build a footprint from."]

    polys = openstudio.Point3dVectorVector()
    for surface in candidates:
        polys.append(_world_vertices(surface))

    try:
        joined = openstudio.joinAllPolygons(polys, POLYGON_JOIN_TOLERANCE_M)
    except Exception as e:
        return {}, [f"Could not join floor polygons into a footprint: {e}"]

    if not joined:
        return {}, ["Joining the floor polygons produced no footprint."]

    perimeters: dict[str, float] = {}
    for name in floor_names:
        optional = model.getSurfaceByName(name)
        if not optional.is_initialized():
            continue
        surface = optional.get()
        if not _has_space(surface):
            # The segfault guard. Reported, never called.
            warnings.append(f"Floor '{name}' has no parent space; its perimeter cannot be computed.")
            continue
        perimeters[name] = round(sum(surface.exposedPerimeter(p) for p in joined), 4)

    return perimeters, warnings
