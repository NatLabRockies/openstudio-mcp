"""Constructions operations — materials, constructions, construction sets.

Extraction patterns adapted from openstudio-toolkit osm_objects/materials.py,
osm_objects/constructions.py, and osm_objects/construction_sets.py
— using direct openstudio bindings.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import (
    build_list_response,
    fetch_object,
    list_paginated,
)


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
        result["exterior_wall_construction"] = ext_constructions.wallConstruction().get().nameString() if ext_constructions.wallConstruction().is_initialized() else None
        result["exterior_floor_construction"] = ext_constructions.floorConstruction().get().nameString() if ext_constructions.floorConstruction().is_initialized() else None
        result["exterior_roof_construction"] = ext_constructions.roofCeilingConstruction().get().nameString() if ext_constructions.roofCeilingConstruction().is_initialized() else None

    if construction_set.defaultInteriorSurfaceConstructions().is_initialized():
        int_constructions = construction_set.defaultInteriorSurfaceConstructions().get()
        result["interior_wall_construction"] = int_constructions.wallConstruction().get().nameString() if int_constructions.wallConstruction().is_initialized() else None
        result["interior_floor_construction"] = int_constructions.floorConstruction().get().nameString() if int_constructions.floorConstruction().is_initialized() else None
        result["interior_ceiling_construction"] = int_constructions.roofCeilingConstruction().get().nameString() if int_constructions.roofCeilingConstruction().is_initialized() else None

    if construction_set.defaultGroundContactSurfaceConstructions().is_initialized():
        gnd_constructions = construction_set.defaultGroundContactSurfaceConstructions().get()
        result["ground_wall_construction"] = gnd_constructions.wallConstruction().get().nameString() if gnd_constructions.wallConstruction().is_initialized() else None
        result["ground_floor_construction"] = gnd_constructions.floorConstruction().get().nameString() if gnd_constructions.floorConstruction().is_initialized() else None

    if construction_set.defaultExteriorSubSurfaceConstructions().is_initialized():
        ext_sub = construction_set.defaultExteriorSubSurfaceConstructions().get()
        result["exterior_fixed_window_construction"] = ext_sub.fixedWindowConstruction().get().nameString() if ext_sub.fixedWindowConstruction().is_initialized() else None
        result["exterior_operable_window_construction"] = ext_sub.operableWindowConstruction().get().nameString() if ext_sub.operableWindowConstruction().is_initialized() else None
        result["exterior_door_construction"] = ext_sub.doorConstruction().get().nameString() if ext_sub.doorConstruction().is_initialized() else None

    return result


def list_materials(
    material_type: str | None = None,
    max_results: int = 10,
) -> dict[str, Any]:
    """List materials with optional type filter and pagination."""
    try:
        model = get_model()

        filt = None
        if material_type:
            def filt(m, mat):
                return material_type in mat.iddObjectType().valueName()

        items, total = list_paginated(
            model, "getMaterials", _extract_material,
            max_results=max_results, obj_filter_fn=filt,
        )
        return build_list_response("materials", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list materials: {e}"}


def list_constructions(max_results: int = 10) -> dict[str, Any]:
    """List constructions with pagination."""
    try:
        model = get_model()
        items, total = list_paginated(
            model, "getConstructions", _extract_construction,
            max_results=max_results,
        )
        return build_list_response("constructions", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list constructions: {e}"}


def list_construction_sets(max_results: int = 10) -> dict[str, Any]:
    """List construction sets with pagination."""
    try:
        model = get_model()
        items, total = list_paginated(
            model, "getDefaultConstructionSets", _extract_construction_set,
            max_results=max_results,
        )
        return build_list_response("construction_sets", items, total, max_results)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list construction sets: {e}"}


def get_construction_details(construction_name: str) -> dict[str, Any]:
    """Get detailed info for a construction including material layers."""
    try:
        model = get_model()
        construction = fetch_object(model, "Construction", name=construction_name)
        if construction is None:
            return {"ok": False, "error": f"Construction '{construction_name}' not found"}

        layers = [_extract_material(model, layer) for layer in construction.layers()]
        return {
            "ok": True,
            "construction": {
                "name": construction.nameString(),
                "handle": str(construction.handle()),
                "num_layers": len(layers),
                "layers": layers,
            },
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get construction details: {e}"}


def create_standard_opaque_material(name: str, roughness: str = "Smooth",
                                   thickness_m: float = 0.1,
                                   conductivity_w_m_k: float = 0.5,
                                   density_kg_m3: float = 800.0,
                                   specific_heat_j_kg_k: float = 1000.0) -> dict[str, Any]:
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


def _layer_resistance_si(material) -> float | None:
    """Layer R in m2K/W, or None when the material type has no simple R."""
    # StandardOpaqueMaterial.thermalResistance() = thickness / conductivity
    std = material.to_StandardOpaqueMaterial()
    if std.is_initialized():
        return std.get().thermalResistance()
    massless = material.to_MasslessOpaqueMaterial()
    if massless.is_initialized():
        return massless.get().thermalResistance()
    air = material.to_AirGap()
    if air.is_initialized():
        return air.get().thermalResistance()
    return None


def _assembly_r_si(construction) -> float | None:
    """Sum of layer resistances (no air films), or None if any layer unknown."""
    layered = construction.to_LayeredConstruction()
    if not layered.is_initialized():
        return None
    total = 0.0
    for material in layered.get().layers():
        r = _layer_resistance_si(material)
        if r is None:
            return None
        total += r
    return round(total, 4)


def _fetch_material(model, material_name: str):
    material = fetch_object(model, "Material", name=material_name)
    if material is None:
        material = fetch_object(model, "StandardOpaqueMaterial", name=material_name)
    return material


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
            material = _fetch_material(model, material_name)
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


def add_layer_to_construction(construction_name: str, material_name: str,
                              position: str = "inside",
                              new_construction_name: str | None = None) -> dict[str, Any]:
    """Create a copy of an existing construction with one material layer added.

    All original layers are preserved (reused, not duplicated); the source
    construction is untouched. Returns before/after assembly R so callers can
    verify the envelope actually improved.

    Args:
        construction_name: Existing construction to upgrade
        material_name: Material to insert (must already exist in the model)
        position: "inside" (innermost face, default) or "outside"
            (directly beneath the outermost weather/finish layer)
        new_construction_name: Name for the upgraded construction
            (default: "<construction> + <material>")

    Returns:
        dict with ok=True, the new construction, and assembly_r_si before/after,
        or ok=False and error message
    """
    try:
        model = get_model()

        construction = fetch_object(model, "Construction", name=construction_name)
        if construction is None:
            return {"ok": False, "error": f"Construction '{construction_name}' not found"}

        material = _fetch_material(model, material_name)
        if material is None:
            return {"ok": False,
                    "error": f"Material '{material_name}' not found — create it "
                             "first with create_standard_opaque_material"}

        if position not in ("inside", "outside"):
            return {"ok": False,
                    "error": f"position must be 'inside' or 'outside', got '{position}'"}

        before_r = _assembly_r_si(construction)

        layers = list(construction.layers())
        index = len(layers) if position == "inside" else min(1, len(layers))
        layers.insert(index, material)

        new_construction = openstudio.model.Construction(model)
        new_construction.setName(new_construction_name
                                 or f"{construction_name} + {material_name}")
        if not new_construction.setLayers(layers):
            new_construction.remove()
            return {"ok": False,
                    "error": f"Could not insert '{material_name}' into "
                             f"'{construction_name}' — material type incompatible "
                             "with this construction's layers"}

        return {
            "ok": True,
            "construction": _extract_construction(model, new_construction),
            "source_construction": construction.nameString(),
            "assembly_r_si_before": before_r,
            "assembly_r_si_after": _assembly_r_si(new_construction),
            "hint": "Assign the new construction to the target surfaces with "
                    "assign_construction_to_surface.",
        }

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add layer to construction: {e}"}


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

        # Effective construction before the swap (may come from a default
        # construction set) — basis for the R-decrease hint
        previous = surface.construction()
        prev_name = previous.get().nameString() if previous.is_initialized() else None
        prev_r = _assembly_r_si(previous.get()) if previous.is_initialized() else None
        new_r = _assembly_r_si(construction)

        # Assign construction to surface
        surface.setConstruction(construction)

        result = {
            "ok": True,
            "surface": {
                "name": surface.nameString(),
                "construction": construction.nameString(),
            },
        }
        if new_r is not None:
            result["assembly_r_si"] = new_r
        if prev_name is not None and prev_name != construction.nameString():
            result["previous_construction"] = prev_name
            if prev_r is not None:
                result["previous_assembly_r_si"] = prev_r
            # Benchmark F7: every model "insulated" roofs by replacing the whole
            # assembly with a bare insulation slab, LOWERING assembly R. Warn
            # (not fail — lowering R is legitimate in some studies) and point at
            # the additive path.
            if prev_r is not None and new_r is not None and new_r < prev_r - 1e-6:
                result["warning"] = (
                    f"assembly R decreased {prev_r:.2f} -> {new_r:.2f} m2K/W; "
                    "if the goal was to ADD insulation, use "
                    "add_layer_to_construction to keep the existing layers "
                    "instead of replacing the whole assembly")
        return result

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to assign construction: {e}"}
