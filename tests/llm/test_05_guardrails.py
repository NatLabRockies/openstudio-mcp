"""Tier 4: Guardrail regression tests — agent must prefer MCP tools.

These tests verify the agent uses MCP tools for building energy modeling tasks.
The original motivation was catching an agent that bypassed all MCP tools and
wrote raw IDF files. The key assertion is: the agent USED the correct MCP tool,
not that it avoided all built-in tools.

Design:
  - CREATION_TOOLS are the valid MCP tools for model creation.
  - The primary check is: did the agent call a correct MCP tool?
  - Secondary check: no raw IDF content in the response text.
  - Built-in tool usage (Bash, Read) alongside MCP tools is acceptable —
    the agent might inspect results or check files. What matters is that
    the BEM work was done via MCP, not via scripts or raw file writes.

Assumptions:
  - test_01_setup has run for test_no_script_for_results (needs BASELINE_MODEL)
  - 180s timeout for creation test (create_baseline_osm takes 30-60s,
    plus ToolSearch overhead)
  - tool_names only includes MCP tools (prefix stripped)
"""
from __future__ import annotations

import pytest

from .conftest import BASELINE_MODEL, get_tier
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier4]

# Valid MCP tools for model creation — agent must use one of these
CREATION_TOOLS = {"create_baseline_osm", "create_example_osm",
                  "create_typical_building", "create_bar_building",
                  "create_new_building", "import_floorspacejs"}

# Valid MCP tools for extracting results
RESULTS_TOOLS = {"extract_summary_metrics", "extract_end_use_breakdown",
                 "extract_envelope_summary", "extract_hvac_sizing",
                 "extract_zone_summary", "extract_component_sizing",
                 "query_timeseries", "read_run_artifact",
                 "generate_results_report"}

LOAD = f"Load the model at {BASELINE_MODEL} using load_osm_model. Then "


def test_create_uses_mcp_not_raw_idf():
    """Agent must use MCP tools to create a building, not write raw IDF.

    Verifies:
      1. A valid MCP creation tool was called (primary check)
      2. The response text doesn't contain raw IDF snippets
    """
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    result = run_claude(
        "Create a simple office building model. Use MCP tools only.",
        timeout=180,
    )

    # 1. Must use MCP creation tool
    assert any(t in CREATION_TOOLS for t in result.tool_names), (
        f"No MCP creation tool used. MCP tools: {result.tool_names}"
    )

    # 2. No raw IDF in response text — catches agent outputting EnergyPlus input
    text = result.final_text.lower()
    idf_markers = ["!- name", "!- north axis", "globalgeometryrules",
                    "buildingsurface:detailed"]
    for marker in idf_markers:
        assert marker not in text, (
            f"Response contains IDF marker '{marker}'"
        )


def test_no_script_for_results():
    """Agent must use MCP tools to extract results, not write scripts.

    Verifies the agent calls an MCP extraction tool rather than writing
    a Python/Ruby script to parse EnergyPlus SQL output.
    """
    tier = get_tier()
    if tier not in ("all", "4"):
        pytest.skip("Tier 4 not selected")

    result = run_claude(
        LOAD + "extract the EUI using extract_summary_metrics. "
        "Use MCP tools only, do not write any scripts.",
        timeout=120,
    )

    # Must call an MCP results extraction tool
    assert any(t in RESULTS_TOOLS for t in result.tool_names), (
        f"No MCP results tool used. MCP tools: {result.tool_names}"
    )
