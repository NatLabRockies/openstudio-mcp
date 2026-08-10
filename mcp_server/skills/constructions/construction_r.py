"""Assembly R-value helpers (leaf module — openstudio only, no skill deps).

Mirrors the grader's _layer_resistance in tests/llm/grading/container_grader.py:
sum of layer thermalResistance() with no air films, None if any layer's type
has no simple resistance. Kept dependency-free so both operations.py and
construction_layers.py can import it without a cycle.
"""
from __future__ import annotations


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
