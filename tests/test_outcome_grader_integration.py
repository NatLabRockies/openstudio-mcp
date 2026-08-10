"""Integration tests for the outcome-grading fact extractor.

Ground truth for plan-outcome-grading.md gate 2: a known-good artifact
must grade outcome_pass=True and a known-bad artifact must fail with the
expected reason — proving the grader falsifiable BEFORE it grades
agent-authored artifacts in the LLM benchmark. Runs in the Docker image
(needs openstudio SDK + CLI); mocks nothing.
"""
from __future__ import annotations

import argparse
import shutil
import uuid

import pytest
from conftest import integration_enabled
from llm.grading import container_grader, rubric

pytestmark = pytest.mark.skipif(not integration_enabled(),
                                reason="integration disabled")

# Correct terminal replacement — the L3 recipe the benchmark prompt describes.
GOOD_RUBY = """\
    chw_loop = model.getPlantLoops.find { |pl| pl.nameString.downcase.include?('chilled') }
    hw_loop = model.getPlantLoops.find { |pl| pl.nameString.downcase.include?('hot') }
    model.getAirLoopHVACs.each do |air_loop|
      air_loop.thermalZones.each do |zone|
        air_loop.removeBranchForZone(zone)
        cooling_coil = OpenStudio::Model::CoilCoolingFourPipeBeam.new(model)
        heating_coil = OpenStudio::Model::CoilHeatingFourPipeBeam.new(model)
        chw_loop.addDemandBranchForComponent(cooling_coil) unless chw_loop.nil?
        hw_loop.addDemandBranchForComponent(heating_coil) unless hw_loop.nil?
        terminal = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeFourPipeBeam.new(
          model, cooling_coil, heating_coil)
        air_loop.addBranchForZone(zone, terminal.to_StraightComponent.get)
      end
    end
    runner.registerInfo('Replaced all terminals with four pipe beams')
"""

# Partial work: replaces ONE zone's terminal, reports Success — the exact
# failure mode routing-only grading could not catch.
PARTIAL_RUBY = """\
    chw_loop = model.getPlantLoops.find { |pl| pl.nameString.downcase.include?('chilled') }
    hw_loop = model.getPlantLoops.find { |pl| pl.nameString.downcase.include?('hot') }
    air_loop = model.getAirLoopHVACs.first
    zone = air_loop.thermalZones.first
    air_loop.removeBranchForZone(zone)
    cooling_coil = OpenStudio::Model::CoilCoolingFourPipeBeam.new(model)
    heating_coil = OpenStudio::Model::CoilHeatingFourPipeBeam.new(model)
    chw_loop.addDemandBranchForComponent(cooling_coil) unless chw_loop.nil?
    hw_loop.addDemandBranchForComponent(heating_coil) unless hw_loop.nil?
    terminal = OpenStudio::Model::AirTerminalSingleDuctConstantVolumeFourPipeBeam.new(model, cooling_coil, heating_coil)
    air_loop.addBranchForZone(zone, terminal.to_StraightComponent.get)
    runner.registerInfo('Replaced one terminal')
"""


def _sys7_seed(tmp_path):
    import openstudio

    from mcp_server.skills.model_management.baseline_model import (
        create_baseline_model,
    )
    model, _info = create_baseline_model(name="grader-fixture",
                                         ashrae_sys_num="07")
    seed = tmp_path / "seed.osm"
    model.save(openstudio.toPath(str(seed)), True)
    return seed


def _authored_measure(name: str, run_body: str):
    from mcp_server.skills.measure_authoring.operations import (
        create_measure_op,
        custom_measures_dir,
    )
    result = create_measure_op(
        name=name, description="grader ground truth",
        run_body=run_body, language="Ruby")
    assert result["ok"] is True, f"create_measure_op failed: {result.get('error')}"
    return custom_measures_dir() / name


def _apply_and_grade(measure_dir, seed, work, level="L2"):
    facts = container_grader.apply_measure_mode(argparse.Namespace(
        work=str(work), measure_dir=str(measure_dir), osm=str(seed)))
    return facts, rubric.evaluate("measure_replace_terminals", level, facts)


@pytest.mark.integration
def test_measure_grader_correct_replacement_passes(tmp_path):
    # Validates: grader confirms a correct replacement measure — 10 FourPipeBeam,
    # 0 VAV, all 10 zones reconnected — before it ever grades agent artifacts
    seed = _sys7_seed(tmp_path)
    name = f"grader_good_{uuid.uuid4().hex[:8]}"
    measure_dir = _authored_measure(name, GOOD_RUBY)
    try:
        facts, verdict = _apply_and_grade(measure_dir, seed, tmp_path / "work")
    finally:
        shutil.rmtree(measure_dir, ignore_errors=True)

    assert facts["measure_ran"] is True, facts.get("cli_stderr_tail")
    assert facts["completed_status"] == "Success"
    result = facts["result_model"]
    beams = sum(n for loop in result["air_loops"]
                for cls, n in loop["terminals"].items() if "FourPipeBeam" in cls)
    vav = sum(n for loop in result["air_loops"]
              for cls, n in loop["terminals"].items() if "VAV" in cls)
    assert beams == 10, f"expected 10 FourPipeBeam terminals, got {beams}"
    assert vav == 0, f"expected 0 VAV terminals after replacement, got {vav}"
    assert result["n_zones_on_air_loops"] == 10, "zones lost their air loop"
    assert verdict["outcome_pass"] is True, verdict["reasons"]


