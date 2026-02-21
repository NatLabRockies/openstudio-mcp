"""Constructions operations — materials, constructions, construction sets.

Extraction patterns adapted from openstudio-toolkit osm_objects/materials.py,
osm_objects/constructions.py, and osm_objects/construction_sets.py
— using direct openstudio bindings.
"""

from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object, list_all_as_dicts


def _extract_material(model, material) -> dict[str, Any]:
    """Extract material attributes to dict."""
    # Get common attributes
    result = {
        "handle": str(material.handle()),
        "name": material.nameString(),
        "type": material.iddObjectType().valueName(),
    }

    # Add type-specific attributes using try-except to handle API variations
    try:
        if hasattr(material, "thickness"):
            result["thickness_m"] = float(material.thickness())
        if hasattr(material, "conductivity"):
            result["conductivity_w_m_k"] = float(material.conductivity())
        if hasattr(material, "density"):
            result["density_kg_m3"] = float(material.density())
        if hasattr(material, "specificHeat"):
            result["specific_heat_j_kg_k"] = float(material.specificHeat())
        if hasattr(material, "roughness"):
            result["roughness"] = material.roughness()
        if hasattr(material, "thermalResistance"):
            result["thermal_resistance_m2_k_w"] = float(material.thermalResistance())
    except Exception:
        pass  # Skip attributes that don't apply to this material type

    return result


def _extract_construction(model, construction) -> dict[str, Any]:
    """Extract construction attributes to dict."""
    # Get layers
    layers = []
    for layer in construction.layers():
        layers.append(layer.nameString())

    return {
        "handle": str(construction.handle()),
        "name": construction.nameString(),
        "num_layers": len(layers),
        "layers": layers,
    }


def _extract_construction_set(model, construction_set) -> dict[str, Any]:
    """Extract construction set attributes to dict."""
    result = {
        "handle": str(construction_set.handle()),
        "name": construction_set.nameString(),
    }

    # Get construction assignments
    if construction_set.defaultExteriorSurfaceConstructions().is_initialized():
        ext_constructions = construction_set.defaultExteriorSurfaceConstructions().get()
        result["exterior_wall_construction"] = (
            ext_constructions.wallConstruction().get().nameString()
            if ext_constructions.wallConstruction().is_initialized()
            else None
        )
        result["exterior_floor_construction"] = (
            ext_constructions.floorConstruction().get().nameString()
            if ext_constructions.floorConstruction().is_initialized()
            else None
        )
        result["exterior_roof_construction"] = (
            ext_constructions.roofCeilingConstruction().get().nameString()
            if ext_constructions.roofCeilingConstruction().is_initialized()
            else None
        )

    if construction_set.defaultInteriorSurfaceConstructions().is_initialized():
        int_constructions = construction_set.defaultInteriorSurfaceConstructions().get()
        result["interior_wall_construction"] = (
            int_constructions.wallConstruction().get().nameString()
            if int_constructions.wallConstruction().is_initialized()
            else None
        )
        result["interior_floor_construction"] = (
            int_constructions.floorConstruction().get().nameString()
            if int_constructions.floorConstruction().is_initialized()
            else None
        )
        result["interior_ceiling_construction"] = (
            int_constructions.roofCeilingConstruction().get().nameString()
            if int_constructions.roofCeilingConstruction().is_initialized()
            else None
        )

    if construction_set.defaultGroundContactSurfaceConstructions().is_initialized():
        gnd_constructions = construction_set.defaultGroundContactSurfaceConstructions().get()
        result["ground_wall_construction"] = (
            gnd_constructions.wallConstruction().get().nameString()
            if gnd_constructions.wallConstruction().is_initialized()
            else None
        )
        result["ground_floor_construction"] = (
            gnd_constructions.floorConstruction().get().nameString()
            if gnd_constructions.floorConstruction().is_initialized()
            else None
        )

    if construction_set.defaultExteriorSubSurfaceConstructions().is_initialized():
        ext_sub = construction_set.defaultExteriorSubSurfaceConstructions().get()
        result["exterior_fixed_window_construction"] = (
            ext_sub.fixedWindowConstruction().get().nameString()
            if ext_sub.fixedWindowConstruction().is_initialized()
            else None
        )
        result["exterior_operable_window_construction"] = (
            ext_sub.operableWindowConstruction().get().nameString()
            if ext_sub.operableWindowConstruction().is_initialized()
            else None
        )
        result["exterior_door_construction"] = (
            ext_sub.doorConstruction().get().nameString() if ext_sub.doorConstruction().is_initialized() else None
        )

    return result


