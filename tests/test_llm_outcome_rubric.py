"""Unit tests for the outcome-grading rubric (tests/llm/grading/rubric.py).

Pure dict fixtures — no openstudio, no docker. Known-bad facts MUST fail
with the expected reason (falsifiability of the benchmark's gate 2).
"""
from __future__ import annotations

import pytest
from llm.grading import rubric
from llm.grading.host import ROUTING_ONLY

pytestmark = pytest.mark.unit


def _model(**overrides) -> dict:
    """A facts['model'] dump matching the healthy System-7 fixture."""
    base = {
        "n_spaces": 10, "n_thermal_zones": 10, "floor_area_m2": 929.03,
        "plant_loops": ["Chilled Water Loop", "Hot Water Loop"],
        "air_loops": [{
            "name": "VAV", "zones_served": [f"Zone {i}" for i in range(10)],
            "terminals": {"OS:AirTerminal:SingleDuct:VAV:Reheat": 10},
        }],
        "n_zones_on_air_loops": 10,
        "zone_equipment": [], "roof_surfaces": [], "thermostats": [],
        "python_plugins": [], "external_files": [],
    }
    return base | overrides


def test_unsaved_model_fails_with_save_reason():
    # Validates: an agent that never calls save_osm_model fails outcome with a
    # reason naming the save contract, not a cryptic load error
    verdict = rubric.evaluate("add_hvac", "L1", {"load_ok": False})
    assert verdict["outcome_pass"] is False
    assert "save_osm_model" in verdict["reasons"][0]


def test_grader_infrastructure_failure_is_ungradable():
    # Validates: docker/timeout failures are separable from agent failures in
    # analysis via the "ungradable" reason prefix
    verdict = rubric.evaluate("roof_insulation", "L2",
                              {"grader_error": "grader timeout after 180s"})
    assert verdict["outcome_pass"] is False
    assert verdict["reasons"][0].startswith("ungradable:")


def test_import_floorplan_l1_is_routing_only():
    # Validates: L1 names no floorplan file — no outcome contract exists, and
    # host.ROUTING_ONLY agrees with the rubric
    assert rubric.evaluate("import_floorplan", "L1", {}) is None
    assert ("import_floorplan", "L1") in ROUTING_ONLY


def test_baseline_hvac_pass_and_partial_fail():
    # Validates: Sys-7 fixture facts pass; a loop serving 6/10 zones fails with
    # the zone count in the reason (partial-wiring must not pass)
    good = {"load_ok": True, "model": _model()}
    assert rubric.evaluate("create_baseline_with_hvac", "setup",
                           good)["outcome_pass"] is True
    partial = {"load_ok": True, "model": _model(
        n_zones_on_air_loops=6,
        air_loops=[{"name": "VAV", "zones_served": [f"Z{i}" for i in range(6)],
                    "terminals": {"OS:AirTerminal:SingleDuct:VAV:Reheat": 6}}])}
    verdict = rubric.evaluate("create_baseline_with_hvac", "setup", partial)
    assert verdict["outcome_pass"] is False
    assert any("6" in r for r in verdict["reasons"])


def test_measure_replace_partial_replacement_fails():
    # Regression: routing-only grading scored syntax-valid partial measures as
    # passes — 1 beam / 9 remaining VAV must fail with both counts cited
    facts = {"measure_ran": True, "completed_status": "Success",
             "result_model": _model(air_loops=[{
                 "name": "VAV", "zones_served": [f"Z{i}" for i in range(10)],
                 "terminals": {
                     "OS:AirTerminal:SingleDuct:ConstantVolume:FourPipeBeam": 1,
                     "OS:AirTerminal:SingleDuct:VAV:Reheat": 9,
                 }}])}
    verdict = rubric.evaluate("measure_replace_terminals", "L2", facts)
    assert verdict["outcome_pass"] is False
    assert any("expected 10 FourPipeBeam" in r for r in verdict["reasons"])
    assert any("9 VAV terminals remain" in r for r in verdict["reasons"])


def test_measure_replace_full_replacement_passes():
    # Validates: complete replacement (10 beams, 0 VAV, 10 zones connected)
    # passes gate 2
    facts = {"measure_ran": True, "completed_status": "Success",
             "result_model": _model(air_loops=[{
                 "name": "VAV", "zones_served": [f"Z{i}" for i in range(10)],
                 "terminals": {
                     "OS:AirTerminal:SingleDuct:ConstantVolume:FourPipeBeam": 10,
                 }}])}
    assert rubric.evaluate("measure_replace_terminals", "L3",
                           facts)["outcome_pass"] is True


