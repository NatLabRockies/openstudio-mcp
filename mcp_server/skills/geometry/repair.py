"""Synthesize a missing RoofCeiling for spaces that have a Floor but no ceiling.

gbXML/Revit exports commonly carve small spaces (closets, cabinets) that get a Floor but
no RoofCeiling — nested under a bigger room's ceiling in the source model — which leaves
Space.isEnclosedVolume() failing even after match_surfaces() has already reconciled every
shared wall it can. Targeted fix for exactly that case: one level Floor, uniformly level
Wall tops, no existing RoofCeiling. Anything sloped or ambiguous is reported as skipped
rather than guessed at.

The other non-enclosed-volume repairs live in sibling modules, one per defect:
merge_coplanar_sliver_surfaces (same-plane fragmentation), weld_coincident_vertices
(sub-centimeter corner gaps), patch_missing_surfaces (a surface absent outright), and
trim_overlapping_surfaces (a same-space duplicate).
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.operations import match_surfaces

# Kept local (not imported from gbxml_import/operations.py's PLANE_TOLERANCE) to preserve
# the existing one-way import direction: gbxml_import depends on geometry, never the
# reverse.
LEVEL_TOLERANCE_M = 0.01
MIN_NEW_SURFACE_AREA_M2 = 0.01


def _z_values(vertices: openstudio.Point3dVector) -> list[float]:
    return [p.z() for p in vertices]


def _is_level(vertices: openstudio.Point3dVector, tolerance: float = LEVEL_TOLERANCE_M) -> bool:
    zs = _z_values(vertices)
    return (max(zs) - min(zs)) <= tolerance


def repair_missing_roof_ceiling() -> dict[str, Any]:
    """Synthesize a RoofCeiling surface for spaces that have a Floor but no ceiling.

    Run repair_and_validate_gbxml_geometry() first to see which spaces need
    this (has_floor=True, has_roofceiling=False in its non_enclosed_spaces
    list), and again afterward to confirm they're now enclosed.

    Per space, requires: exactly one Floor surface, at least one Wall
    surface, a level floor, and uniformly level wall tops — a flat ceiling
    is only synthesized when the geometry actually supports one. New
    surfaces start "Outdoors"; match_surfaces() then runs once to pair any
    that truly coincide with a floor above in an adjacent space, and
    whatever's still unmatched afterward is set to "Adiabatic" rather than
    left facing outdoor weather it almost certainly isn't exposed to —
    defensible here specifically because this tool only ever fires on the
    nested-under-another-room's-ceiling case its preconditions describe.
    """
    try:
        model = get_model()

        # gbXML imports typically carry per-surface constructions and no
        # default construction set, so a synthesized surface with nothing
        # assigned can hit an EnergyPlus severe/fatal ("surface has no
        # construction") the first time anyone simulates the repaired model.
        # Borrow one from an existing RoofCeiling surface elsewhere in the
        # model before falling back to whatever a default construction set
        # would resolve (there usually isn't one on these models).
        donor_construction = next(
            (c.get() for s in model.getSurfaces()
             if s.surfaceType() == "RoofCeiling" and (c := s.construction()).is_initialized()),
            None,
        )

        repaired: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        new_surfaces: list[openstudio.model.Surface] = []

        for space in model.getSpaces():
            name = space.nameString()
            surfaces = list(space.surfaces())

            if any(s.surfaceType() == "RoofCeiling" for s in surfaces):
                continue

            floors = [s for s in surfaces if s.surfaceType() == "Floor"]
            if len(floors) != 1:
                skipped.append({
                    "space": name,
                    "reason": f"expected exactly 1 Floor surface, found {len(floors)}",
                })
                continue

            walls = [s for s in surfaces if s.surfaceType() == "Wall"]
            if not walls:
                skipped.append({"space": name, "reason": "no Wall surfaces to derive ceiling height from"})
                continue

            floor_vertices = list(floors[0].vertices())
            if not _is_level(floor_vertices):
                skipped.append({"space": name, "reason": "non-planar floor, cannot derive a flat ceiling"})
                continue

            wall_max_zs = [max(_z_values(list(w.vertices()))) for w in walls]
            ceiling_z = max(wall_max_zs)
            if any((ceiling_z - z) > LEVEL_TOLERANCE_M for z in wall_max_zs):
                skipped.append({"space": name, "reason": "uneven wall heights, cannot auto-repair a flat ceiling"})
                continue

            # Floor's own vertex order, reversed (flips the outward normal),
            # with Z substituted for the derived ceiling height.
            candidate = openstudio.Point3dVector()
            for p in reversed(floor_vertices):
                candidate.append(openstudio.Point3d(p.x(), p.y(), ceiling_z))

            normal = openstudio.getOutwardNormal(candidate)
            if not normal.is_initialized():
                skipped.append({"space": name, "reason": "could not compute outward normal for candidate ceiling"})
                continue
            if normal.get().z() <= 0:
                candidate = openstudio.reverse(candidate)
                normal = openstudio.getOutwardNormal(candidate)
                if not normal.is_initialized() or normal.get().z() <= 0:
                    skipped.append({"space": name, "reason": "unexpected floor winding, cannot orient ceiling"})
                    continue

            try:
                surface = openstudio.model.Surface(candidate, model)
            except Exception as e:
                skipped.append({"space": name, "reason": f"failed to construct surface: {e}"})
                continue

            area = float(surface.grossArea())
            if area <= MIN_NEW_SURFACE_AREA_M2:
                surface.remove()
                skipped.append({"space": name, "reason": f"degenerate ceiling polygon (area={area:.4f} m2)"})
                continue

            surface.setName(f"{name} RoofCeiling (repaired)")
            surface.setSpace(space)
            surface.setSurfaceType("RoofCeiling")
            surface.setOutsideBoundaryCondition("Outdoors")

            # construction() already searches the space/space-type/building
            # default-construction-set hierarchy; only fall back to the
            # borrowed donor if that search comes up empty.
            if not surface.construction().is_initialized() and donor_construction is not None:
                surface.setConstruction(donor_construction)
            resolved_construction = surface.construction()

            new_surfaces.append(surface)
            repaired.append({
                "space": name,
                "new_surface_name": surface.nameString(),
                "area_m2": round(area, 4),
                "ceiling_z": round(ceiling_z, 4),
                "construction": resolved_construction.get().nameString() if resolved_construction.is_initialized() else None,
                "construction_warning": (
                    None if resolved_construction.is_initialized()
                    else "No construction assigned — no default construction set and no existing "
                         "RoofCeiling surface to borrow one from. Assign one before simulating or "
                         "EnergyPlus will likely fail with a missing-construction error."
                ),
            })

        if new_surfaces:
            # Must not be discarded: the boundary-condition decision below reads the
            # results of this matching, so a silent failure would make every synthesized
            # ceiling look unmatched and be forced Adiabatic on false evidence.
            match_result = match_surfaces()
            if not match_result.get("ok"):
                return {
                    "ok": False,
                    "error": f"Synthesized {len(new_surfaces)} ceiling(s) but "
                             "match_surfaces() failed afterward, so boundary conditions "
                             f"could not be resolved: {match_result.get('error')}",
                    "repaired_count": len(repaired),
                    "repaired": repaired,
                }

            for entry, surface in zip(repaired, new_surfaces, strict=True):
                matched_space_above = surface.outsideBoundaryCondition() == "Surface"
                if not matched_space_above:
                    surface.setOutsideBoundaryCondition("Adiabatic")
                entry["final_boundary_condition"] = surface.outsideBoundaryCondition()
                entry["boundary_condition_warning"] = (
                    None if matched_space_above
                    else "Set Adiabatic (no matching space above) — correct for a nested space "
                         "under another room's ceiling, but wrong if this space is genuinely "
                         "top-floor with a missing roof; verify before trusting simulation results."
                )

        return {
            "ok": True,
            "repaired_count": len(repaired),
            "repaired": repaired,
            "skipped": skipped,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to repair missing roof/ceiling surfaces: {e}"}
