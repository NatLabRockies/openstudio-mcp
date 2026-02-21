"""MCP tool definitions for constructions (materials, constructions, sets)."""

from __future__ import annotations

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
        """List all materials in the currently loaded model.

        Returns array of material objects with:
        - Name, handle, type (StandardOpaque, MasslessOpaque, AirGap, Glazing, etc.)
        - Type-specific properties:
          * Opaque: thickness, conductivity, density, specific heat
          * Massless/AirGap: thermal resistance
          * Glazing: U-factor, SHGC, transmittance

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_materials()

    @mcp.tool(name="list_constructions")
    def list_constructions_tool():
        """List all constructions in the currently loaded model.

        Returns array of construction objects with:
        - Name, handle
        - Number of layers
        - List of layer material names (outside to inside)

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_constructions()

    @mcp.tool(name="list_construction_sets")
    def list_construction_sets_tool():
        """List all construction sets in the currently loaded model.

        Returns array of construction set objects with:
        - Name, handle
        - Default constructions for:
          * Exterior surfaces (walls, floors, roofs)
          * Interior surfaces (walls, floors, ceilings)
          * Ground contact surfaces (walls, floors)
          * Subsurfaces (windows, doors)

        Construction sets define default construction assignments
        for buildings, stories, space types, or spaces.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_construction_sets()

    @mcp.tool(name="create_standard_opaque_material")
    def create_standard_opaque_material_tool(
        name: str,
        roughness: str = "Smooth",
        thickness_m: float = 0.1,
        conductivity_w_m_k: float = 0.5,
        density_kg_m3: float = 800.0,
        specific_heat_j_kg_k: float = 1000.0,
    ):
        """Create a standard opaque material with thermal properties.

        Args:
            name: Name for the material
            roughness: Surface roughness - "VeryRough", "Rough", "MediumRough", "MediumSmooth", "Smooth", "VerySmooth" (default: "Smooth")
            thickness_m: Thickness in meters (default: 0.1 = 10cm)
            conductivity_w_m_k: Thermal conductivity in W/m-K (default: 0.5)
            density_kg_m3: Density in kg/m³ (default: 800.0)
            specific_heat_j_kg_k: Specific heat in J/kg-K (default: 1000.0)

        Creates a material with specified thermal properties. Common examples:
        - Concrete: conductivity ~1.7, density ~2400, specific_heat ~900
        - Insulation: conductivity ~0.04, density ~50, specific_heat ~800
        - Wood: conductivity ~0.15, density ~600, specific_heat ~1600

        Use save_osm_model_tool to persist changes.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return create_standard_opaque_material(
            name=name,
            roughness=roughness,
            thickness_m=thickness_m,
            conductivity_w_m_k=conductivity_w_m_k,
            density_kg_m3=density_kg_m3,
            specific_heat_j_kg_k=specific_heat_j_kg_k,
        )

    @mcp.tool(name="create_construction")
    def create_construction_tool(name: str, material_names: list[str]):
        """Create a layered construction from materials.

        Args:
            name: Name for the construction
            material_names: List of material names, ordered from outside to inside

        Creates a construction by stacking materials in layers.
        Order matters: first material is outermost layer, last is innermost.

        Example for wall: ["Exterior Finish", "Insulation", "Concrete", "Interior Finish"]

        Use save_osm_model_tool to persist changes.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return create_construction(name=name, material_names=material_names)

    @mcp.tool(name="assign_construction_to_surface")
    def assign_construction_to_surface_tool(surface_name: str, construction_name: str):
        """Assign a construction to a surface.

        Args:
            surface_name: Name of the surface to modify
            construction_name: Name of the construction to assign

        Modifies a surface to use the specified construction.
        The construction determines the thermal and optical properties
        of the surface for simulation.

        Use save_osm_model_tool to persist changes.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return assign_construction_to_surface(surface_name=surface_name, construction_name=construction_name)
