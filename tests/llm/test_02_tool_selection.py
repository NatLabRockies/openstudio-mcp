"""Tier 1: Tool selection tests — verify Claude picks the right MCP tools.

These are hand-crafted query/info prompts that load the saved baseline
model first (from test_01_setup), then ask a specific question. Each test
checks that the agent calls at least one of the expected query tools.

Design:
  - All with-model cases use LOAD prefix to load the saved baseline model
  - Prompts are explicit (e.g. "list the spaces") to minimize ambiguity
  - Each case lists 1-2 acceptable tools (e.g. both get_building_info and
    get_model_summary are valid for "floor area")
  - Tool ordering is NOT checked — only presence in the full call sequence
  - NO_MODEL_CASES test tools that work without model state (server info, skills)

Assumptions:
  - test_01_setup has run and saved a model at BASELINE_MODEL
  - ToolSearch (deferred tool loading) consumes 1-3 turns before MCP tools
  - Agent may call context-gathering tools beyond the expected ones
  - 120s timeout is enough for query operations (no simulation)
"""
from __future__ import annotations

import pytest

from .conftest import BASELINE_MODEL, get_tier
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier1]

# Prompt prefix that loads the saved model — used by all with-model cases
LOAD = f"First load the model at {BASELINE_MODEL} using load_osm_model. Then "

# (prompt_suffix, acceptable MCP tools)
# Each case tests that the agent picks a reasonable tool for the query.
# Multiple acceptable tools handle cases where different tools can
# answer the same question (e.g. get_building_info vs get_model_summary).
TOOL_SELECTION_CASES = [
    ("list all the spaces",
     ["list_spaces"]),
    ("tell me the building floor area",
     ["get_building_info", "get_model_summary"]),
    ("show me a 3D view of the model",
     ["view_model"]),
    ("list the HVAC baseline systems available",
     ["list_baseline_systems", "get_baseline_system_info"]),
    ("list the materials in the model",
     ["list_materials"]),
    ("list the thermal zones",
     ["list_thermal_zones"]),
    ("list the schedules",
     ["list_schedule_rulesets"]),
    # Explicit tool name in prompt to test direct tool invocation
    ("check the model for issues using run_qaqc_checks",
     ["run_qaqc_checks", "inspect_osm_summary"]),
]

# Cases that don't need a model loaded — tests tool discovery and server info
NO_MODEL_CASES = [
    ("What is the server status?",
     ["get_server_status"]),
    ("List available skills",
     ["list_skills"]),
]


@pytest.mark.parametrize(("suffix", "expected"), TOOL_SELECTION_CASES,
                         ids=[c[0][:35] for c in TOOL_SELECTION_CASES])
def test_tool_selection_with_model(suffix, expected):
    """Agent loads model then calls expected query tool.

    Verifies:
      1. load_osm_model is called (model must be loaded before querying)
      2. At least one expected tool appears in the tool call sequence

    Does NOT verify tool ordering or that the expected tool is the first
    MCP call — the agent may call context-gathering tools first.
    """
    tier = get_tier()
    if tier not in ("all", "1"):
        pytest.skip("Tier 1 not selected")

    result = run_claude(LOAD + suffix, timeout=120)
    tool_names = result.tool_names

    assert "load_osm_model" in tool_names, (
        f"load_osm_model not called. Tools: {tool_names}"
    )
    assert any(t in expected for t in tool_names), (
        f"Expected one of {expected} in sequence, got: {tool_names}"
    )


@pytest.mark.parametrize(("prompt", "expected"), NO_MODEL_CASES,
                         ids=[c[0][:35] for c in NO_MODEL_CASES])
def test_tool_selection_no_model(prompt, expected):
    """Agent calls expected tool without needing model state.

    Verifies:
      - At least one expected tool appears in the tool call sequence
      - No model loading needed (these tools work without model state)
    """
    tier = get_tier()
    if tier not in ("all", "1"):
        pytest.skip("Tier 1 not selected")

    result = run_claude(prompt, timeout=90)
    tool_names = result.tool_names

    assert any(t in expected for t in tool_names), (
        f"Expected one of {expected} in sequence, got: {tool_names}"
    )
