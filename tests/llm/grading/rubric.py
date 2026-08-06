"""Rubric v1: pure functions facts -> verdict for outcome grading.

No openstudio import (host-side, unit-testable). Facts come from
container_grader.py. Thresholds are module constants so a rubric bump can
re-score recorded facts post-hoc without re-running any leg — see
docs/plans/plan-outcome-grading.md.

Class-name checks use substrings of iddObjectType().valueDescription()
(e.g. "FourPipeBeam") to stay robust to IDD name formatting.
"""
from __future__ import annotations

RUBRIC_VERSION = "1.0"

N_ZONES = 10                 # baseline fixture zone count
NIGHT_SETPOINT_C = 15.6      # L2/L3 pinned setback value
DAY_SETPOINT_C = 21.1        # baseline heating setpoint
SETPOINT_TOL_C = 0.1
L1_MIN_SETBACK_K = 1.0       # L1 only asserts direction: night <= day - 1K
R30_SI = 5.283               # R-30 ft2hF/Btu in m2K/W
R30_MIN_INCREASE_SI = R30_SI * 0.85
L2_MIN_R_INCREASE_SI = 0.5   # L2/L3 don't pin a value; require a real increase


def _fail(reasons: list[str]) -> dict:
    return {"rubric_version": RUBRIC_VERSION, "outcome_pass": False,
            "reasons": reasons}


def _ok() -> dict:
    return {"rubric_version": RUBRIC_VERSION, "outcome_pass": True,
            "reasons": []}


def _verdict(reasons: list[str]) -> dict:
    return _fail(reasons) if reasons else _ok()


def _terminal_count(model_facts: dict, substring: str) -> int:
    return sum(n for loop in model_facts.get("air_loops", [])
               for cls, n in loop.get("terminals", {}).items()
               if substring in cls)


def _loaded_model(facts: dict) -> tuple[dict | None, list[str]]:
    if not facts.get("load_ok"):
        return None, ["saved model missing or unreadable (agent must "
                      "save_osm_model to the graded path)"]
    return facts["model"], []


def grade_create_baseline_model(level: str, facts: dict) -> dict:
    model, reasons = _loaded_model(facts)
    if model is None:
        return _fail(reasons)
    if model["n_thermal_zones"] != N_ZONES:
        reasons.append(f"expected {N_ZONES} thermal zones, "
                       f"got {model['n_thermal_zones']}")
    return _verdict(reasons)


def grade_create_baseline_with_hvac(level: str, facts: dict) -> dict:
    model, reasons = _loaded_model(facts)
    if model is None:
        return _fail(reasons)
    if model["n_thermal_zones"] != N_ZONES:
        reasons.append(f"expected {N_ZONES} zones, got {model['n_thermal_zones']}")
    if model.get("n_zones_on_air_loops") != N_ZONES:
        reasons.append(f"System 7 must serve all {N_ZONES} zones, "
                       f"{model.get('n_zones_on_air_loops')} on air loops")
    vav = _terminal_count(model, "VAV")
    if vav != N_ZONES:
        reasons.append(f"expected {N_ZONES} VAV terminals, got {vav}")
    plants = [p.lower() for p in model.get("plant_loops", [])]
    if not any("hot water" in p for p in plants):
        reasons.append("no hot water plant loop")
    if not any("chilled" in p for p in plants):
        reasons.append("no chilled water plant loop")
    return _verdict(reasons)


# Ground truth for /inputs/sddc_office/floorplan.json — recorded 2026-08-06
# by importing the fixture via import_floorspacejs in the pinned image
# (44 spaces / 44 zones / 1858.06 m2, 2 stories). None = not recorded,
# rubric then only requires a non-empty imported model.
FLOORPLAN_TRUTH: dict = {"n_spaces": 44, "floor_area_m2": 1858.06}


