"""Additive construction upgrade (the F7 insulation-affordance fix).

Split out of operations.py to keep that file under the ~400-line limit.
Imports _extract_construction / _fetch_material from operations at module
load; operations re-exports add_layer_to_construction from here at its own
module bottom, so the one-directional cycle resolves cleanly.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object
from mcp_server.skills.constructions.construction_r import _assembly_r_si
from mcp_server.skills.constructions.operations import (
    _extract_construction,
    _fetch_material,
)


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