def test_measure_run_failure_fails_with_runner_errors():
    # Validates: a measure that errors at run time fails with completed_status
    # and runner errors surfaced
    facts = {"measure_ran": False, "completed_status": "Fail",
             "runner_errors": ["undefined method 'foo'"]}
    verdict = rubric.evaluate("measure_replace_terminals", "L1", facts)
    assert verdict["outcome_pass"] is False
    assert "completed_status=Fail" in verdict["reasons"][0]


def _ems_facts(night: float, day: float) -> dict:
    stats = {f"ZONE {i}": {"night": {"mean": night, "min": night, "max": night,
                                     "n": 432},
                           "day": {"mean": day, "min": day, "max": day,
                                   "n": 432}}
             for i in range(10)}
    return {"saved": True, "load_ok": True, "sim_ran": True,
            "setpoint_stats": stats}


def test_ems_correct_setback_passes_l2_and_l1():
    # Validates: measured 15.6 night / 21.1 day passes both the pinned (L2)
    # and directional (L1) rubrics
    facts = _ems_facts(night=15.6, day=21.1)
    assert rubric.evaluate("python_ems_control", "L2",
                           facts)["outcome_pass"] is True
    assert rubric.evaluate("python_ems_control", "L1",
                           facts)["outcome_pass"] is True


def test_ems_flat_setpoint_fails_both_levels():
    # Regression: routing-only grading passed agents whose plugin never changed
    # the setpoint — a flat 21.1/21.1 profile must fail L1 AND L2
    facts = _ems_facts(night=21.1, day=21.1)
    l2 = rubric.evaluate("python_ems_control", "L2", facts)
    assert l2["outcome_pass"] is False
    assert any("night mean 21.1" in r for r in l2["reasons"])
    l1 = rubric.evaluate("python_ems_control", "L1", facts)
    assert l1["outcome_pass"] is False
    assert any("no setback" in r for r in l1["reasons"])


def test_ems_day_value_clobbered_fails_l2():
    # Validates: an always-15.6 override (agent set default_value wrong) fails
    # L2 on the day check even though night is correct
    facts = _ems_facts(night=15.6, day=15.6)
    verdict = rubric.evaluate("python_ems_control", "L2", facts)
    assert verdict["outcome_pass"] is False
    assert any("day mean 15.6" in r for r in verdict["reasons"])


def test_ems_tolerance_boundary_is_inclusive():
    # Regression: val-grading leg failed day mean 21.0 vs 21.1 on IEEE noise —
    # a drift of EXACTLY the +-0.1 tolerance is within tolerance (inclusive);
    # 0.11 is not
    at_edge = _ems_facts(night=15.6, day=21.0)
    assert rubric.evaluate("python_ems_control", "L2",
                           at_edge)["outcome_pass"] is True
    beyond = _ems_facts(night=15.6, day=20.99)
    assert rubric.evaluate("python_ems_control", "L2",
                           beyond)["outcome_pass"] is False


def test_ems_sim_failure_fails_with_cli_context():
    # Validates: a saved-but-unsimulatable model fails with the grading-sim
    # context, not a KeyError
    facts = {"saved": True, "load_ok": True, "sim_ran": False, "cli_rc": 1,
             "eplus_severe_n": 3}
    verdict = rubric.evaluate("python_ems_control", "L3", facts)
    assert verdict["outcome_pass"] is False
    assert "grading simulation failed" in verdict["reasons"][0]


def test_zone_priority_baseboard_first_passes_last_fails():
    # Regression: routing-only grading passed add-without-reorder; baseboard
    # last in heating order must fail, first must pass
    def zfacts(order):
        return {"load_ok": True, "model": _model(zone_equipment=[{
            "zone": "Zone 1",
            "equipment_classes": {"Baseboard Htr": "OS:ZoneHVAC:Baseboard:Convective:Electric",
                                  "Terminal": "OS:AirTerminal:SingleDuct:VAV:Reheat"},
            "heating_order": order, "cooling_order": ["Terminal"]}])}
    good = rubric.evaluate("zone_equipment_priority", "L2",
                           zfacts(["Baseboard Htr", "Terminal"]))
    assert good["outcome_pass"] is True
    bad = rubric.evaluate("zone_equipment_priority", "L2",
                          zfacts(["Terminal", "Baseboard Htr"]))
    assert bad["outcome_pass"] is False
    assert any("not first in heating order" in r for r in bad["reasons"])


