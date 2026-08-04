"""Flag conditioned thermal zones with zero or missing volume.

gbXML/Revit zone-enclosure defects (the same family repair_and_validate_gbxml_
geometry already checks for at the Space level) can leave a ThermalZone's
computed volume at zero or uncomputable, which silently corrupts autosized
equipment capacities. This is a read-only diagnostic — it flags, it doesn't
repair; the fix is the same geometry-repair tooling already documented in the
gbXML import SKILL.md.
"""
from __future__ import annotations

from typing import Any

# Below this, a "volume" is not a real enclosed zone volume — it's noise from
# a broken/non-manifold enclosure.
MIN_ZONE_VOLUME_M3 = 1.0


def get_conditioned_zones(model: Any) -> list[Any]:
    """Conditioned, non-plenum thermal zones: has a thermostat assigned, not a plenum.

    Simpler than the openstudio-standards gem's thermal_zone_plenum?/
    is_zone_conditioned? heuristics (not available in this Python codebase) —
    thermostat presence is the direct core-SDK signal for "this zone is meant
    to be conditioned."
    """
    return [tz for tz in model.getThermalZones() if not tz.isPlenum() and tz.thermostat().is_initialized()]


def check_conditioned_zone_volumes(model: Any) -> dict[str, Any]:
    """Warn when conditioned zones have zero or missing volume."""
    conditioned = get_conditioned_zones(model)
    suspects: list[dict[str, Any]] = []
    for tz in conditioned:
        volume = tz.volume()
        has_volume = volume.is_initialized()
        if not has_volume or volume.get() < MIN_ZONE_VOLUME_M3:
            suspects.append({
                "zone": tz.nameString(),
                "volume_m3": round(volume.get(), 4) if has_volume else None,
            })

    warning = None
    if suspects:
        warning = (
            f"{len(suspects)} of {len(conditioned)} conditioned zones have zero or missing volume. "
            "Zone enclosure issues from gbXML import likely — equipment autosizing may be "
            "unreliable. Verify gbXML geometry before trusting simulation results."
        )

    return {
        "conditioned_zone_count": len(conditioned),
        "zero_volume_zone_count": len(suspects),
        "zero_volume_zones": suspects,
        "zero_volume_warning": warning,
    }
