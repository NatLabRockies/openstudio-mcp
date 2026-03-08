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


def register(mcp):
    @mcp.tool(name="list_surfaces")
    def list_surfaces_tool(detailed: bool = False):
        """List all surfaces. Brief: name, type, area, space. Use get_surface_details for full info.

        Args:
            detailed: Return all fields (boundary conditions, construction, orientation, vertices, subsurfaces)
        """
        return list_surfaces(detailed=detailed)

    @mcp.tool(name="get_surface_details")
    def get_surface_details_tool(surface_name: str):
        """Get detailed information about a specific surface.

        Args:
            surface_name: Name of the surface to retrieve
        """
        return get_surface_details(surface_name=surface_name)

    @mcp.tool(name="list_subsurfaces")
    def list_subsurfaces_tool():
        """List all subsurfaces (windows/doors) in the model."""
        return list_subsurfaces()

    @mcp.tool(name="create_surface")
    def create_surface_tool(
        name: str,
        vertices: list[list[float]],
        space_name: str,
        surface_type: str | None = None,
        outside_boundary_condition: str | None = None,
    ):
        """Create a surface with explicit vertices in a space.

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

    @mcp.tool(name="create_subsurface")
    def create_subsurface_tool(
        name: str,
        vertices: list[list[float]],
        parent_surface_name: str,
        subsurface_type: str = "FixedWindow",
    ):
        """Create a subsurface (window/door) on a parent surface.

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

    @mcp.tool(name="create_space_from_floor_print")
    def create_space_from_floor_print_tool(
        name: str,
        floor_vertices: list[list[float]],
        floor_to_ceiling_height: float,
        building_story_name: str | None = None,
        thermal_zone_name: str | None = None,
    ):
        """Create a space by extruding a floor polygon to a given height.

        Automatically creates floor, ceiling, and wall surfaces from the
        polygon outline and height. This is the easiest way to create
        geometry for a rectangular or polygonal zone.

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

    @mcp.tool(name="match_surfaces")
    def match_surfaces_tool():
        """Intersect and match surfaces across all spaces, setting shared walls as interior boundaries."""
        return match_surfaces()

    @mcp.tool(name="set_window_to_wall_ratio")
    def set_window_to_wall_ratio_tool(
        surface_name: str,
        ratio: float,
        sill_height_m: float = 0.9,
    ):
        """Add a centered window to a wall surface by glazing ratio.

        Args:
            surface_name: Name of the wall surface
            ratio: Window-to-wall ratio (0.0 to 1.0)
            sill_height_m: Sill height above floor in meters (default 0.9m)

        """
        return set_window_to_wall_ratio(
            surface_name=surface_name, ratio=ratio,
            sill_height_m=sill_height_m,
        )

    @mcp.tool(name="import_floorspacejs")
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