@pytest.mark.integration
def test_measure_grader_partial_replacement_fails(tmp_path):
    # Regression: routing-only grading passed syntax-valid partial measures;
    # a Success run that replaces 1/10 terminals must fail gate 2 with counts
    seed = _sys7_seed(tmp_path)
    name = f"grader_partial_{uuid.uuid4().hex[:8]}"
    measure_dir = _authored_measure(name, PARTIAL_RUBY)
    try:
        facts, verdict = _apply_and_grade(measure_dir, seed, tmp_path / "work")
    finally:
        shutil.rmtree(measure_dir, ignore_errors=True)

    assert facts["measure_ran"] is True, facts.get("cli_stderr_tail")
    assert verdict["outcome_pass"] is False
    assert any("expected 10 FourPipeBeam terminals, got 1" in r
               for r in verdict["reasons"]), verdict["reasons"]
    assert any("9 VAV terminals remain" in r
               for r in verdict["reasons"]), verdict["reasons"]


def _baseline_saved(tmp_path, dirname):
    import openstudio

    from mcp_server.skills.model_management.baseline_model import (
        create_baseline_model,
    )
    model, _info = create_baseline_model(name=f"grader-{dirname}")
    osm = tmp_path / dirname / "model.osm"
    osm.parent.mkdir(parents=True)
    model.save(openstudio.toPath(str(osm)), True)
    return osm


@pytest.mark.integration
def test_ems_grader_setback_plugin_passes(tmp_path):
    # Validates: ems_sim grader measures the ACTUAL night/day thermostat
    # setpoints from EnergyPlus — a correct 15.6-outside-6-18 schedule_override
    # plugin passes L2, and the sim runs on a weatherless baseline copy
    # Plugin creation enforces the session write-area guard — the model must
    # live under user_run_root(), not pytest tmp
    import openstudio

    from mcp_server import model_manager
    from mcp_server.config import user_run_root
    from mcp_server.skills.model_management.baseline_model import (
        create_baseline_model,
    )
    from mcp_server.skills.python_ems.operations import create_python_plugin_op
    base = user_run_root() / f"grader-ems-{uuid.uuid4().hex[:8]}"
    base.mkdir(parents=True)
    osm = base / "model.osm"
    try:
        model, _info = create_baseline_model(name="grader-ems-good")
        model.save(openstudio.toPath(str(osm)), True)
        model_manager.load_model(osm)
        result = create_python_plugin_op(
            name="grader_setback", template="schedule_override",
            schedule_name="Heating Sch",
            rules=[
                {"days": "all", "start_hour": 0, "end_hour": 6, "value": 15.6},
                {"days": "all", "start_hour": 18, "end_hour": 24, "value": 15.6},
            ],
            default_value=21.1)
        assert result["ok"] is True, (
            f"plugin creation failed: {result.get('error')}")
        model_manager.save_model()
        model_manager.clear_model()

        facts = container_grader.ems_sim_mode(argparse.Namespace(
            osm=str(osm), work=str(tmp_path / "work"),
            epw=container_grader.EPW))
    finally:
        model_manager.clear_model()
        shutil.rmtree(base, ignore_errors=True)
    assert facts["sim_ran"] is True, facts
    stats = facts["setpoint_stats"]
    assert len(stats) == 10, f"expected setpoint series for 10 zones: {list(stats)}"
    for zone, buckets in stats.items():
        assert buckets["night"]["mean"] == pytest.approx(15.6, abs=0.05), (
            f"{zone} night setback not measured")
        assert buckets["day"]["mean"] == pytest.approx(21.1, abs=0.05), (
            f"{zone} day setpoint drifted")
    verdict = rubric.evaluate("python_ems_control", "L2", facts)
    assert verdict["outcome_pass"] is True, verdict["reasons"]


@pytest.mark.integration
def test_ems_grader_flat_baseline_fails(tmp_path):
    # Regression: routing-only grading passed plugins that never changed the
    # setpoint — a plugin-less model reads flat 21.1 and must fail L1 and L2
    osm = _baseline_saved(tmp_path, "ems-flat")
    facts = container_grader.ems_sim_mode(argparse.Namespace(
        osm=str(osm), work=str(tmp_path / "work"), epw=container_grader.EPW))
    assert facts["sim_ran"] is True, facts
    assert facts["python_plugins"] == []
    l2 = rubric.evaluate("python_ems_control", "L2", facts)
    assert l2["outcome_pass"] is False
    assert any("night mean 21.1" in r for r in l2["reasons"]), l2["reasons"]
    l1 = rubric.evaluate("python_ems_control", "L1", facts)
    assert l1["outcome_pass"] is False
    assert any("no setback" in r for r in l1["reasons"]), l1["reasons"]


@pytest.mark.integration
def test_inspect_mode_reports_sys7_facts(tmp_path):
    # Validates: inspect mode's generic dump carries the exact fields the
    # rubric consumes (terminal classes, zones-on-loops, plant names)
    seed = _sys7_seed(tmp_path)
    facts = container_grader.inspect_mode(argparse.Namespace(
        osm=str(seed), baseline=None))
    assert facts["load_ok"] is True
    model = facts["model"]
    assert model["n_thermal_zones"] == 10
    assert model["n_zones_on_air_loops"] == 10
    terminals = model["air_loops"][0]["terminals"]
    assert sum(n for cls, n in terminals.items() if "VAV" in cls) == 10, terminals
    plants = [p.lower() for p in model["plant_loops"]]
    assert any("hot water" in p for p in plants), plants
    assert any("chilled" in p for p in plants), plants