def grade_import_floorplan(level: str, facts: dict) -> dict | None:
    if level == "L1":
        return None  # no file named in the L1 prompt — routing-only
    model, reasons = _loaded_model(facts)
    if model is None:
        return _fail(reasons)
    if model["n_spaces"] < 1:
        reasons.append("imported model has no spaces")
    if model["floor_area_m2"] <= 0:
        reasons.append("imported model has zero floor area")
    truth_spaces = FLOORPLAN_TRUTH["n_spaces"]
    if truth_spaces is not None and model["n_spaces"] != truth_spaces:
        reasons.append(f"expected {truth_spaces} spaces from fixture, "
                       f"got {model['n_spaces']}")
    truth_area = FLOORPLAN_TRUTH["floor_area_m2"]
    if truth_area is not None and not (
            0.95 * truth_area <= model["floor_area_m2"] <= 1.05 * truth_area):
        reasons.append(f"floor area {model['floor_area_m2']} m2 not within "
                       f"5% of fixture {truth_area} m2")
    return _verdict(reasons)


def grade_add_hvac(level: str, facts: dict) -> dict:
    model, reasons = _loaded_model(facts)
    if model is None:
        return _fail(reasons)
    if level == "L1":
        # Any HVAC serving every zone counts (accept-set includes DOAS/VRF/
        # radiant): zone is served if on an air loop or has zone equipment.
        unserved = [z["zone"] for z in model.get("zone_equipment", [])
                    if not z["heating_order"] and not z["cooling_order"]]
        on_loops = model.get("n_zones_on_air_loops", 0)
        if on_loops < N_ZONES and unserved:
            reasons.append(f"zones without any HVAC: {unserved[:4]} "
                           f"({on_loops}/{N_ZONES} on air loops)")
    else:
        vav = _terminal_count(model, "VAV")
        if model.get("n_zones_on_air_loops") != N_ZONES:
            reasons.append(f"System 7 must serve all {N_ZONES} zones, "
                           f"{model.get('n_zones_on_air_loops')} on air loops")
        if vav != N_ZONES:
            reasons.append(f"expected {N_ZONES} VAV terminals, got {vav}")
        plants = [p.lower() for p in model.get("plant_loops", [])]
        if not any("hot water" in p for p in plants):
            reasons.append("no hot water plant loop (Sys 7 needs reheat HW)")
        if not any("chilled" in p for p in plants):
            reasons.append("no chilled water plant loop")
    return _verdict(reasons)


def grade_python_ems_control(level: str, facts: dict) -> dict:
    if not facts.get("saved") or not facts.get("load_ok"):
        return _fail(["saved model missing or unreadable (agent must "
                      "save_osm_model to the graded path)"])
    if not facts.get("sim_ran"):
        return _fail([f"grading simulation failed "
                      f"(cli_rc={facts.get('cli_rc')}, "
                      f"severe={facts.get('eplus_severe_n')})"])
    stats = facts.get("setpoint_stats", {})
    if not stats:
        return _fail(["no Zone Thermostat Heating Setpoint Temperature rows "
                      "in grading SQL"])
    reasons = []
    for zone, buckets in stats.items():
        night = buckets.get("night", {}).get("mean")
        day = buckets.get("day", {}).get("mean")
        if night is None or day is None:
            reasons.append(f"{zone}: missing night/day setpoint data")
            continue
        if level == "L1":
            if night > day - L1_MIN_SETBACK_K:
                reasons.append(f"{zone}: no setback — night mean {night} vs "
                               f"day mean {day}")
        else:
            if abs(night - NIGHT_SETPOINT_C) > SETPOINT_TOL_C:
                reasons.append(f"{zone}: night mean {night}, "
                               f"expected {NIGHT_SETPOINT_C}")
            if abs(day - DAY_SETPOINT_C) > SETPOINT_TOL_C:
                reasons.append(f"{zone}: day mean {day}, "
                               f"expected {DAY_SETPOINT_C} (unchanged)")
    return _verdict(reasons[:6])


