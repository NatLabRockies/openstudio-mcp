"""Common measures discovery — scan and categorize bundled measures.

Provides list_common_measures: scan COMMON_MEASURES_DIR for available
measures from the openstudio-common-measures-gem.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.stdout_suppression import suppress_openstudio_warnings

# Category classification for common measures.
# Only the 20 curated measures are categorized; everything else is "other".
_CATEGORY_MAP: dict[str, str] = {
    # Tier 1 — reporting
    "openstudio_results": "reporting",
    "generic_qaqc": "reporting",
    # Tier 1 — thermostat
    "AdjustThermostatSetpointsByDegrees": "thermostat",
    "SetThermostatSchedules": "thermostat",
    "ReplaceThermostatSchedules": "thermostat",
    # Tier 1 — envelope
    "ReplaceExteriorWindowConstruction": "envelope",
    "set_exterior_walls_and_floors_to_adiabatic": "envelope",
    # Tier 1 — location
    "ChangeBuildingLocation": "location",
    # Tier 1 — loads
    "EnableIdealAirLoadsForAllZones": "loads",
    "add_ev_load": "loads",
    "add_zone_ventilation_design_flow_rate_object": "loads",
    # Tier 1 — renewables
    "add_rooftop_pv": "renewables",
    "AddSimplePvToShadingSurfacesByType": "renewables",
    # Tier 1 — schedule
    "ShiftScheduleProfileTime": "schedule",
    # Tier 1 — cost
    "SetLifecycleCostParameters": "cost",
    "AddCostPerFloorAreaToBuilding": "cost",
    # Tier 1 — cleanup
    "remove_orphan_objects_and_unused_resources": "cleanup",
    # Tier 1 — visualization
    "view_model": "visualization",
    "view_data": "visualization",
}


def list_common_measures(category: str | None = None) -> dict[str, Any]:
    """List available common measures with names, descriptions, paths.

    Args:
        category: Optional filter — "reporting", "thermostat", "envelope",
                  "location", "loads", "renewables", "schedule", "cost",
                  "cleanup", "idf", "visualization", "other", or None for all
    """
    measures_dir = Path(os.environ.get("COMMON_MEASURES_DIR", "/opt/common-measures"))
    if not measures_dir.is_dir():
        return {
            "ok": False,
            "error": f"Common measures directory not found: {measures_dir}. "
                     "Ensure COMMON_MEASURES_DIR is set and measures are installed.",
        }

    results = []
    for d in sorted(measures_dir.iterdir()):
        if not d.is_dir() or not (d / "measure.rb").is_file():
            continue
        cat = _CATEGORY_MAP.get(d.name, "other")
        if category and cat != category:
            continue

        entry: dict[str, Any] = {
            "name": d.name,
            "category": cat,
        }
        try:
            with suppress_openstudio_warnings():
                bcl = openstudio.BCLMeasure(openstudio.toPath(str(d)))
            entry["display_name"] = bcl.name()
            entry["num_arguments"] = len(bcl.arguments())
        except Exception:
            entry["display_name"] = d.name
            entry["num_arguments"] = -1

        results.append(entry)

    return {"ok": True, "count": len(results), "measures": results}
