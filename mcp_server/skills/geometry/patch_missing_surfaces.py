"""Reconstruct surfaces missing outright from a space's own polyhedron edges.

Investigation (Space.polyhedron().edgesNotTwo(), the same manifold check
Space.isEnclosedVolume() uses internally) found that most non-enclosed-space defects
remaining after weld_coincident_vertices() and merge_coplanar_sliver_surfaces() aren't
tolerance gaps or fragmentation at all — they're surfaces missing outright from the
gbXML/Revit export (e.g. a partition wall exported for one instance of a repeated
apartment unit type but dropped from others on different floors).

edgesNotTwo() takes an includeCreatedEdges argument — passing False hides edges
Polyhedron's own internal colinear-point auto-heal step creates, which can understate
the real defect (confirmed directly: one space reported 6 bad edges with False, the true
8 with True). Always pass True here.

Edges used three or more times (a same-space overlap/duplicate defect — a different
problem, see trim_overlapping_surfaces) are excluded before anything else and reported
separately; they don't block reconstructing whatever else in the same space IS just
missing.

This module owns model mutation only — the edge-graph tracing and facet decomposition
live in edge_topology.py.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.edge_graph import (
    LOCAL_WELD_TOLERANCE_M,
    Point3d,
    canonical_edge_order,
    connected_components,
    dedupe_zero_length,
    local_weld_pairs,
)
from mcp_server.skills.geometry.edge_topology import resolve_component
from mcp_server.skills.geometry.operations import match_surfaces

# Deliberately much smaller than the other repair tools' 0.01 m2 degenerate-result guard:
# a facet here is computed exactly from the model's own unpaired edges, not guessed, so a
# genuinely tiny sliver isn't wrong, just physically small — leaving it unpatched would
# mean a topological hole survives for no benefit. Only true near-zero/collinear results
# (the actual "this isn't a real polygon" case) get rejected.
MIN_PATCHED_SURFACE_AREA_M2 = 0.0001


def _donor_construction(model: openstudio.model.Model, surface_type: str):
    return next(
        (c.get() for s in model.getSurfaces()
         if s.surfaceType() == surface_type and (c := s.construction()).is_initialized()),
        None,
    )


def _build_surface(
    model: openstudio.model.Model, space: openstudio.model.Space, points: list[Point3d],
) -> tuple[bool, Any, float | None]:
    """Construct and place one reconstructed surface, or return a skip reason."""
    candidate = openstudio.Point3dVector()
    for p in points:
        candidate.append(p)
    area = openstudio.getArea(candidate)
    if not area.is_initialized() or area.get() <= MIN_PATCHED_SURFACE_AREA_M2:
        area_val = area.get() if area.is_initialized() else 0.0
        return False, f"degenerate reconstructed polygon (area={area_val:.4f} m2)", None

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


def _resolve_space_components(
    unpaired_pairs: list[tuple[Point3d, Point3d]],
) -> list[tuple[int, list[list[Point3d]] | None, str | None, int]]:
    """Resolve every hole in one space into facets, welding as a per-component fallback."""
    resolved: list[tuple[int, list[list[Point3d]] | None, str | None, int]] = []

    for comp_idx, indices in enumerate(connected_components(unpaired_pairs)):
        comp_pairs = [unpaired_pairs[i] for i in indices]
        facets, reason, ambiguity = resolve_component(comp_pairs)
        if facets is not None:
            resolved.append((comp_idx, facets, None, ambiguity))
            continue

        # Local welding only as a fallback for a component that failed on its raw
        # geometry — trying it unconditionally corrupted components that were already
        # fine (e.g. collapsing a tiny genuine sliver's own distinct corners into each
        # other). Welding can change connectivity, so re-split into sub-components
        # rather than assuming it's still one.
        welded = canonical_edge_order(
            dedupe_zero_length(local_weld_pairs(comp_pairs, LOCAL_WELD_TOLERANCE_M)),
        )
        if len(welded) < 3:
            resolved.append((comp_idx, None, reason, 0))
            continue

        any_sub_failed = False
        sub_facets: list[list[Point3d]] = []
        sub_ambiguity = 0
        for sub_indices in connected_components(welded):
            sub_pairs = [welded[i] for i in sub_indices]
            sub_result, sub_reason, sub_count = resolve_component(sub_pairs)
            if sub_result is None:
                any_sub_failed = True
                reason = sub_reason
                break
            sub_facets.extend(sub_result)
            sub_ambiguity = max(sub_ambiguity, sub_count)
        resolved.append((
            comp_idx,
            None if any_sub_failed else sub_facets,
            reason,
            0 if any_sub_failed else sub_ambiguity,
        ))

    return resolved


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
    into planar facets via chords), and a branch point where more than one missing surface
    converges (resolved via a cost-bounded, deterministic search over edge pairings, with
    a small local vertex-welding pass first to clear residual noise). Edges used three or
    more times (a same-space overlap/duplicate defect — see trim_overlapping_surfaces) are
    excluded and reported separately; they don't block patching whatever else in the same
    space is just missing. A component that still can't be resolved — including one whose
    branch vertex is too high-degree to search affordably — is reported as skipped with the
    specific reason rather than guessed at.

    Reconstructed surfaces start "Outdoors" so match_surfaces() can pair them with a real
    surface on the other side. A patch that finds no partner is set "Adiabatic" with
    NoSun/NoWind, and reported with `boundary_condition_ambiguous: true` (counted in
    `ambiguous_boundary_condition_count`) so the assumption is visible rather than silent.
    Adiabatic because these facets are topological closures traced from a hole's outline —
    on badly broken geometry one need not correspond to any real building element, and zero
    heat flux keeps a surface the tool cannot physically identify from either inventing or
    destroying load. It is wrong for a genuinely exterior wall or roof missing from the
    export; those need overriding, which is what the flag and count are for.

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

            bad_edges = list(space.polyhedron().edgesNotTwo(True))
            overlap_edges = [e for e in bad_edges if e.count() > 2]
            # Canonically ordered so a repeated run on the same model reconstructs the same
            # surfaces — edgesNotTwo()'s own ordering is a C++ implementation detail that
            # otherwise reaches every downstream tracing and chord decision.
            unpaired_pairs = canonical_edge_order(
                [(e.start(), e.end()) for e in bad_edges if e.count() == 1],
            )

            if overlap_edges:
                skipped.append({
                    "space": name,
                    "reason": f"{len(overlap_edges)} edge(s) used 3+ times — a same-space "
                              "overlap/duplicate defect, not a missing surface; not "
                              "attempted here (see trim_overlapping_surfaces)",
                })

            if not unpaired_pairs:
                continue

            for comp_idx, facets, reason, ambiguity in _resolve_space_components(unpaired_pairs):
                if facets is None:
                    skipped.append({"space": name, "component": comp_idx, "reason": reason})
                    continue

                for facet in facets:
                    ok, result, area_val = _build_surface(model, space, facet)
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
                        # >1 means several distinct edge pairings were equally valid and
                        # one was chosen deterministically; the reconstruction is a
                        # legitimate reading of the geometry but not the only one.
                        "decomposition_was_ambiguous": ambiguity > 1,
                    })

        ambiguous_bc_count = 0
        if new_surfaces:
            # Must not be discarded: the boundary-condition decision below reads the
            # results of this matching, so a silent failure here would make every patch
            # look unmatched and be reported as such.
            match_result = match_surfaces()
            if not match_result.get("ok"):
                return {
                    "ok": False,
                    "error": f"Patched {len(patched)} surface(s) but match_surfaces() "
                             "failed afterward, so boundary conditions could not be "
                             f"resolved: {match_result.get('error')}",
                    "patched_count": len(patched),
                    "patched": patched,
                }

            for entry, surface in zip(patched, new_surfaces, strict=True):
                matched = surface.outsideBoundaryCondition() == "Surface"
                if not matched:
                    ambiguous_bc_count += 1
                    surface.setOutsideBoundaryCondition("Adiabatic")
                    # Exposure must follow the boundary condition. A Surface defaults to
                    # SunExposed/WindExposed, and nothing else in this codebase has ever
                    # changed that — harmless while the outside face is adiabatic (no heat
                    # transfer for exposure to modify) but a live error the moment the
                    # surface is left facing Outdoors: full solar gain, wind convection,
                    # and sky longwave on a surface that may not exist physically at all.
                    surface.setSunExposure("NoSun")
                    surface.setWindExposure("NoWind")
                entry["final_boundary_condition"] = surface.outsideBoundaryCondition()
                entry["boundary_condition_ambiguous"] = not matched
                entry["boundary_condition_warning"] = (
                    None if matched
                    else "Assumed Adiabatic (NoSun/NoWind) — no surface was found on the "
                         "other side. These facets are topological closures traced from a "
                         "hole's outline, so on badly broken geometry one need not "
                         "correspond to a real building element; zero heat flux keeps a "
                         "surface the tool cannot identify from inventing or destroying "
                         "load. Wrong if this is genuinely an exterior wall or roof missing "
                         "from the export — override those to Outdoors (with SunExposed/"
                         "WindExposed) before trusting simulation results."
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
            "ambiguous_boundary_condition_count": ambiguous_bc_count,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to patch missing surfaces: {e}"}
