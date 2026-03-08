"""MCP tool definitions for constructions (materials, constructions, sets)."""
from __future__ import annotations

from mcp_server.osm_helpers import parse_str_list
from mcp_server.skills.constructions.operations import (
    assign_construction_to_surface,
    create_construction,
    create_standard_opaque_material,
    list_construction_sets,
    list_constructions,
    list_materials,
)


def register(mcp):
    @mcp.tool(name="list_materials")
    def list_materials_tool():
        """List all materials in the model."""
        return list_materials()

    @mcp.tool(name="list_constructions")
    def list_constructions_tool():
        """List all constructions (layered assemblies) in the model."""
        return list_constructions()

    @mcp.tool(name="list_construction_sets")
    def list_construction_sets_tool():
        """List all construction sets in the model."""
        return list_construction_sets()

    @mcp.tool(name="create_standard_opaque_material")
    def create_standard_opaque_material_tool(name: str, roughness: str = "Smooth",
                                            thickness_m: float = 0.1,
                                            conductivity_w_m_k: float = 0.5,
                                            density_kg_m3: float = 800.0,
                                            specific_heat_j_kg_k: float = 1000.0):
        """Create a standard opaque material with thermal properties.

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

    @mcp.tool(name="create_construction")
    def create_construction_tool(name: str, material_names: list[str] | str):
        """Create a layered construction from materials.

        Args:
            name: Name for the construction
            material_names: List of material names, ordered from outside to inside

        """
        return create_construction(name=name, material_names=parse_str_list(material_names))

    @mcp.tool(name="assign_construction_to_surface")
    def assign_construction_to_surface_tool(surface_name: str, construction_name: str):
        """Assign a construction to a surface.

        Args:
            surface_name: Name of the surface to modify
            construction_name: Name of the construction to assign

        """
        return assign_construction_to_surface(surface_name=surface_name,
                                             construction_name=construction_name)