def grade_measure_replace_terminals(level: str, facts: dict) -> dict:
    if facts.get("error"):
        return _fail([facts["error"]])
    reasons = []
    if not facts.get("measure_ran"):
        reasons.append(f"measures_only run failed (completed_status="
                       f"{facts.get('completed_status')}, "
                       f"errors={facts.get('runner_errors', [])[:2]})")
        return _fail(reasons)
    result = facts.get("result_model")
    if not result:
        return _fail(["run/in.osm missing or unreadable after measure run"])
    beams = _terminal_count(result, "FourPipeBeam")
    vav = _terminal_count(result, "VAV")
    if beams != N_ZONES:
        reasons.append(f"expected {N_ZONES} FourPipeBeam terminals, got {beams}")
    if vav != 0:
        reasons.append(f"{vav} VAV terminals remain")
    if result.get("n_zones_on_air_loops") != N_ZONES:
        reasons.append(f"only {result.get('n_zones_on_air_loops')}/{N_ZONES} "
                       "zones still connected to air loops")
    return _verdict(reasons)


def grade_zone_equipment_priority(level: str, facts: dict) -> dict:
    model, reasons = _loaded_model(facts)
    if model is None:
        return _fail(reasons)
    zones_with_baseboard = []
    for z in model.get("zone_equipment", []):
        baseboards = [name for name, cls in z["equipment_classes"].items()
                      if "Baseboard" in cls]
        if baseboards:
            zones_with_baseboard.append((z, baseboards))
    if not zones_with_baseboard:
        return _fail(["no baseboard equipment found in any zone"])
    z, baseboards = zones_with_baseboard[0]
    order = z["heating_order"]
    if not order or order[0] not in baseboards:
        reasons.append(f"baseboard not first in heating order for "
                       f"{z['zone']}: {order}")
    return _verdict(reasons)


def grade_roof_insulation(level: str, facts: dict) -> dict:
    model, reasons = _loaded_model(facts)
    if model is None:
        return _fail(reasons)
    baseline = facts.get("baseline") or {}
    graded_roofs = model.get("roof_surfaces", [])
    base_roofs = baseline.get("roof_surfaces", [])
    if not graded_roofs:
        return _fail(["no exterior roof surfaces in graded model"])
    graded_rs = [r["assembly_r_si"] for r in graded_roofs]
    base_rs = [r["assembly_r_si"] for r in base_roofs]
    if any(r is None for r in graded_rs) or not base_rs or any(
            r is None for r in base_rs):
        return _fail(["assembly R not computable (unknown layer resistance)"])
    increase = (sum(graded_rs) / len(graded_rs)) - (sum(base_rs) / len(base_rs))
    minimum = R30_MIN_INCREASE_SI if level == "L1" else L2_MIN_R_INCREASE_SI
    if increase < minimum:
        reasons.append(f"roof assembly R increase {increase:.2f} m2K/W < "
                       f"required {minimum:.2f} (level {level})")
    return _verdict(reasons)


_GRADERS = {
    "create_baseline_model": grade_create_baseline_model,
    "create_baseline_with_hvac": grade_create_baseline_with_hvac,
    "import_floorplan": grade_import_floorplan,
    "add_hvac": grade_add_hvac,
    "python_ems_control": grade_python_ems_control,
    "measure_replace_terminals": grade_measure_replace_terminals,
    "zone_equipment_priority": grade_zone_equipment_priority,
    "roof_insulation": grade_roof_insulation,
}


def evaluate(case_id: str, level: str, facts: dict) -> dict | None:
    """Verdict for one graded case, or None when the level is routing-only.

    Grader infrastructure failures (docker error/timeout) arrive as
    {"grader_error": ...} and fail with the distinguishable reason
    "ungradable" so analysis can separate them from agent failures.
    """
    if "grader_error" in facts:
        return _fail([f"ungradable: {facts['grader_error']}"])
    return _GRADERS[case_id](level, facts)
