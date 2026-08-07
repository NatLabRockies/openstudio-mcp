"""MCP tool definitions for constructions (materials, constructions, sets)."""
from __future__ import annotations

from mcp_server.osm_helpers import parse_str_list
from mcp_server.skills.constructions.operations import (
    add_layer_to_construction,
    assign_construction_to_surface,
    create_construction,
    create_standard_opaque_material,
    get_construction_details,
    list_materials,
)


def register(mcp):
    @mcp.tool(tags={"geometry"}, name="list_materials")
    def list_materials_tool(
        material_type: str | None = None,
        max_results: int = 10,
    ):
        """List materials with conductivity, density, specific heat, thickness.
        Default 10 results.

        Common filters: material_type="StandardOpaqueMaterial"

        Args:
            material_type: Filter by iddObjectType (e.g. "StandardOpaqueMaterial")
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_materials(material_type=material_type, max_results=mr)

    @mcp.tool(tags={"geometry"}, name="get_construction_details")
    def get_construction_details_tool(construction_name: str):
        """Get construction details — layers, R-value, U-factor, thermal mass for each material.

        Args:
            construction_name: Name of the construction
        """
        return get_construction_details(construction_name=construction_name)

    # list_constructions removed — use list_model_objects("Construction")
    # list_construction_sets removed — use list_model_objects("DefaultConstructionSet")

    @mcp.tool(tags={"geometry"}, name="create_standard_opaque_material")
    def create_standard_opaque_material_tool(name: str, roughness: str = "Smooth",
                                            thickness_m: float = 0.1,
                                            conductivity_w_m_k: float = 0.5,
                                            density_kg_m3: float = 800.0,
                                            specific_heat_j_kg_k: float = 1000.0):
        """Create a standard opaque material — conductivity, density, specific heat, thickness, roughness.

        Args:
            name: Name for the material
            roughness: VeryRough|Rough|MediumRough|MediumSmooth|Smooth|VerySmooth
            thickness_m: Thickness in meters (default: 0.1 = 10cm)
            conductivity_w_m_k: Thermal conductivity in W/m-K (default: 0.5)
            density_kg_m3: Density in kg/m³ (default: 800.0)
            specific_heat_j_kg_k: Specific heat in J/kg-K (default: 1000.0)

        """
        return create_standard_opaque_material(name=name, roughness=roughness,
                                              thickness_m=thickness_m,
                                              conductivity_w_m_k=conductivity_w_m_k,
                                              density_kg_m3=density_kg_m3,
                                              specific_heat_j_kg_k=specific_heat_j_kg_k)

    @mcp.tool(tags={"geometry"}, name="create_construction")
    def create_construction_tool(name: str, material_names: list[str] | str):
        """Create a layered construction — ordered material layers from outside to inside.

        Args:
            name: Name for the construction
            material_names: List of material names, ordered from outside to inside

        """
        return create_construction(name=name, material_names=parse_str_list(material_names))

    @mcp.tool(tags={"geometry"}, name="add_layer_to_construction")
    def add_layer_to_construction_tool(construction_name: str, material_name: str,
                                       position: str = "inside",
                                       new_construction_name: str | None = None):
        """Add a material layer to an EXISTING construction — copies it with all
        original layers preserved plus the inserted layer. Use this for insulation
        upgrades instead of building a replacement construction from scratch.
        Returns assembly R before/after for self-checking.

        Args:
            construction_name: Existing construction to upgrade
            material_name: Material to insert (create first via create_standard_opaque_material)
            position: "inside" (innermost face, default) or "outside" (beneath the outermost layer)
            new_construction_name: Name for the upgraded construction (default: "<construction> + <material>")
        """
        return add_layer_to_construction(construction_name=construction_name,
                                         material_name=material_name,
                                         position=position,
                                         new_construction_name=new_construction_name)

    @mcp.tool(tags={"geometry"}, name="assign_construction_to_surface")
    def assign_construction_to_surface_tool(surface_name: str, construction_name: str):
        """Apply a wall, roof, or floor construction to a surface.

        Args:
            surface_name: Name of the surface to modify
            construction_name: Name of the construction to assign

        """
        return assign_construction_to_surface(surface_name=surface_name,
                                             construction_name=construction_name)
