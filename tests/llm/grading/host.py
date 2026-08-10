"""Host-side outcome grading: docker invocation + rubric application.

Called from the LLM tests after the routing gates pass. Spawns the SAME
pinned benchmark image with the leg's /runs and /measures mounts plus
this directory read-only at /grading, runs container_grader.py, and
applies rubric.evaluate to the returned facts. All docker/JSON failures
degrade to {"grader_error": ...} -> rubric verdict "ungradable" (never
raises into the test).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

from . import rubric

GRADING_DIR = Path(__file__).resolve().parent

# Cases with an outcome gate (production 18-case set only; other
# progressive cases stay routing-only — plan-outcome-grading.md).
GRADED_CASES = {
    "create_baseline_model", "create_baseline_with_hvac", "import_floorplan",
    "add_hvac", "python_ems_control", "measure_replace_terminals",
    "zone_equipment_priority", "roof_insulation",
}

# Model-mutation cases whose prompt gets an explicit save-as step (no
# autosave exists; save-as also protects shared fixtures from state leaks).
SAVE_REQUIRED = {
    "import_floorplan", "add_hvac", "python_ems_control",
    "zone_equipment_priority", "roof_insulation",
}

# (case_id, level) pairs with no outcome contract (e.g. no file named in
# the prompt) — graded by routing only.
ROUTING_ONLY = {("import_floorplan", "L1")}

BASELINE_OSM = "/runs/examples/llm-test-baseline/baseline_model.osm"
BASELINE_HVAC_OSM = "/runs/examples/llm-test-baseline-hvac/baseline_model.osm"

_TIMEOUTS = {"inspect": 180, "apply_measure": 480, "ems_sim": 780}


def graded_model_container_path(case_id: str, level: str) -> str:
    return f"/runs/graded_{case_id}_{level}.osm"


def save_instruction(case_id: str, level: str) -> str:
    return (f" Then save the model to "
            f"{graded_model_container_path(case_id, level)} using save_osm_model.")


def _runs_dir() -> str:
    return os.environ.get(
        "LLM_TESTS_RUNS_DIR",
        str(Path(tempfile.gettempdir()) / "llm-test-runs"))


def _measures_dir() -> str:
    return os.environ.get(
        "LLM_TESTS_MEASURES_DIR",
        str(Path(tempfile.gettempdir()) / "llm-test-measures"))


def _image() -> str:
    return os.environ.get("LLM_TESTS_IMAGE", "openstudio-mcp:dev")


def _run_grader(mode: str, grader_args: list[str]) -> dict:
    """Run container_grader.py in the image; return its facts dict."""
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{_runs_dir()}:/runs",
        "-v", f"{_measures_dir()}:/measures:ro",
        "-v", f"{GRADING_DIR}:/grading:ro",
        _image(), "/opt/venv/bin/python", "/grading/container_grader.py",
        "--mode", mode, *grader_args,
    ]
    timeout = _TIMEOUTS[mode]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed docker argv, harness-owned paths
            cmd, capture_output=True, text=True, timeout=timeout, check=False,
            encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"grader_error": f"grader timeout after {timeout}s ({mode})"}
    if proc.returncode != 0:
        return {"grader_error": f"grader rc={proc.returncode}: "
                                f"{proc.stderr[-500:]}"}
    for line in reversed((proc.stdout or "").splitlines()):
        stripped = line.strip()
        if stripped.startswith("{"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
    return {"grader_error": f"no JSON in grader stdout: "
                            f"{(proc.stdout or '')[-300:]}"}


def _dispatch(case_id: str, level: str, measure_name: str | None) -> dict:
    work = f"/runs/grading_{case_id}_{level}"
    if case_id == "create_baseline_model":
        return _run_grader("inspect", ["--osm", BASELINE_OSM])
    if case_id == "create_baseline_with_hvac":
        return _run_grader("inspect", ["--osm", BASELINE_HVAC_OSM])
    if case_id == "measure_replace_terminals":
        if not measure_name:
            return {"measure_ran": False,
                    "error": "no accepted create_measure call with a name"}
        return _run_grader("apply_measure", [
            "--osm", BASELINE_HVAC_OSM, "--work", work,
            "--measure-dir", f"/measures/local/custom/{measure_name}"])
    if case_id == "python_ems_control":
        return _run_grader("ems_sim", [
            "--osm", graded_model_container_path(case_id, level),
            "--work", work])
    if case_id == "roof_insulation":
        return _run_grader("inspect", [
            "--osm", graded_model_container_path(case_id, level),
            "--baseline", BASELINE_OSM])
    # import_floorplan L2, add_hvac, zone_equipment_priority
    return _run_grader("inspect",
                       ["--osm", graded_model_container_path(case_id, level)])


def grade_case(case_id: str, level: str,
               measure_name: str | None = None) -> dict | None:
    """Facts + verdict for one graded row; None when routing-only."""
    if (case_id, level) in ROUTING_ONLY:
        return None
    facts = _dispatch(case_id, level, measure_name)
    verdict = rubric.evaluate(case_id, level, facts)
    if verdict is None:
        return None
    return facts | verdict
