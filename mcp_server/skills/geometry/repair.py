"""Repair spaces missing a RoofCeiling surface.

gbXML/Revit exports commonly carve small spaces (closets, cabinets) that get
a Floor but no RoofCeiling — nested under a bigger room's ceiling in the
source model — which leaves Space.isEnclosedVolume() failing even after
match_surfaces() has already reconciled every shared wall it can. This is a
targeted fix for exactly that case: one level Floor, uniformly level Wall
tops, no existing RoofCeiling. Anything sloped, stepped, or ambiguous is
reported as skipped rather than guessed at.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.operations import match_surfaces

# Kept local (not imported from gbxml_import/operations.py's PLANE_TOLERANCE)
# to preserve the existing one-way import direction: gbxml_import depends on
# geometry, never the reverse.
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
    left facing outdoor weather it almost certainly isn't exposed to.
    """
    try:
        model = get_model()

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

            new_surfaces.append(surface)
            repaired.append({
                "space": name,
                "new_surface_name": surface.nameString(),
                "area_m2": round(area, 4),
                "ceiling_z": round(ceiling_z, 4),
            })

        if new_surfaces:
            match_surfaces()
            for entry, surface in zip(repaired, new_surfaces, strict=True):
                if surface.outsideBoundaryCondition() != "Surface":
                    surface.setOutsideBoundaryCondition("Adiabatic")
                entry["final_boundary_condition"] = surface.outsideBoundaryCondition()

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
