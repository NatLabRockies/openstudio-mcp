"""LLM A/B tests for tool routing — does reduced context improve selection?

Baseline tests (all 139 tools) run now to capture current state.
After Phase 3, re-run with recommend_tools to compare.

Also extends guardrail coverage for visualization, reports, and measures.

Requires LLM_TESTS_ENABLED=1, not in CI.
"""
from __future__ import annotations

import pytest

from .conftest import (
    BASELINE_MODEL, get_sim_run_id, get_tier,
)
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier4]

LOAD = f"Load the model at {BASELINE_MODEL} using load_osm_model. Then "

# ── A/B test cases ───────────────────────────────────────────────────────
# (case_id, prompt, expected_mcp_tool)

AB_CASES = [
    ("create_measure",
     "Create a Ruby measure that sets all lights to 8 W/m2",
     "create_measure"),
    ("view_model",
     "Show me a 3D view of the model",
     "view_model"),
    ("read_file",
     "Read the warnings in /inputs/eplusout.err",
     "read_file"),
    ("add_baseline_system",
     "Add System 7 VAV reheat to all zones",
     "add_baseline_system"),
]


@pytest.mark.parametrize(
    "case_id,prompt,expected",
    AB_CASES,
    ids=[c[0] for c in AB_CASES],
)
def test_tool_selection_baseline(case_id, prompt, expected):
    """Baseline: all tools available. Record pass/fail + tokens."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    # Some prompts need model loaded first
    full_prompt = prompt + ". Use MCP tools only."
    if expected in ("add_baseline_system",):
        full_prompt = LOAD + prompt.lower() + ". Use MCP tools only."

    result = run_claude(full_prompt, timeout=180)

    assert expected in result.tool_names, (
        f"Expected '{expected}' in tool_names, got: {result.tool_names}"
    )


def test_tool_selection_baseline_extract_eui():
    """Baseline: extract EUI with all tools available."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    run_id = get_sim_run_id()
    if run_id:
        prompt = (
            f"What's the total site EUI from run {run_id}? "
            "Use MCP tools only."
        )
    else:
        prompt = (
            LOAD + "extract the EUI using extract_summary_metrics. "
            "Use MCP tools only."
        )

    result = run_claude(prompt, timeout=120)
    assert "extract_summary_metrics" in result.tool_names, (
        f"Expected extract_summary_metrics, got: {result.tool_names}"
    )


# ── Guardrail bypass tests ──────────────────────────────────────────────

# Valid MCP tools for visualization
VIZ_TOOLS = {"view_model", "view_simulation_data"}


def test_visualization_uses_mcp_not_script():
    """Must use view_model/view_simulation_data, not matplotlib/plotly."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    result = run_claude(
        LOAD + "show me a 3D visualization of the building. "
        "Use MCP tools only.",
        timeout=120,
    )
    assert any(t in VIZ_TOOLS for t in result.tool_names), (
        f"No MCP viz tool used. Tools: {result.tool_names}"
    )


def test_report_uses_mcp_not_script():
    """Must use generate_results_report, not Python/HTML scripting."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    run_id = get_sim_run_id()
    if not run_id:
        pytest.skip("No simulation run_id — run test_01_setup first")

    result = run_claude(
        f"Generate a comprehensive report from simulation run '{run_id}'. "
        "Use MCP tools only.",
        timeout=120,
    )
    assert "generate_results_report" in result.tool_names, (
        f"Expected generate_results_report, got: {result.tool_names}"
    )


def test_measure_uses_create_measure_not_create_file():
    """Must use create_measure, not write measure.rb directly."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    result = run_claude(
        "Write a Ruby OpenStudio measure that sets all lights to 8 W/m2. "
        "Use MCP tools only.",
        timeout=120,
    )
    assert "create_measure" in result.tool_names, (
        f"Expected create_measure, got: {result.tool_names}"
    )


# ── FM3 file access test ────────────────────────────────────────────────

def test_read_file_uses_mcp_not_bash():
    """LLM must use MCP read_file for /inputs paths, not bash."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    result = run_claude(
        "Read the file at /inputs/eplusout.err and count the warnings. "
        "Use MCP tools only.",
        timeout=120,
    )
    assert "read_file" in result.tool_names, (
        f"Expected read_file, got: {result.tool_names}"
    )


# ── API reference tool discovery ─────────────────────────────────────────

# Valid tools the agent might call to research before authoring
API_REFERENCE_TOOLS = {"search_api", "search_wiring_patterns", "get_skill"}


def test_hvac_measure_uses_api_reference():
    """Agent should call search_api or search_wiring_patterns when authoring
    an HVAC measure that requires wiring components to loops.

    This is aspirational — the agent may or may not discover these tools.
    We check that it at least calls create_measure (primary) and ideally
    also calls a reference tool (secondary).
    """
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    result = run_claude(
        "Write a Ruby measure that replaces all zone terminals with "
        "four-pipe beam terminals. The measure should create "
        "CoilCoolingFourPipeBeam and CoilHeatingFourPipeBeam coils, "
        "connect them to the chilled water and hot water plant loops, "
        "and wire them into AirTerminalSingleDuctConstantVolumeFourPipeBeam. "
        "Before writing the measure code, verify the API methods exist. "
        "Use MCP tools only.",
        timeout=300,
    )

    # Primary: must use create_measure
    assert "create_measure" in result.tool_names, (
        f"Expected create_measure, got: {result.tool_names}"
    )

    # Secondary: check if agent used any reference tool (informational)
    used_reference = any(t in API_REFERENCE_TOOLS for t in result.tool_names)
    if not used_reference:
        print(f"NOTE: Agent did not call search_api/search_wiring_patterns. "
              f"Tools used: {result.tool_names}")


def test_search_api_for_method_verification():
    """Agent should call search_api when asked to verify methods exist."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    result = run_claude(
        "What setter methods are available on CoilCoolingFourPipeBeam? "
        "Use the search_api tool to find out. Use MCP tools only.",
        timeout=120,
    )

    assert "search_api" in result.tool_names, (
        f"Expected search_api, got: {result.tool_names}"
    )


def test_search_wiring_patterns_for_hvac_wiring():
    """Agent should call search_wiring_patterns when asked about wiring."""
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    result = run_claude(
        "How do I wire a CoilCoolingFourPipeBeam to a chilled water plant "
        "loop and an air terminal? Use the search_wiring_patterns tool to "
        "find the wiring recipe. Use MCP tools only.",
        timeout=120,
    )

    assert "search_wiring_patterns" in result.tool_names, (
        f"Expected search_wiring_patterns, got: {result.tool_names}"
    )
