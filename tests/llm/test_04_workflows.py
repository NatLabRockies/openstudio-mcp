"""Tier 2: Multi-step workflow tests — load saved model, perform actions.

Each test loads the baseline model from test_01_setup, then performs a
specific action (add HVAC, set weather, delete object, etc.). This tests
the agent's ability to chain multiple MCP tools in the right sequence.

Design:
  - All cases use LOAD prefix to load the saved baseline model
  - Prompts include explicit tool names to minimize ambiguity
  - required_tools are ALL checked (every one must appear in the sequence)
  - any_of is used when multiple tools can achieve the same goal
    (e.g. set_weather_file OR change_building_location for Chicago weather)
  - Timeouts are per-case; adjust_thermostat gets 180s because applying
    measures to all zones is slow

Assumptions:
  - test_01_setup has run and saved a model at BASELINE_MODEL
  - Each test starts a fresh Docker container (no shared model state
    between tests — model is loaded fresh each time)
  - The agent may call context-gathering tools (list_thermal_zones,
    get_building_info) before the required tools — this is expected
  - Tool ordering within required_tools is NOT enforced (load_osm_model
    should come first, but we don't check order)
"""
from __future__ import annotations

import pytest

from .conftest import BASELINE_MODEL, get_tier
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier2]

LOAD = f"Load the model at {BASELINE_MODEL} using load_osm_model. Then "

WORKFLOW_CASES = [
    {
        # Add ASHRAE System 7 (VAV with reheat) — the most common baseline system
        "id": "add_vav_reheat",
        "prompt": LOAD + (
            "add System 7 VAV reheat to all zones using add_baseline_system. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "add_baseline_system"],
        "timeout": 120,
    },
    {
        # Add Dedicated Outdoor Air System with fan coils
        "id": "add_doas",
        "prompt": LOAD + (
            "add a DOAS system with fan coils using add_doas_system. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "add_doas_system"],
        "timeout": 120,
    },
    {
        # Add Variable Refrigerant Flow system
        "id": "add_vrf",
        "prompt": LOAD + (
            "add a VRF system using add_vrf_system. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "add_vrf_system"],
        "timeout": 120,
    },
    {
        # Set weather — two tools can do this (set_weather_file is native,
        # change_building_location is a measure wrapper)
        "id": "set_weather",
        "prompt": LOAD + (
            "set the weather to Chicago using set_weather_file or "
            "change_building_location. Use MCP tools only."
        ),
        "required_tools": ["load_osm_model"],
        "any_of": ["set_weather_file", "change_building_location"],
        "timeout": 120,
    },
    {
        # Add rooftop PV panels via the common_measures wrapper
        "id": "add_rooftop_pv",
        "prompt": LOAD + (
            "add rooftop solar panels using add_rooftop_pv. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "add_rooftop_pv"],
        "timeout": 120,
    },
    {
        # Adjust thermostat setpoints — applies a measure to all zones
        # which can be slow (180s timeout). Explicit F values prevent
        # the agent from asking clarifying questions.
        "id": "adjust_thermostat",
        "prompt": LOAD + (
            "adjust the thermostat setpoints using adjust_thermostat_setpoints. "
            "Set heating to 70F and cooling to 75F. Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "adjust_thermostat_setpoints"],
        "timeout": 180,
    },
    {
        # Delete an object — tests list-then-delete pattern.
        # Agent must list spaces first to get a name, then delete one.
        "id": "delete_space",
        "prompt": LOAD + (
            "list the spaces, then delete one using delete_object. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "delete_object"],
        "timeout": 120,
    },
    {
        # Run QA/QC checks — tests the common_measures wrapper
        "id": "qaqc_check",
        "prompt": LOAD + (
            "run QA/QC checks using run_qaqc_checks. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "run_qaqc_checks"],
        "timeout": 120,
    },
]


@pytest.mark.parametrize("case", WORKFLOW_CASES, ids=[c["id"] for c in WORKFLOW_CASES])
def test_workflow(case):
    """Agent loads model and completes a multi-step workflow.

    Verifies:
      1. ALL required_tools appear in the tool call sequence
      2. If any_of is specified, at least one of those tools appears
      3. Tool ordering is NOT enforced (only presence)

    Assumptions:
      - Agent may call extra tools (context-gathering) — that's fine
      - Each test is independent (fresh Docker container per claude -p call)
      - Retries handle LLM non-determinism (conftest MAX_RETRIES)
    """
    tier = get_tier()
    if tier not in ("all", "2"):
        pytest.skip("Tier 2 not selected")

    result = run_claude(case["prompt"], timeout=case.get("timeout", 120))
    tool_names = result.tool_names

    for tool in case["required_tools"]:
        assert tool in tool_names, (
            f"Required tool '{tool}' not found. Tools: {tool_names}"
        )

    if "any_of" in case:
        assert any(t in tool_names for t in case["any_of"]), (
            f"None of {case['any_of']} found. Tools: {tool_names}"
        )
