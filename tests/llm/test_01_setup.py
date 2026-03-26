"""Tier 0: Setup — create and save models for downstream tests.

These run first (alphabetical ordering guarantees test_01 before test_02+).
They create baseline and example models and save them to /runs/ so Tier 2+
tests can load them without redundant model creation.

Model paths (Docker-internal, shared via /runs volume mount):
  /runs/examples/llm-test-baseline/baseline_model.osm — 10-zone baseline office
  /runs/examples/llm-test-example/example_model.osm   — example SEB model

Dependency chain:
  test_01_setup (create models) → test_02+ (load models)

These tests are marked tier1 so they always run with tool selection tests.
Prompts include explicit tool names to minimize non-determinism — the agent
should call exactly these tools, not discover alternatives.
"""
from __future__ import annotations

import pytest

import re

from .conftest import BASELINE_MODEL, save_retrofit_run_id, save_sim_run_id
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier1]


def test_create_baseline_model():
    """Create a 10-zone baseline model and save it for later tests."""
    # Validates: Claude uses create_baseline_osm (not create_example_osm or raw IDF) for baseline models
    result = run_claude(
        "Create a baseline building named 'llm-test-baseline' using "
        "create_baseline_osm. Use MCP tools only.",
        timeout=120,
    )

    tool_names = result.tool_names
    assert "create_baseline_osm" in tool_names, (
        f"create_baseline_osm not called. Tools: {tool_names}"
    )

    assert not result.is_error, f"Claude reported error: {result.final_text}"


def test_create_baseline_with_hvac():
    """Create baseline + System 7 HVAC for component inspection tests."""
    # Validates: Claude uses create_baseline_osm with ashrae_sys_num for HVAC-equipped baseline
    result = run_claude(
        "Create a baseline building named 'llm-test-baseline-hvac' using "
        "create_baseline_osm with ashrae_sys_num '07'. Use MCP tools only.",
        timeout=120,
    )
    assert "create_baseline_osm" in result.tool_names, (
        f"create_baseline_osm not called. Tools: {result.tool_names}"
    )
    assert not result.is_error, f"Claude reported error: {result.final_text}"


def test_create_example_model():
    """Create an example SEB model for later tests."""
    # Validates: Claude uses create_example_osm (or create_baseline_osm) for example models
    result = run_claude(
        "Create an example model named 'llm-test-example' using create_example_osm. "
        "Use MCP tools only.",
        timeout=120,
    )

    tool_names = result.tool_names
    assert any(t in ("create_example_osm", "create_baseline_osm") for t in tool_names), (
        f"No creation tool called. Tools: {tool_names}"
    )
    assert not result.is_error, f"Claude reported error: {result.final_text}"


def test_load_baseline_model():
    """Verify the saved baseline model can be loaded and queried."""
    # Validates: Claude uses load_osm_model + list_thermal_zones to load and inspect saved models
    result = run_claude(
        f"Load the model at {BASELINE_MODEL} using load_osm_model, "
        "then tell me how many thermal zones it has using list_thermal_zones.",
        timeout=90,
    )

    tool_names = result.tool_names
    assert "load_osm_model" in tool_names, (
        f"load_osm_model not called. Tools: {tool_names}"
    )
    assert "list_thermal_zones" in tool_names, (
        f"list_thermal_zones not called. Tools: {tool_names}"
    )


def test_run_baseline_simulation():
    """Set weather and run simulation on the baseline model, save run_id."""
    # Validates: Claude chains load → weather → run_simulation → get_run_status for full sim workflow
    boston_epw = (
        "/opt/comstock-measures/ChangeBuildingLocation"
        "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
    )
    result = run_claude(
        f"Load the model at {BASELINE_MODEL} using load_osm_model. "
        f"Then set the weather using change_building_location with "
        f"weather_file {boston_epw}. "
        "Then run a simulation using run_simulation. "
        "Wait for it to complete by checking get_run_status. "
        "Report the run_id when done.",
        timeout=420,
        max_turns=20,
    )

    tool_names = result.tool_names
    assert "run_simulation" in tool_names, (
        f"run_simulation not called. Tools: {tool_names}"
    )

    # Extract run_id from the tool call inputs
    run_id = None
    for call in result.mcp_tool_calls:
        if call["tool"].endswith("run_simulation"):
            # run_simulation returns the run_id
            continue
        if call["tool"].endswith("get_run_status"):
            run_id = call["input"].get("run_id", "")
            break

    # Also try to extract from the final text (agent usually reports it)
    if not run_id:
        match = re.search(r"sim_[a-f0-9]{12}", result.final_text)
        if match:
            run_id = match.group(0)

    if run_id:
        save_sim_run_id(run_id)

    assert not result.is_error, f"Simulation failed: {result.final_text}"


def test_run_retrofit_simulation():
    """Run a modified simulation (thermostat +2F cooling) for compare_runs tests."""
    # Validates: Claude chains load → weather → adjust_thermostat → run_simulation for retrofit workflow
    boston_epw = (
        "/opt/comstock-measures/ChangeBuildingLocation"
        "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
    )
    result = run_claude(
        f"Load the model at {BASELINE_MODEL} using load_osm_model. "
        f"Then set the weather using change_building_location with "
        f"weather_file {boston_epw}. "
        "Then adjust thermostat setpoints using adjust_thermostat_setpoints "
        "with cooling_offset 2. "
        "Then run a simulation using run_simulation. "
        "Wait for it to complete by checking get_run_status. "
        "Report the run_id when done.",
        timeout=420,
        max_turns=20,
    )

    tool_names = result.tool_names
    assert "run_simulation" in tool_names, (
        f"run_simulation not called. Tools: {tool_names}"
    )

    # Extract run_id from tool call inputs
    run_id = None
    for call in result.mcp_tool_calls:
        if call["tool"].endswith("get_run_status"):
            run_id = call["input"].get("run_id", "")
            break

    # Fallback: extract from final text
    if not run_id:
        match = re.search(r"sim_[a-f0-9]{12}", result.final_text)
        if match:
            run_id = match.group(0)

    if run_id:
        save_retrofit_run_id(run_id)

    assert not result.is_error, f"Retrofit simulation failed: {result.final_text}"