def list_materials() -> dict[str, Any]:
    """List all materials in the model."""
    try:
        model = get_model()
        materials = list_all_as_dicts(model, "getMaterials", _extract_material)
        return {
            "ok": True,
            "count": len(materials),
            "materials": materials,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list materials: {e}"}


def list_constructions() -> dict[str, Any]:
    """List all constructions in the model."""
    try:
        model = get_model()
        constructions = list_all_as_dicts(model, "getConstructions", _extract_construction)
        return {
            "ok": True,
            "count": len(constructions),
            "constructions": constructions,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list constructions: {e}"}


def list_construction_sets() -> dict[str, Any]:
    """List all construction sets in the model."""
    try:
        model = get_model()
        construction_sets = list_all_as_dicts(model, "getDefaultConstructionSets", _extract_construction_set)
        return {
            "ok": True,
            "count": len(construction_sets),
            "construction_sets": construction_sets,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list construction sets: {e}"}


def create_standard_opaque_material(
    name: str,
    roughness: str = "Smooth",
    thickness_m: float = 0.1,
    conductivity_w_m_k: float = 0.5,
    density_kg_m3: float = 800.0,
    specific_heat_j_kg_k: float = 1000.0,
) -> dict[str, Any]:
    """Create a standard opaque material.

    Args:
        name: Name for the material
        roughness: Surface roughness - "VeryRough", "Rough", "MediumRough", "MediumSmooth", "Smooth", "VerySmooth" (default: "Smooth")
        thickness_m: Thickness in meters (default: 0.1)
        conductivity_w_m_k: Thermal conductivity in W/m-K (default: 0.5)
        density_kg_m3: Density in kg/m³ (default: 800.0)
        specific_heat_j_kg_k: Specific heat in J/kg-K (default: 1000.0)

    Returns:
        dict with ok=True and material details, or ok=False and error message
    """
    try:
        model = get_model()

        # Create StandardOpaqueMaterial
        material = openstudio.model.StandardOpaqueMaterial(model)
        material.setName(name)
        material.setRoughness(roughness)
        material.setThickness(thickness_m)
        material.setConductivity(conductivity_w_m_k)
        material.setDensity(density_kg_m3)
        material.setSpecificHeat(specific_heat_j_kg_k)

        # Extract and return
        result = _extract_material(model, material)
        return {"ok": True, "material": result}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create material: {e}"}


def create_construction(name: str, material_names: list[str]) -> dict[str, Any]:
    """Create a construction from layers of materials.

    Args:
        name: Name for the construction
        material_names: List of material names, ordered from outside to inside

    Returns:
        dict with ok=True and construction details, or ok=False and error message
    """
    try:
        model = get_model()

        # Verify all materials exist
        materials = []
        for material_name in material_names:
            # Try to fetch as Material (base class)
            material = fetch_object(model, "Material", name=material_name)
            if material is None:
                # Try StandardOpaqueMaterial
                material = fetch_object(model, "StandardOpaqueMaterial", name=material_name)
            if material is None:
                return {"ok": False, "error": f"Material '{material_name}' not found"}
            materials.append(material)

        # Create Construction
        construction = openstudio.model.Construction(model)
        construction.setName(name)

        # Set layers (outside to inside)
        construction.setLayers(materials)

        # Extract and return
        result = _extract_construction(model, construction)
        return {"ok": True, "construction": result}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create construction: {e}"}


def assign_construction_to_surface(surface_name: str, construction_name: str) -> dict[str, Any]:
    """Assign a construction to a surface.

    Args:
        surface_name: Name of the surface to modify
        construction_name: Name of the construction to assign

    Returns:
        dict with ok=True and updated surface info, or ok=False and error message
    """
    try:
        model = get_model()

        # Get surface
        surface = fetch_object(model, "Surface", name=surface_name)
        if surface is None:
            return {"ok": False, "error": f"Surface '{surface_name}' not found"}

        # Get construction
        construction = fetch_object(model, "Construction", name=construction_name)
        if construction is None:
            return {"ok": False, "error": f"Construction '{construction_name}' not found"}

        # Assign construction to surface
        surface.setConstruction(construction)

        return {
            "ok": True,
            "surface": {
                "name": surface.nameString(),
                "construction": construction.nameString(),
            },
        }

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to assign construction: {e}"}
