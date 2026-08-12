"""Set boundary conditions on a named batch of surfaces.

`patch_missing_surfaces` can flag a hundred-plus surfaces as
`boundary_condition_ambiguous` on a badly broken gbXML import — an honest
disclosure that was, until this tool existed, not actionable: the only
alternatives were `set_adiabatic_boundaries` (wholesale, by surface class and
cardinal orientation, with no way to name a surface) or `set_object_property`
one surface at a time.

Two things this deliberately does that a thin wrapper would not:

- Resolves every name before mutating anything, so a typo in one name cannot
  leave a batch half-applied.
- Keeps sun/wind exposure coherent with the boundary condition unless the caller
  says otherwise. A `Surface` defaults to SunExposed/WindExposed, and leaving
  that in place while setting a non-`Outdoors` condition is precisely the
  incoherence that made an earlier revision of `patch_missing_surfaces` apply
  fictitious solar gain to interior partitions.
"""
from __future__ import annotations

import difflib
from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object, parse_str_list

# "Surface" means "adjacent to another surface" and is meaningless without that
# partner — OpenStudio sets it as a side effect of matching, and setting it here
# would leave a dangling reference.
_REQUIRES_PAIRING = "Surface"


def _valid(values_fn) -> list[str]:
    """Allowed values straight from the SDK, so this can't drift from the bindings."""
    return list(values_fn())


def _suggest(value: str, allowed: list[str]) -> list[str]:
    return difflib.get_close_matches(value, allowed, n=3)


def _derive_exposure(outside_boundary_condition: str) -> tuple[str, str]:
    """Exposure implied by a boundary condition when the caller doesn't specify.

    Only an outdoor-facing surface sees sun and wind; everything else (adiabatic,
    ground-coupled, other-side-coefficient) has no outdoor face to expose.
    """
    if outside_boundary_condition == "Outdoors":
        return "SunExposed", "WindExposed"
    return "NoSun", "NoWind"


def set_surface_boundary_conditions(
    surface_names: list[str] | str,
    outside_boundary_condition: str,
    sun_exposure: str | None = None,
    wind_exposure: str | None = None,
) -> dict[str, Any]:
    """Set the outside boundary condition on a batch of named surfaces."""
    try:
        model = get_model()

        names = parse_str_list(surface_names) if isinstance(surface_names, str) else list(surface_names)
        names = list(dict.fromkeys(names))  # dedupe, preserve caller's order
        if not names:
            return {"ok": False, "error": "No surface names given."}

        valid_bcs = _valid(openstudio.model.Surface.validOutsideBoundaryConditionValues)
        valid_sun = _valid(openstudio.model.Surface.validSunExposureValues)
        valid_wind = _valid(openstudio.model.Surface.validWindExposureValues)

        if outside_boundary_condition == _REQUIRES_PAIRING:
            return {
                "ok": False,
                "error": "'Surface' cannot be set directly — it means 'adjacent to a "
                         "specific other surface' and needs that partner. Use "
                         "match_surfaces() to pair surfaces between adjacent spaces.",
            }
        if outside_boundary_condition not in valid_bcs:
            return {
                "ok": False,
                "error": f"Invalid outside_boundary_condition '{outside_boundary_condition}'.",
                "did_you_mean": _suggest(outside_boundary_condition, valid_bcs),
                "valid_values": valid_bcs,
            }
        if sun_exposure is not None and sun_exposure not in valid_sun:
            return {
                "ok": False,
                "error": f"Invalid sun_exposure '{sun_exposure}'.",
                "did_you_mean": _suggest(sun_exposure, valid_sun),
                "valid_values": valid_sun,
            }
        if wind_exposure is not None and wind_exposure not in valid_wind:
            return {
                "ok": False,
                "error": f"Invalid wind_exposure '{wind_exposure}'.",
                "did_you_mean": _suggest(wind_exposure, valid_wind),
                "valid_values": valid_wind,
            }

        # Resolve everything up front — a bad name must not leave a partial batch.
        resolved: list[Any] = []
        missing: list[str] = []
        for name in names:
            surface = fetch_object(model, "Surface", name=name)
            if surface is None:
                missing.append(name)
            else:
                resolved.append((name, surface))
        if missing:
            return {
                "ok": False,
                "error": f"{len(missing)} surface(s) not found; no changes were made: "
                         f"{', '.join(missing)}",
                "missing_surfaces": missing,
            }

        derived_sun, derived_wind = _derive_exposure(outside_boundary_condition)
        final_sun = sun_exposure or derived_sun
        final_wind = wind_exposure or derived_wind

        updated: list[dict[str, Any]] = []
        for name, surface in resolved:
            before = {
                "outside_boundary_condition": surface.outsideBoundaryCondition(),
                "sun_exposure": surface.sunExposure(),
                "wind_exposure": surface.windExposure(),
            }
            # Drop any existing adjacency first: a surface still pointing at a
            # partner would otherwise keep being reported as "Surface" and the
            # partner would be left referencing a surface that no longer matches it.
            if before["outside_boundary_condition"] == _REQUIRES_PAIRING:
                surface.resetAdjacentSurface()
            surface.setOutsideBoundaryCondition(outside_boundary_condition)
            surface.setSunExposure(final_sun)
            surface.setWindExposure(final_wind)
            updated.append({
                "surface": name,
                "before": before,
                "after": {
                    "outside_boundary_condition": surface.outsideBoundaryCondition(),
                    "sun_exposure": surface.sunExposure(),
                    "wind_exposure": surface.windExposure(),
                },
            })

        return {
            "ok": True,
            "updated_count": len(updated),
            "updated": updated,
            "outside_boundary_condition": outside_boundary_condition,
            "sun_exposure": final_sun,
            "wind_exposure": final_wind,
            "exposure_derived": sun_exposure is None and wind_exposure is None,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to set surface boundary conditions: {e}"}
