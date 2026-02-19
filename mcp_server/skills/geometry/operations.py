"""Geometry operations — surfaces and subsurfaces.

Query and creation patterns adapted from openstudio-toolkit osm_objects/surfaces.py
and osm_objects/subsurfaces.py — using direct openstudio bindings.
Floor-print extrusion follows openstudio-resources baseline_model.py.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object, list_all_as_dicts, optional_name
from mcp_server.stdout_suppression import suppress_openstudio_warnings


def _extract_surface(model, surface) -> dict[str, Any]:
    """Extract surface attributes to dict.

    Fields mirror OpenStudio-Toolkit's get_surface_object_as_dict().
    """
    return {
        "handle": str(surface.handle()),
        "name": surface.nameString(),
        "surface_type": surface.surfaceType(),
        "outside_boundary_condition": surface.outsideBoundaryCondition(),
        "sun_exposure": surface.sunExposure(),
        "wind_exposure": surface.windExposure(),
        "construction": optional_name(surface.construction()),
        "space": optional_name(surface.space()),
        "adjacent_surface": optional_name(surface.adjacentSurface()),
        "gross_area_m2": float(surface.grossArea()),
        "net_area_m2": float(surface.netArea()),
        "azimuth_deg": float(surface.azimuth()) * 180.0 / 3.14159,  # Convert radians to degrees
        "tilt_deg": float(surface.tilt()) * 180.0 / 3.14159,
        "num_vertices": len(surface.vertices()),
        "num_subsurfaces": len(surface.subSurfaces()),
    }


def _extract_subsurface(model, subsurface) -> dict[str, Any]:
    """Extract subsurface (window/door) attributes to dict.

    Fields mirror OpenStudio-Toolkit's get_subsurface_object_as_dict().
    """
    return {
        "handle": str(subsurface.handle()),
        "name": subsurface.nameString(),
        "subsurface_type": subsurface.subSurfaceType(),
        "construction": optional_name(subsurface.construction()),
        "surface": optional_name(subsurface.surface()),
        "multiplier": float(subsurface.multiplier()),
        "gross_area_m2": float(subsurface.grossArea()),
        "num_vertices": len(subsurface.vertices()),
    }


def list_surfaces() -> dict[str, Any]:
    """List all surfaces in the model."""
    try:
        model = get_model()
        surfaces = list_all_as_dicts(model, "getSurfaces", _extract_surface)
        return {
            "ok": True,
            "count": len(surfaces),
            "surfaces": surfaces
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list surfaces: {e}"}


def get_surface_details(surface_name: str) -> dict[str, Any]:
    """Get detailed information about a specific surface."""
    try:
        model = get_model()
        surface = fetch_object(model, "Surface", name=surface_name)

        if surface is None:
            return {"ok": False, "error": f"Surface '{surface_name}' not found"}

        return {
            "ok": True,
            "surface": _extract_surface(model, surface)
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get surface details: {e}"}


def list_subsurfaces() -> dict[str, Any]:
    """List all subsurfaces (windows/doors) in the model."""
    try:
        model = get_model()
        subsurfaces = list_all_as_dicts(model, "getSubSurfaces", _extract_subsurface)
        return {
            "ok": True,
            "count": len(subsurfaces),
            "subsurfaces": subsurfaces
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list subsurfaces: {e}"}


# ---- Geometry creation ----


def _to_point3d_vector(vertices: list[list[float]]) -> openstudio.Point3dVector:
    """Convert [[x,y,z], ...] or [[x,y], ...] to Point3dVector."""
    poly = openstudio.Point3dVector()
    for v in vertices:
        x, y = float(v[0]), float(v[1])
        z = float(v[2]) if len(v) > 2 else 0.0
        poly.append(openstudio.Point3d(x, y, z))
    return poly


def create_surface(
    name: str,
    vertices: list[list[float]],
    space_name: str,
    surface_type: str | None = None,
    outside_boundary_condition: str | None = None,
) -> dict[str, Any]:
    """Create a Surface with explicit vertices in the given space.

    Args:
        name: Surface name
        vertices: [[x,y,z], ...] — at least 3 points
        space_name: Name of existing space to contain the surface
        surface_type: "Wall", "Floor", "RoofCeiling" — auto-detected from tilt if None
        outside_boundary_condition: "Outdoors", "Ground", "Surface" — default "Outdoors"
    """
    try:
        model = get_model()
        space = fetch_object(model, "Space", name=space_name)
        if space is None:
            return {"ok": False, "error": f"Space '{space_name}' not found"}

        poly = _to_point3d_vector(vertices)
        with suppress_openstudio_warnings():
            surface = openstudio.model.Surface(poly, model)
            surface.setName(name)
            surface.setSpace(space)
            if surface_type is not None:
                surface.setSurfaceType(surface_type)
            if outside_boundary_condition is not None:
                surface.setOutsideBoundaryCondition(outside_boundary_condition)

        return {"ok": True, "surface": _extract_surface(model, surface)}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create surface: {e}"}


def create_subsurface(
    name: str,
    vertices: list[list[float]],
    parent_surface_name: str,
    subsurface_type: str = "FixedWindow",
) -> dict[str, Any]:
    """Create a SubSurface (window/door) on a parent surface.

    Args:
        name: Subsurface name
        vertices: [[x,y,z], ...] — at least 3 points, coplanar with parent
        parent_surface_name: Name of existing parent surface
        subsurface_type: "FixedWindow", "OperableWindow", "Door", "GlassDoor"
    """
    try:
        model = get_model()
        parent = fetch_object(model, "Surface", name=parent_surface_name)
        if parent is None:
            return {"ok": False, "error": f"Surface '{parent_surface_name}' not found"}

        poly = _to_point3d_vector(vertices)
        with suppress_openstudio_warnings():
            sub = openstudio.model.SubSurface(poly, model)
            sub.setName(name)
            sub.setSurface(parent)
            sub.setSubSurfaceType(subsurface_type)

        return {"ok": True, "subsurface": _extract_subsurface(model, sub)}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create subsurface: {e}"}


def create_space_from_floor_print(
    name: str,
    floor_vertices: list[list[float]],
    floor_to_ceiling_height: float,
    building_story_name: str | None = None,
    thermal_zone_name: str | None = None,
) -> dict[str, Any]:
    """Extrude a floor polygon to create a space with all surfaces.

    Uses Space.fromFloorPrint() — creates floor, ceiling, and walls
    automatically from the polygon and height. Vertices are automatically
    reordered so the floor normal points down (required by OpenStudio).

    Args:
        name: Space name
        floor_vertices: [[x,y], ...] or [[x,y,z], ...] — floor polygon
        floor_to_ceiling_height: Height in meters
        building_story_name: Optional existing building story to assign
        thermal_zone_name: Optional existing thermal zone to assign
    """
    try:
        model = get_model()
        poly = _to_point3d_vector(floor_vertices)

        # fromFloorPrint requires outward normal pointing down (clockwise
        # when viewed from above). Compute normal via cross product of first
        # two edges — if Z > 0, reverse the vertex order.
        if len(floor_vertices) >= 3:
            normal = openstudio.getOutwardNormal(poly)
            if normal.is_initialized() and normal.get().z() > 0:
                poly = openstudio.reverse(poly)

        with suppress_openstudio_warnings():
            # fromFloorPrint returns an Optional<Space>
            opt_space = openstudio.model.Space.fromFloorPrint(
                poly, floor_to_ceiling_height, model
            )
            if not opt_space.is_initialized():
                return {"ok": False, "error": "Failed to create space from floor print"}
            space = opt_space.get()
            space.setName(name)

            # Assign building story if provided
            if building_story_name is not None:
                story = fetch_object(model, "BuildingStory", name=building_story_name)
                if story is None:
                    return {"ok": False, "error": f"BuildingStory '{building_story_name}' not found"}
                space.setBuildingStory(story)

            # Assign thermal zone if provided
            if thermal_zone_name is not None:
                zone = fetch_object(model, "ThermalZone", name=thermal_zone_name)
                if zone is None:
                    return {"ok": False, "error": f"ThermalZone '{thermal_zone_name}' not found"}
                space.setThermalZone(zone)

        # Count surfaces created
        surfaces = space.surfaces()
        surface_types = {}
        for s in surfaces:
            st = s.surfaceType()
            surface_types[st] = surface_types.get(st, 0) + 1

        return {
            "ok": True,
            "space_name": space.nameString(),
            "num_surfaces": len(surfaces),
            "surface_types": surface_types,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create space from floor print: {e}"}


# ---- Surface matching & fenestration helpers ----


def match_surfaces() -> dict[str, Any]:
    """Intersect and match surfaces across all spaces.

    Calls intersectSurfaces() then matchSurfaces() on all spaces.
    Shared walls between adjacent spaces are split at intersections and
    paired with "Surface" boundary condition pointing to each other.

    This is essential after creating multiple adjacent spaces — without it,
    shared walls remain "Outdoors" and heat transfer is wildly wrong.
    """
    try:
        model = get_model()

        # Build a mutable SpaceVector — SWIG needs a non-const reference
        space_vector = openstudio.model.SpaceVector()
        for sp in model.getSpaces():
            space_vector.append(sp)

        with suppress_openstudio_warnings():
            # Intersect: split surfaces where spaces overlap
            openstudio.model.intersectSurfaces(space_vector)
            # Match: pair coincident surfaces as interior boundaries
            openstudio.model.matchSurfaces(space_vector)

        # Count matched pairs (boundary == "Surface")
        matched = 0
        for surface in model.getSurfaces():
            if surface.outsideBoundaryCondition() == "Surface":
                matched += 1

        return {
            "ok": True,
            "matched_surfaces": matched,
            "total_surfaces": len(model.getSurfaces()),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to match surfaces: {e}"}


def set_window_to_wall_ratio(
    surface_name: str,
    ratio: float,
    sill_height_m: float = 0.9,
) -> dict[str, Any]:
    """Add a window to a wall surface by glazing ratio.

    Creates a single centered window sized to the given wall-to-window
    ratio. Much easier than specifying vertex coordinates manually.

    Args:
        surface_name: Name of the wall surface
        ratio: Window-to-wall ratio (0.0 to 1.0, e.g. 0.4 for 40%)
        sill_height_m: Sill height above floor in meters (default 0.9)
    """
    try:
        model = get_model()
        surface = fetch_object(model, "Surface", name=surface_name)
        if surface is None:
            return {"ok": False, "error": f"Surface '{surface_name}' not found"}

        if surface.surfaceType() != "Wall":
            return {"ok": False, "error": f"Surface '{surface_name}' is {surface.surfaceType()}, not Wall"}

        if ratio <= 0.0 or ratio >= 1.0:
            return {"ok": False, "error": f"Ratio must be between 0 and 1, got {ratio}"}

        with suppress_openstudio_warnings():
            # setWindowToWallRatio(ratio, sillHeight, startingFromBottom)
            ok = surface.setWindowToWallRatio(ratio, sill_height_m, True)

        if not ok:
            return {"ok": False, "error": "setWindowToWallRatio returned false — wall may be too small"}

        # Read back the created subsurfaces
        subs = surface.subSurfaces()
        sub_dicts = [_extract_subsurface(model, sub) for sub in subs]

        return {
            "ok": True,
            "surface_name": surface.nameString(),
            "ratio": ratio,
            "num_subsurfaces": len(sub_dicts),
            "subsurfaces": sub_dicts,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to set window-to-wall ratio: {e}"}