def test_zone_priority_no_baseboard_fails():
    # Validates: reordering without ever adding the baseboard fails
    facts = {"load_ok": True, "model": _model(zone_equipment=[{
        "zone": "Zone 1", "equipment_classes": {"T": "OS:AirTerminal:X"},
        "heating_order": ["T"], "cooling_order": ["T"]}])}
    verdict = rubric.evaluate("zone_equipment_priority", "L1", facts)
    assert verdict["outcome_pass"] is False
    assert "no baseboard" in verdict["reasons"][0]


def _roof(*layer_rs: float) -> list[dict]:
    return [{"surface": "Roof 1", "construction": "C",
             "layers": [{"name": f"L{i}", "class": "OS:Material", "r_si": r}
                        for i, r in enumerate(layer_rs)],
             "assembly_r_si": round(sum(layer_rs), 4)}]


def test_roof_insulation_r30_added_passes_l1_partial_fails():
    # Regression: routing-only grading passed material-creation-without-
    # assignment; assembly R must actually increase by ~R-30 at L1
    good = {"load_ok": True, "model": _model(roof_surfaces=_roof(6.0)),
            "baseline": _model(roof_surfaces=_roof(0.6))}
    assert rubric.evaluate("roof_insulation", "L1", good)["outcome_pass"] is True
    unchanged = {"load_ok": True, "model": _model(roof_surfaces=_roof(0.6)),
                 "baseline": _model(roof_surfaces=_roof(0.6))}
    verdict = rubric.evaluate("roof_insulation", "L1", unchanged)
    assert verdict["outcome_pass"] is False
    assert "assembly R increase" in verdict["reasons"][0]


def test_roof_insulation_l1_accepts_insulate_to_r30_reading():
    # Regression: val-grading rubric 1.0 failed sonnet's CORRECT roof (swapped
    # R-21 layer for an exact R-30 layer, membrane+decking kept) by demanding
    # a +R-30 assembly DELTA; an R-30 layer + any improvement must pass
    sonnet_style = {"load_ok": True,
                    "model": _model(roof_surfaces=_roof(0.0594, 5.2818, 0.0)),
                    "baseline": _model(roof_surfaces=_roof(0.0594, 4.2959, 0.0))}
    assert rubric.evaluate("roof_insulation", "L1",
                           sonnet_style)["outcome_pass"] is True
    bare_slab = {"load_ok": True, "model": _model(roof_surfaces=_roof(5.25)),
                 "baseline": _model(roof_surfaces=_roof(0.0594, 4.2959, 0.0))}
    assert rubric.evaluate("roof_insulation", "L1",
                           bare_slab)["outcome_pass"] is True


def test_roof_insulation_l1_r30_layer_must_still_improve_roof():
    # Validates: an ~R-30 layer that leaves the assembly WORSE than baseline
    # (replaced a better roof) fails despite the layer being nominally R-30
    worse = {"load_ok": True, "model": _model(roof_surfaces=_roof(5.25)),
             "baseline": _model(roof_surfaces=_roof(0.0594, 5.9, 0.1))}
    verdict = rubric.evaluate("roof_insulation", "L1", worse)
    assert verdict["outcome_pass"] is False
    assert "R-30 layer present: True" in verdict["reasons"][0]


def test_roof_insulation_l2_requires_only_real_increase():
    # Validates: L2 prompt pins no R-value — any material increase > 0.5 passes,
    # a trivial 0.1 bump fails
    small = {"load_ok": True, "model": _model(roof_surfaces=_roof(0.7)),
             "baseline": _model(roof_surfaces=_roof(0.6))}
    assert rubric.evaluate("roof_insulation", "L2", small)["outcome_pass"] is False
    real = {"load_ok": True, "model": _model(roof_surfaces=_roof(1.8)),
            "baseline": _model(roof_surfaces=_roof(0.6))}
    assert rubric.evaluate("roof_insulation", "L2", real)["outcome_pass"] is True
