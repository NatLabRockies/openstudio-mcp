"""MCP tool definitions for geometry (surfaces and subsurfaces)."""
from __future__ import annotations

from mcp_server.skills.geometry.operations import (
    create_space_from_floor_print,
    create_subsurface,
    create_surface,
    get_surface_details,
    import_floorspacejs,
    list_subsurfaces,
    list_surfaces,
    match_surfaces,
    set_window_to_wall_ratio,
)
from mcp_server.skills.geometry.patch_missing_surfaces import patch_missing_surfaces
from mcp_server.skills.geometry.repair import (
    merge_coplanar_sliver_surfaces,
    repair_missing_roof_ceiling,
    weld_coincident_vertices,
)
from mcp_server.skills.geometry.trim_overlapping_surfaces import trim_overlapping_surfaces


def register(mcp):
    @mcp.tool(tags={"geometry"}, name="list_surfaces")
    def list_surfaces_tool(
        detailed: bool = False,
        space_name: str | None = None,
        surface_type: str | None = None,
        boundary: str | None = None,
        max_results: int = 10,
    ):
        """List surfaces — walls, floors, roofs, ceilings by type and boundary condition.
        Default 10 results; use filters to narrow.

        Common filters:
        - Exterior walls: surface_type="Wall", boundary="Outdoors"
        - All exterior: boundary="Outdoors"
        - Surfaces in a space: space_name="Office 1"

        Args:
            detailed: Return all fields (construction, orientation, vertices, subsurfaces)
            space_name: Filter by parent space name
            surface_type: Filter by type — "Wall", "Floor", "RoofCeiling"
            boundary: Filter by outside boundary — "Outdoors", "Ground", "Surface"
            max_results: Max items to return (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_surfaces(detailed=detailed, space_name=space_name,
                            surface_type=surface_type, boundary=boundary,
                            max_results=mr)

    @mcp.tool(tags={"geometry"}, name="get_surface_details")
    def get_surface_details_tool(surface_name: str):
        """Get surface details — vertices, area, tilt, azimuth, construction, adjacent surface.

        Args:
            surface_name: Name of the surface to retrieve
        """
        return get_surface_details(surface_name=surface_name)

    @mcp.tool(tags={"geometry"}, name="list_subsurfaces")
    def list_subsurfaces_tool(
        surface_name: str | None = None,
        space_name: str | None = None,
        subsurface_type: str | None = None,
        max_results: int = 10,
    ):
        """List subsurfaces — windows, doors, skylights, glass doors.
        Default 10 results; use filters to narrow.

        Common filters:
        - Windows on a wall: surface_name="Wall 1"
        - All doors: subsurface_type="Door"
        - Windows in a space: space_name="Office 1"

        Args:
            surface_name: Filter by parent surface name
            space_name: Filter by parent space (transitive: subsurface→surface→space)
            subsurface_type: Filter — "FixedWindow", "OperableWindow", "Door", "GlassDoor"
            max_results: Max items to return (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_subsurfaces(surface_name=surface_name, space_name=space_name,
                               subsurface_type=subsurface_type, max_results=mr)

    @mcp.tool(tags={"geometry"}, name="create_surface")
    def create_surface_tool(
        name: str,
        vertices: list[list[float]],
        space_name: str,
        surface_type: str | None = None,
        outside_boundary_condition: str | None = None,
    ):
        """Create a wall, floor, or roof surface with 3D vertex coordinates in a space.

        Args:
            name: Surface name
            vertices: List of [x,y,z] vertex coordinates (at least 3)
            space_name: Name of existing space to contain the surface
            surface_type: "Wall", "Floor", or "RoofCeiling" (auto-detected from tilt if omitted)
            outside_boundary_condition: "Outdoors", "Ground", or "Surface" (default "Outdoors")

        """
        return create_surface(
            name=name, vertices=vertices, space_name=space_name,
            surface_type=surface_type,
            outside_boundary_condition=outside_boundary_condition,
        )

    @mcp.tool(tags={"geometry"}, name="create_subsurface")
    def create_subsurface_tool(
        name: str,
        vertices: list[list[float]],
        parent_surface_name: str,
        subsurface_type: str = "FixedWindow",
    ):
        """Create a window, door, skylight, or glass door subsurface on a parent surface.

        Args:
            name: Subsurface name
            vertices: List of [x,y,z] vertex coordinates (coplanar with parent)
            parent_surface_name: Name of existing parent surface
            subsurface_type: "FixedWindow", "OperableWindow", "Door", or "GlassDoor"

        """
        return create_subsurface(
            name=name, vertices=vertices,
            parent_surface_name=parent_surface_name,
            subsurface_type=subsurface_type,
        )

    @mcp.tool(tags={"geometry"}, name="create_space_from_floor_print")
    def create_space_from_floor_print_tool(
        name: str,
        floor_vertices: list[list[float]],
        floor_to_ceiling_height: float,
        building_story_name: str | None = None,
        thermal_zone_name: str | None = None,
    ):
        """Extrude a 2D floor polygon into a 3D space with walls, floor, and ceiling.

        Automatically creates all surfaces from the polygon outline and height.
        Easiest way to create geometry for a rectangular or polygonal zone.

        Args:
            name: Space name
            floor_vertices: List of [x,y] or [x,y,z] floor polygon vertices
            floor_to_ceiling_height: Extrusion height in meters
            building_story_name: Optional existing building story to assign
            thermal_zone_name: Optional existing thermal zone to assign

        """
        return create_space_from_floor_print(
            name=name, floor_vertices=floor_vertices,
            floor_to_ceiling_height=floor_to_ceiling_height,
            building_story_name=building_story_name,
            thermal_zone_name=thermal_zone_name,
        )

    @mcp.tool(tags={"geometry"}, name="match_surfaces")
    def match_surfaces_tool():
        """Intersect and match surfaces across all spaces, setting shared walls as interior boundaries."""
        return match_surfaces()

    @mcp.tool(tags={"geometry"}, name="repair_missing_roof_ceiling")
    def repair_missing_roof_ceiling_tool():
        """Synthesize a RoofCeiling surface for spaces that have a Floor but no ceiling.

        Run repair_and_validate_gbxml_geometry() first to find spaces with
        has_floor=True/has_roofceiling=False in non_enclosed_spaces, then this
        to fix them, then repair_and_validate_gbxml_geometry() again to
        confirm. Only synthesizes a flat ceiling when the space's floor is
        level and its wall tops are uniformly level — anything sloped or
        ambiguous is reported as skipped, not guessed at.
        """
        return repair_missing_roof_ceiling()

    @mcp.tool(tags={"geometry"}, name="merge_coplanar_sliver_surfaces")
    def merge_coplanar_sliver_surfaces_tool():
        """Merge same-space coplanar wall/floor/ceiling fragments into fewer, larger surfaces.

        Fixes gbXML/Revit exports that split one physical wall, floor, or ceiling into
        many tiny same-space fragments (one per adjacent-room boundary segment) instead
        of one clean surface per side — the cause of Space.isEnclosedVolume() failures
        that match_surfaces() can't fix (it only reconciles surfaces between spaces,
        never within one). Mixed boundary conditions/constructions, and fragments
        carrying windows or doors, are reported as skipped rather than guessed at. Run
        repair_and_validate_gbxml_geometry() before and after to see the effect on
        non_enclosed_spaces_count.
        """
        return merge_coplanar_sliver_surfaces()

    @mcp.tool(tags={"geometry"}, name="weld_coincident_vertices")
    def weld_coincident_vertices_tool():
        """Snap each space's near-coincident vertices to a shared point, closing corner gaps.

        Fixes gbXML/Revit exports that leave sub-centimeter float noise between vertices
        that are supposed to coincide — e.g. two perpendicular walls, or a wall and the
        floor, whose shared corner is a few millimeters off between the two surfaces.
        This is a different defect from merge_coplanar_sliver_surfaces (that one only
        handles same-plane fragments); these surfaces aren't coplanar, so grouping/joining
        doesn't apply. A surface is only rewritten if welding actually moved one of its
        points; degenerate results (a surface's own vertices collapsing onto each other,
        or near-zero resulting area) are reported as skipped rather than corrupted. Run
        repair_and_validate_gbxml_geometry() before and after to see the effect on
        non_enclosed_spaces_count.
        """
        return weld_coincident_vertices()

    @mcp.tool(tags={"geometry"}, name="patch_missing_surfaces")
    def patch_missing_surfaces_tool():
        """Reconstruct a space's missing surfaces from its own unpaired polyhedron edges.

        Fixes gbXML/Revit exports that dropped a surface outright — usually an interior
        partition wall, but not always: surface type is inferred from each reconstructed
        facet's own geometry, not assumed, so a missing Floor or RoofCeiling is handled
        exactly the same way. A different defect from either merge_coplanar_sliver_surfaces
        (same-plane fragments) or weld_coincident_vertices (corner gaps): here there's
        nothing to snap or join because the surface simply doesn't exist. Uses
        Space.polyhedron().edgesNotTwo(True) to find edges used by only one surface, then
        reconstructs the missing surface(s) — independently per separate hole in the same
        space, splitting a non-planar hole into planar facets via chords, and resolving a
        branch point (more than one missing surface meeting at a vertex) via a bounded
        search over ways to pair up its edges. Edges used 3+ times (a same-space overlap —
        a different defect, see trim_overlapping_surfaces) are excluded and reported
        separately rather than blocking the rest of the space. Run
        repair_and_validate_gbxml_geometry() before and after to see the effect on
        non_enclosed_spaces_count.
        """
        return patch_missing_surfaces()

    @mcp.tool(tags={"geometry"}, name="trim_overlapping_surfaces")
    def trim_overlapping_surfaces_tool():
        """Trim same-space surfaces with a genuine 2D overlap to their non-overlap remainder.

        Fixes the historical "wall exported once per neighboring room instead of split at
        the boundary between them" defect (and any similar same-space duplicate/overlap)
        — a different problem from a missing or fragmented surface: here there's too much
        material, not too little. Scoped to spaces currently failing
        Space.isEnclosedVolume() — a coplanar sliver artifact elsewhere doesn't need
        touching just because it exists. Detects coincident-plane pairs with true 2D
        overlap area (not just a shared edge), then replaces each surface's vertices with
        its own non-overlapping remainder, or removes it outright if fully contained
        within the other. A remainder that splits into multiple disjoint pieces is
        reported as skipped rather than guessed at. Run
        repair_and_validate_gbxml_geometry() before and after to see the effect on
        overlapping_surfaces_count and non_enclosed_spaces_count.
        """
        return trim_overlapping_surfaces()

    @mcp.tool(tags={"geometry"}, name="set_window_to_wall_ratio")
    def set_window_to_wall_ratio_tool(
        surface_name: str,
        ratio: float,
        sill_height_m: float = 0.9,
    ):
        """Set glazing ratio on an exterior wall — adds a centered window by window-to-wall ratio.

        Args:
            surface_name: Name of the wall surface
            ratio: Window-to-wall ratio (0.0 to 1.0)
            sill_height_m: Sill height above floor in meters (default 0.9m)

        """
        return set_window_to_wall_ratio(
            surface_name=surface_name, ratio=ratio,
            sill_height_m=sill_height_m,
        )

    @mcp.tool(tags={"geometry"}, name="import_floorspacejs")
    def import_floorspacejs_tool(
        floorplan_path: str,
        building_type: str = "SmallOffice",
        create_zones: bool = True,
        match: bool = True,
    ):
        """Import a floor plan / custom geometry from FloorspaceJS JSON.

        Use this tool when a user wants to import a floor plan, import geometry,
        load a FloorspaceJS file, or use custom geometry from the FloorspaceJS
        editor. Creates spaces, surfaces, windows, building stories, and space
        types from a FloorspaceJS JSON file. Optionally creates thermal zones
        and runs surface matching. Sets standardsBuildingType/standardsSpaceType
        so create_typical_building can populate the model.

        Create FloorspaceJS JSON at https://nrel.github.io/floorspace.js/

        Args:
            floorplan_path: Absolute path to FloorspaceJS JSON file (*.json)
            building_type: DOE prototype — "SmallOffice", "LargeOffice",
                "RetailStandalone", "Hospital", etc. Sets standardsBuildingType.
            create_zones: Create one thermal zone per space (default True)
            match: Run surface intersection and matching (default True)

        """
        return import_floorspacejs(
            floorplan_path=floorplan_path,
            building_type=building_type,
            create_zones=create_zones,
            match=match,
        )
