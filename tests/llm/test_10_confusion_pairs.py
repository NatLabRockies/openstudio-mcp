"""LLM tests for tool confusion pairs — does the agent pick the right tool
when the prompt is ambiguous between two similar tools?

Each test uses a natural language prompt that could go either way,
and asserts the contextually correct tool is chosen.

Requires LLM_TESTS_ENABLED=1, not in CI.
"""
from __future__ import annotations

import pytest

from .conftest import (
    BASELINE_MODEL, BASELINE_HVAC_MODEL,
    baseline_model_exists, baseline_hvac_model_exists,
    get_sim_run_id, get_tier,
)
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier4]

LOAD = f"Load the model at {BASELINE_MODEL} using load_osm_model. Then "
LOAD_HVAC = f"Load the model at {BASELINE_HVAC_MODEL} using load_osm_model. Then "


# ── Confusion pair tests ─────────────────────────────────────────────────
# Each pair has a prompt designed to trigger the CORRECT tool, not the
# confused alternative. If the description guidance works, these pass.

def test_qaqc_vs_validate_post_sim():
    """'Check model quality' after sim → run_qaqc_checks, not validate_model."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    run_id = get_sim_run_id()
    if not run_id:
        pytest.skip("No simulation run_id")

    result = run_claude(
        f"Check the quality of simulation run '{run_id}'. "
        "Are there any ASHRAE compliance issues? Use MCP tools only.",
        timeout=120,
    )
    assert "run_qaqc_checks" in result.tool_names, (
        f"Expected run_qaqc_checks, got: {result.tool_names}"
    )


def test_validate_vs_qaqc_pre_sim():
    """'Is the model ready to simulate?' pre-sim → validate_model, not run_qaqc_checks."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    if not baseline_model_exists():
        pytest.skip("Baseline model not found")

    result = run_claude(
        LOAD + "check if this model is ready to simulate. Does it have "
        "weather, design days, and HVAC? Use MCP tools only.",
        timeout=120,
    )
    valid = {"validate_model", "get_model_summary", "get_building_info",
             "get_weather_info", "list_air_loops"}
    assert any(t in valid for t in result.tool_names), (
        f"Expected validate_model or inspection tools, got: {result.tool_names}"
    )


def test_load_details_vs_space_details():
    """'What are the lighting loads?' → get_load_details, not get_space_details."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    if not baseline_model_exists():
        pytest.skip("Baseline model not found")

    result = run_claude(
        LOAD + "what are the lighting power densities in the building? "
        "Use MCP tools only.",
        timeout=120,
    )
    valid = {"get_load_details", "list_model_objects", "get_object_fields"}
    assert any(t in valid for t in result.tool_names), (
        f"Expected load inspection tool, got: {result.tool_names}"
    )


def test_summary_metrics_vs_end_use():
    """'What is the EUI?' → extract_summary_metrics, not extract_end_use_breakdown."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    run_id = get_sim_run_id()
    if not run_id:
        pytest.skip("No simulation run_id")

    result = run_claude(
        f"What is the EUI for simulation run '{run_id}'? "
        "Use MCP tools only.",
        timeout=120,
    )
    assert "extract_summary_metrics" in result.tool_names, (
        f"Expected extract_summary_metrics, got: {result.tool_names}"
    )


def test_end_use_vs_summary_metrics():
    """'Break down energy by category' → extract_end_use_breakdown, not extract_summary_metrics."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    run_id = get_sim_run_id()
    if not run_id:
        pytest.skip("No simulation run_id")

    result = run_claude(
        f"Show me the energy breakdown by heating, cooling, lighting, "
        f"and equipment for run '{run_id}'. Use MCP tools only.",
        timeout=120,
    )
    assert "extract_end_use_breakdown" in result.tool_names, (
        f"Expected extract_end_use_breakdown, got: {result.tool_names}"
    )


def test_inspect_osm_vs_model_summary():
    """'Preview this OSM file' without loading → inspect_osm_summary."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    result = run_claude(
        f"Give me a quick summary of {BASELINE_MODEL} without loading it. "
        "Use MCP tools only.",
        timeout=120,
    )
    assert "inspect_osm_summary" in result.tool_names, (
        f"Expected inspect_osm_summary, got: {result.tool_names}"
    )


def test_create_baseline_vs_new_building():
    """'Create a real office building' → create_new_building, not create_baseline_osm."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    result = run_claude(
        "Create a 2-story, 20000 sqft small office building in climate "
        "zone 4A with full HVAC and loads. Use MCP tools only.",
        timeout=180,
    )
    assert "create_new_building" in result.tool_names, (
        f"Expected create_new_building, got: {result.tool_names}"
    )


def test_apply_measure_vs_create_measure():
    """'Apply an existing measure' → apply_measure, not create_measure."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    if not baseline_model_exists():
        pytest.skip("Baseline model not found")

    result = run_claude(
        LOAD + "apply the measure at /inputs/measures/"
        "replace_terminals_with_four_pipe_beams using apply_measure. "
        "Use MCP tools only.",
        timeout=120,
    )
    valid = {"apply_measure", "list_measure_arguments"}
    assert any(t in valid for t in result.tool_names), (
        f"Expected apply_measure or list_measure_arguments, got: {result.tool_names}"
    )
