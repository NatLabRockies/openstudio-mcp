"""Apply an EPW header's ground temperatures to the loaded model's Site:GroundTemperature:* objects.

A gbXML translation arrives with none of these objects set, so EnergyPlus falls back to its
own defaults on every Ground-boundary surface. The project EPW already carries measured
values and import_gbxml already requires that EPW — nothing read it until now.

**The EPW values are UNDISTURBED soil temperatures — an open field, no building on it.** The
repo's own weather assets say so (tests/assets/USA_MA_Boston-Logan...stat:498-500, and the
same text in the Austin .stat):

    **These ground temperatures should NOT BE USED in the GroundTemperatures object to
    compute building floor losses.
    The temperatures for 0.5 m depth can be used for GroundTemperatures:Surface.
    The temperatures for 4.0 m depth can be used for GroundTemperatures:Deep.

So raw EPW values go to Shallow, Deep and FCfactorMethod, and BuildingSurface — the only one
that drives a slab's heat balance — gets a derived value instead. Boston's January 0.5 m
figure is -0.29 C; feeding that to BuildingSurface would produce grossly overstated floor
losses. Kiva (the Foundation boundary condition) is the higher-fidelity answer for anyone who
needs real slab-edge heat transfer; this tool is the fast, approximate one.

Honest scope, because four written objects can read as four improvements:
  - Shallow/Deep feed ground heat exchangers and Site:GroundDomain. On a model with no GHX
    they are inert.
  - FCfactorMethod affects only F/C-factor constructions, which a gbXML import rarely has.
    EnergyPlus derives this object from the weather file when it is absent, so writing it is
    a deliberate override rather than a repair.
  - BuildingSurface is the one that changes the floor heat balance.

SDK facts (dev/probes/probe_ground_temperatures.py, OpenStudio 3.11.0):
  - The four classes are UniqueModelObjects and the PLAIN getter CREATES the object
    (objects 0 -> 1). getOptional<Class>() does not. A read path must use the optional form
    or a "get" tool silently mutates the session model — the same hazard weather/operations.py
    already documents at :240 and sidesteps at :295 with getOptionalWeatherFile().
  - Per-month named accessors differ by class (setJanuaryGroundTemperature on BuildingSurface
    and FCfactorMethod, setJanuarySurfaceGroundTemperature on Shallow,
    setJanuaryDeepGroundTemperature on Deep) — but all four share a uniform
    setAllMonthlyTemperatures(list_of_12) -> bool, getTemperatureByMonth(1..12),
    isMonthDefaulted(1..12), resetAllMonths(). This module uses only the uniform four, so
    there are no per-class name tables and no string dispatch.
  - setAllMonthlyTemperatures accepts a plain Python list and clears all 12 defaulted flags.
  - Setting one month leaves the others defaulted, so a mixed ("partial") state is real.
  - IDD defaults differ per class: BuildingSurface 18.0, FCfactorMethod 13.0, Shallow 13.0,
    Deep 16.0 — there is no single "18 C everywhere" assumption to lean on.
  - An all-defaulted object IS written to the saved OSM and survives a reload, so presence is
    not evidence that anyone chose a value. Detection has to use isMonthDefaulted.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp_server.config import is_path_allowed, path_denied_hint
from mcp_server.model_manager import ensure_generation_unchanged, get_model_with_generation
from mcp_server.skills.weather.epw_ground_temperatures import (
    EpwGroundTemperatureError,
    GroundTemperatureSet,
    nearest_depth_set,
    read_ground_temperature_sets,
)
from mcp_server.skills.weather.zone_heating_setpoints import zone_heating_setpoints

BUILDING_SURFACE_METHODS = ("setpoint_offset", "epw_raw", "constant", "none")

# Below the indoor temperature, per the EnergyPlus Slab-preprocessor rule of thumb. A rule of
# thumb is all this is — see the module docstring's Kiva note.
SETPOINT_OFFSET_C = 2.0

SHALLOW_TARGET_DEPTH_M = 0.5
FCFACTOR_TARGET_DEPTH_M = 0.5
DEEP_TARGET_DEPTH_M = 4.0

# A nearest-available depth further than this from what was asked for changes the seasonal
# swing enough to be worth saying out loud.
DEPTH_MISMATCH_WARN_M = 1.0

MONTHS = 12
MIN_PLAUSIBLE_C = -60.0
MAX_PLAUSIBLE_C = 60.0

_OBJECT_KEYS = ("building_surface", "fcfactor_method", "shallow", "deep")
_IDF_NAMES = {
    "building_surface": "Site:GroundTemperature:BuildingSurface",
    "fcfactor_method": "Site:GroundTemperature:FCfactorMethod",
    "shallow": "Site:GroundTemperature:Shallow",
    "deep": "Site:GroundTemperature:Deep",
}


def _state_from_optional(optional) -> dict[str, Any]:
    """Side-effect-free state of one Site:GroundTemperature:* object.

    absent    -> the unique object is not in the model
    defaulted -> present, every month still the IDD default: carries no information
    partial   -> present, some months chosen: somebody wrote a few deliberately
    set       -> present, all 12 chosen
    """
    if not optional.is_initialized():
        return {"state": "absent", "monthly_c": None, "months_set": 0}

    obj = optional.get()
    defaulted = [obj.isMonthDefaulted(m) for m in range(1, MONTHS + 1)]
    months_set = sum(1 for d in defaulted if not d)
    if months_set == 0:
        state = "defaulted"
    elif months_set < MONTHS:
        state = "partial"
    else:
        state = "set"
    return {
        "state": state,
        "monthly_c": [round(obj.getTemperatureByMonth(m), 3) for m in range(1, MONTHS + 1)],
        "months_set": months_set,
    }


def read_ground_temperature_state(model) -> dict[str, Any]:
    """Per-object state of the model's four ground-temperature objects.

    Never creates anything: four direct getOptional* calls, no dispatch. Safe to call from a
    read tool.
    """
    return {
        "building_surface": _state_from_optional(
            model.getOptionalSiteGroundTemperatureBuildingSurface()),
        "fcfactor_method": _state_from_optional(
            model.getOptionalSiteGroundTemperatureFCfactorMethod()),
        "shallow": _state_from_optional(model.getOptionalSiteGroundTemperatureShallow()),
        "deep": _state_from_optional(model.getOptionalSiteGroundTemperatureDeep()),
    }


def _missing_from_state(state: dict[str, Any], kiva_surface_count: int = 0,
                       ground_surface_count: int = 0) -> dict[str, Any]:
    unset = [
        key for key in _OBJECT_KEYS
        if state[key]["state"] in ("absent", "defaulted", "partial")
    ]
    # Every ground-coupled surface is solved by Kiva, which ignores BuildingSurface outright.
    # Flagging it then would nag the user for having done the higher-fidelity thing, so it is
    # reported as superseded rather than missing. The other three are inert with or without
    # Kiva (no GHX, no F/C-factor constructions) and stay in the list on the same terms as before.
    all_kiva = kiva_surface_count > 0 and ground_surface_count == 0
    superseded = [_IDF_NAMES[k] for k in unset if all_kiva and k == "building_surface"]
    missing = [_IDF_NAMES[k] for k in unset if _IDF_NAMES[k] not in superseded]
    result: dict[str, Any] = {
        "ground_temperatures_missing": bool(missing),
        "ground_temperatures_missing_count": len(missing),
        "ground_temperatures_state": {k: state[k]["state"] for k in _OBJECT_KEYS},
        "kiva_foundation_surface_count": kiva_surface_count,
    }
    if superseded:
        result["ground_temperatures_superseded_by_kiva"] = superseded
    if missing:
        result["ground_temperatures_missing_objects"] = missing
        if all_kiva:
            result["ground_temperatures_hint"] = (
                f"All {kiva_surface_count} ground-coupled surface(s) use Kiva, which solves its own "
                f"2D soil domain and ignores Site:GroundTemperature:BuildingSurface. The remaining "
                f"objects would be inert here: Shallow and Deep feed ground heat exchangers, "
                f"FCfactorMethod affects only F/C-factor constructions."
            )
        else:
            result["ground_temperatures_hint"] = (
                "EnergyPlus falls back to its own per-object defaults (BuildingSurface 18 C). "
                "Apply the project EPW's values with set_ground_temperatures(), or model the "
                "foundation directly with set_kiva_foundation() when slab-edge heat transfer "
                "matters."
            )
    return result


def find_missing_ground_temperatures() -> dict[str, Any]:
    """Report-only check of the loaded model's ground temperatures.

    Shaped to be merged into repair_and_validate_gbxml_geometry's result without touching its
    `ok`, exactly like find_missing_ground_contact. Needs no EPW and never mutates.
    """
    try:
        model, generation = get_model_with_generation()
        conditions = [s.outsideBoundaryCondition() for s in model.getSurfaces()]
        result = {
            "ok": True,
            **_missing_from_state(
                read_ground_temperature_state(model),
                kiva_surface_count=sum(1 for c in conditions if c == "Foundation"),
                ground_surface_count=sum(1 for c in conditions if c.startswith("Ground")),
            ),
        }
        ensure_generation_unchanged(generation)
        return result
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to check ground temperatures: {e}"}


def _model_weather_epw(model) -> Path | None:
    """The EPW the model's own WeatherFile points at, if it can be reached safely.

    Deliberately not weather.operations.resolve_model_weather_epw: that takes a saved OSM
    path and re-loads it from disk, while this tool works on the in-memory session model that
    may never have been saved (and that function creates a unique object on its throwaway
    copy). An absolute url is honoured only inside the allowlist — a model's weather url is
    caller-controlled and must not reach another tenant's file.
    """
    from mcp_server.skills.weather.operations import find_epw_by_name

    optional = model.getOptionalWeatherFile()
    if not optional.is_initialized():
        return None
    url_path = optional.get().path()
    if not url_path.is_initialized():
        return None

    candidate = Path(str(url_path.get()))
    # Allowlist before existence: the url is caller-controlled, and is_file() on a path outside
    # the allowed roots would be an existence probe even though the result is never returned.
    if candidate.is_absolute() and is_path_allowed(candidate) and candidate.is_file():
        return candidate

    found = find_epw_by_name(candidate.name)
    if found is not None and is_path_allowed(found):
        return found
    return None


def _resolve_epw(model, generation: int, epw_path: str | None) -> tuple[Path | None, str]:
    """(epw, source) or (None, reason). Sources: argument, gbxml_import_stash, model_weather_file."""
    if epw_path is not None:
        candidate = Path(epw_path)
        if candidate.suffix.lower() != ".epw":
            return None, f"Not an EPW file (expected .epw): {epw_path}"
        # Allowlist before existence, so a path outside it gets the same answer whether or
        # not a file is there — the existence check must not double as a probe.
        if not is_path_allowed(candidate):
            return None, f"EPW path not allowed: {epw_path}. {path_denied_hint()}"
        if not candidate.is_file():
            return None, f"EPW file not found: {epw_path}"
        return candidate, "argument"

    from mcp_server.skills.gbxml_import.gbxml_source_state import get_epw_for_model

    stashed = get_epw_for_model(generation)
    if stashed is not None:
        candidate = Path(stashed)
        # Run retention may have swept the staged copy — that is a miss, not an error.
        if candidate.is_file() and is_path_allowed(candidate):
            return candidate, "gbxml_import_stash"

    from_model = _model_weather_epw(model)
    if from_model is not None:
        return from_model, "model_weather_file"

    return None, (
        "No EPW to read ground temperatures from. Tried: the epw_path argument (not given), "
        "the EPW stashed by import_gbxml for this model (none), and the model's own weather "
        "file (absent or unresolvable). Pass epw_path, or set the model's weather with "
        "change_building_location."
    )


def _kiva_interaction(model) -> dict[str, int]:
    """How many surfaces Kiva governs versus how many BuildingSurface still reaches.

    The mirror of set_kiva_foundation's ground_temperature_interaction: a Foundation surface
    ignores Site:GroundTemperature:BuildingSurface, so writing it after Kiva can be a no-op
    that looks effective unless this says so.
    """
    conditions = [s.outsideBoundaryCondition() for s in model.getSurfaces()]
    return {
        "foundation_surface_count": sum(1 for c in conditions if c == "Foundation"),
        "ground_surface_count": sum(1 for c in conditions if c.startswith("Ground")),
    }


def _write_monthly(obj, values: list[float], label: str) -> str | None:
    """Write 12 monthly temperatures. Returns an error string, or None on success."""
    if not obj.setAllMonthlyTemperatures(values):
        return f"OpenStudio refused the monthly temperatures for {label}"
    return None


def _building_surface_values(
    model,
    method: str,
    constant_c: float | None,
    shallow_set: GroundTemperatureSet,
) -> tuple[list[float] | None, dict[str, Any]]:
    """(values or None, detail). None means "write nothing", and detail says why."""
    if method == "none":
        return None, {"reason": "building_surface_method='none'"}

    if method == "constant":
        return [constant_c] * MONTHS, {
            "source": "constant",
            "constant_c": constant_c,
        }

    if method == "epw_raw":
        return list(shallow_set.monthly_c), {
            "source": "epw_raw_against_guidance",
            "depth_m": shallow_set.depth_m,
        }

    setpoints = zone_heating_setpoints(model)
    if setpoints["mean_c"] is None:
        return None, {
            "reason": (
                f"{setpoints['skip_reason']} — cannot derive a setpoint offset. Run this after "
                f"thermostats exist, or pass building_surface_method='constant' with "
                f"building_surface_constant_c, or 'epw_raw' to accept the undisturbed values."
            ),
            "zones_with_thermostat": setpoints["zones_with_thermostat"],
        }

    value = round(setpoints["mean_c"] - SETPOINT_OFFSET_C, 3)
    return [value] * MONTHS, {
        "source": "setpoint_offset",
        "mean_heating_setpoint_c": round(setpoints["mean_c"], 3),
        "offset_c": SETPOINT_OFFSET_C,
        "zone_count": setpoints["zone_count"],
        "setpoint_spread_warning": setpoints["spread_warning"],
    }


def set_ground_temperatures(
    epw_path: str | None = None,
    building_surface_method: str = "setpoint_offset",
    building_surface_constant_c: float | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Apply an EPW header's ground temperatures to the loaded model. See the module docstring."""
    if building_surface_method not in BUILDING_SURFACE_METHODS:
        return {
            "ok": False,
            "error": f"Unknown building_surface_method '{building_surface_method}'. "
                     f"Valid: {list(BUILDING_SURFACE_METHODS)}",
        }
    if building_surface_method == "constant":
        if building_surface_constant_c is None:
            return {
                "ok": False,
                "error": "building_surface_method='constant' requires building_surface_constant_c",
            }
        if not MIN_PLAUSIBLE_C <= building_surface_constant_c <= MAX_PLAUSIBLE_C:
            return {
                "ok": False,
                "error": f"building_surface_constant_c {building_surface_constant_c} is outside "
                         f"{MIN_PLAUSIBLE_C}..{MAX_PLAUSIBLE_C} C",
            }

    try:
        model, generation = get_model_with_generation()
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}

    try:
        warnings: list[str] = []
        if building_surface_constant_c is not None and building_surface_method != "constant":
            warnings.append(
                f"building_surface_constant_c was given but building_surface_method is "
                f"'{building_surface_method}'; the value is unused.",
            )

        epw, source = _resolve_epw(model, generation, epw_path)
        if epw is None:
            return {"ok": False, "error": source}

        try:
            sets, parse_warnings = read_ground_temperature_sets(epw)
        except EpwGroundTemperatureError as e:
            return {"ok": False, "error": str(e), "epw_path": str(epw), "epw_source": source}
        warnings.extend(parse_warnings)

        shallow_set, shallow_delta = nearest_depth_set(sets, SHALLOW_TARGET_DEPTH_M)
        fcfactor_set, fcfactor_delta = nearest_depth_set(sets, FCFACTOR_TARGET_DEPTH_M)
        deep_set, deep_delta = nearest_depth_set(sets, DEEP_TARGET_DEPTH_M)
        for target, chosen, delta in (
            (SHALLOW_TARGET_DEPTH_M, shallow_set, shallow_delta),
            (DEEP_TARGET_DEPTH_M, deep_set, deep_delta),
        ):
            if delta > DEPTH_MISMATCH_WARN_M:
                warnings.append(
                    f"Nearest available depth to {target} m is {chosen.depth_m} m "
                    f"({delta:.1f} m away); its seasonal swing will not match the depth asked for.",
                )

        before = read_ground_temperature_state(model)
        surface_values, surface_detail = _building_surface_values(
            model, building_surface_method, building_surface_constant_c, shallow_set,
        )
        if building_surface_method == "epw_raw":
            warnings.append(
                "building_surface_method='epw_raw' writes UNDISTURBED soil temperatures to "
                "Site:GroundTemperature:BuildingSurface. The EPW's own .stat says these "
                '"should NOT BE USED in the GroundTemperatures object to compute building '
                'floor losses" — expect overstated slab heat loss.',
            )

        planned: list[tuple[str, Any, list[float] | None, dict[str, Any]]] = [
            ("building_surface", model.getSiteGroundTemperatureBuildingSurface,
             surface_values, surface_detail),
            ("fcfactor_method", model.getSiteGroundTemperatureFCfactorMethod,
             list(fcfactor_set.monthly_c),
             {"source": "epw_raw", "depth_m": fcfactor_set.depth_m,
              "depth_delta_m": round(fcfactor_delta, 3),
              "note": "affects F/C-factor constructions only"}),
            ("shallow", model.getSiteGroundTemperatureShallow,
             list(shallow_set.monthly_c),
             {"source": "epw_raw", "depth_m": shallow_set.depth_m,
              "depth_delta_m": round(shallow_delta, 3),
              "note": "feeds ground heat exchangers, not the floor heat balance"}),
            ("deep", model.getSiteGroundTemperatureDeep,
             list(deep_set.monthly_c),
             {"source": "epw_raw", "depth_m": deep_set.depth_m,
              "depth_delta_m": round(deep_delta, 3),
              "note": "feeds ground heat exchangers, not the floor heat balance"}),
        ]

        applied: dict[str, Any] = {}
        skipped: dict[str, Any] = {}
        for key, getter, values, detail in planned:
            label = _IDF_NAMES[key]
            if values is None:
                skipped[label] = detail.get("reason", "not requested")
                continue
            if before[key]["state"] in ("set", "partial") and not overwrite:
                skipped[label] = (
                    f"already {before[key]['state']} — pass overwrite=True to replace it"
                )
                continue
            error = _write_monthly(getter(), values, label)
            if error is not None:
                return {"ok": False, "error": error, "epw_path": str(epw)}
            entry = {"monthly_c": [round(v, 3) for v in values], **detail}
            if before[key]["state"] in ("set", "partial"):
                entry["replaced_monthly_c"] = before[key]["monthly_c"]
            applied[label] = entry

        after = read_ground_temperature_state(model)
        interaction = _kiva_interaction(model)
        if interaction["foundation_surface_count"] > 0 and "Site:GroundTemperature:BuildingSurface" in applied:
            warnings.append(
                f"{interaction['foundation_surface_count']} surface(s) use Kiva (Foundation boundary "
                f"condition) and ignore Site:GroundTemperature:BuildingSurface entirely. It "
                + (
                    f"still applies to the {interaction['ground_surface_count']} remaining Ground "
                    f"surface(s)."
                    if interaction["ground_surface_count"] else
                    "applies to no surface in this model — writing it changed nothing thermally."
                ),
            )
        ensure_generation_unchanged(generation)
        return {
            "ok": True,
            "epw_path": str(epw),
            "epw_source": source,
            "depth_sets_available": [s.depth_m for s in sets],
            "building_surface_method": building_surface_method,
            "applied": applied,
            "skipped": skipped,
            "warnings": warnings,
            "ground_temperatures": after,
            "kiva_interaction": interaction,
            "note": "Changes the in-memory model; call save_osm_model to persist.",
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to set ground temperatures: {e}"}
