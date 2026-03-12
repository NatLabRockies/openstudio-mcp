"""Tier 1 tests auto-generated from eval.md files.

Parses "should trigger" tables from 8 skill eval.md files
(.claude/skills/<skill>/eval.md). Each row maps a natural-language prompt
to one or more expected MCP tool names.

Key design decisions:
  - Skills in NEEDS_MODEL get a load prefix prepended so the agent has
    model state. Without this, the agent wastes turns creating a model.
  - EXTRA_EXPECTED supplements eval.md expected tools with tools that are
    reasonable context-gathering responses (e.g. list_thermal_zones before
    adding HVAC). This prevents false failures when the agent does useful
    work but doesn't reach the exact target tool within the turn limit.
  - SLOW_SKILLS get 180s timeout instead of 120s because model creation
    operations (create_baseline_osm) take 30-60s each.
  - Wildcard tool names (e.g. "add_*_system") are filtered out at import
    since we can't match them reliably.
  - All prompts get " Use MCP tools only." appended to discourage the
    agent from writing scripts or raw files.
"""
from __future__ import annotations

import pytest

from .conftest import BASELINE_MODEL, baseline_model_exists, get_sim_run_id, get_tier
from .eval_parser import load_should_trigger
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier1]

# Prompts too vague or too complex for single-turn testing.
# Vague prompts: agent consults skill guides but doesn't act within timeout.
# Complex prompts: multi-step workflows (replace → simulate → compare)
# that need more turns than a single `claude -p` invocation provides.
# These work in interactive mode but not in automated single-prompt testing.
SKIP_PROMPTS = {
    "Build me a new model from scratch",
    "Start a new building energy model",
    "What energy savings from better windows?",
    # Prompt says "with weather" but no weather_file path — agent can't guess
    "Create a complete building with weather",
}

# Load cases at import time; filter out wildcard tool names and skip-listed prompts
EVAL_CASES = [
    c for c in load_should_trigger()
    if all("*" not in t for t in c["expected_tools"])
    and c["prompt"] not in SKIP_PROMPTS
]

# Skills whose prompts need a loaded model to be meaningful.
# Without model state, the agent wastes turns on creation instead of
# exercising the target tool.
NEEDS_MODEL = {"add-hvac", "simulate", "energy-report", "retrofit",
               "qaqc", "troubleshoot", "view"}

LOAD_PREFIX = (
    f"First load the model at {BASELINE_MODEL} using load_osm_model. Then "
)

def _troubleshoot_prefix() -> str:
    """Build a prompt prefix for troubleshoot tests, including run_id if available."""
    run_id = get_sim_run_id()
    if run_id:
        return (
            f"First load the model at {BASELINE_MODEL} using load_osm_model. "
            f"A simulation was run with run_id '{run_id}'. "
        )
    return (
        f"First load the model at {BASELINE_MODEL} using load_osm_model. "
        "A simulation was run previously. Look for simulation runs in /runs. "
    )

# Extra acceptable tools beyond what eval.md lists.
# The agent often does context-gathering before reaching the "target" tool.
# These represent valid agent behaviors that shouldn't count as failures.
# Example: "Add HVAC to the model" → agent calls list_thermal_zones first
# to understand zone layout, then adds HVAC. Both are correct behavior.
EXTRA_EXPECTED = {
    # Agent may inspect model before adding HVAC, or pick a different system type
    "add-hvac": ["list_baseline_systems", "get_baseline_system_info",
                 "add_doas_system", "add_vrf_system", "add_radiant_system",
                 "get_building_info", "list_thermal_zones", "list_air_loops"],
    # inspect_osm_summary is a valid QA/QC approach alongside run_qaqc_checks
    "qaqc": ["inspect_osm_summary", "run_qaqc_checks", "get_model_summary"],
    # Troubleshooting may involve inspecting model state, not just reading logs.
    # Agent may use list_files to discover runs, run_simulation to reproduce,
    # or inspect_osm_summary/get_building_info for pre-sim diagnostics.
    "troubleshoot": ["get_run_status", "get_run_logs", "extract_summary_metrics",
                     "extract_component_sizing", "get_model_summary",
                     "list_thermal_zones", "list_files", "inspect_osm_summary",
                     "get_building_info", "run_simulation"],
    # Retrofit analysis involves many intermediate steps (inspect envelope,
    # list constructions, etc.) — any of these is valid progress
    "retrofit": ["save_osm_model", "run_simulation", "extract_summary_metrics",
                 "replace_window_constructions", "list_model_objects",
                 "extract_envelope_summary"],
    # "Full energy report" can be answered by generate_results_report (single HTML)
    # or by individual extract_* tools — both are valid
    "energy-report": ["generate_results_report"],
    # Agent may use create_typical_building (ComStock) instead of create_baseline_osm,
    # or build from scratch using geometry tools (create_space_from_floor_print,
    # create_thermal_zone, etc.) — all are valid creation approaches
    "new-building": ["create_typical_building", "create_example_osm",
                     "create_space_from_floor_print", "create_thermal_zone",
                     "create_space"],
}

# Skills that need longer timeout because their tools involve heavyweight
# operations (model creation ~30-60s, simulation ~60-120s)
SLOW_SKILLS = {"new-building": 180, "retrofit": 180}

# Appended to all prompts to discourage raw file/script creation
SUFFIX = " Use MCP tools only."


def _case_id(case: dict) -> str:
    return f"{case['skill']}:{case['prompt'][:35]}"


@pytest.mark.parametrize("case", EVAL_CASES, ids=[_case_id(c) for c in EVAL_CASES])
def test_eval_tool_selection(case):
    """Verify agent calls at least one expected MCP tool for an eval.md prompt.

    This test does NOT assert tool ordering — the agent may call tools in
    any order. It only checks that at least one tool from the expected set
    (eval.md + EXTRA_EXPECTED) appears in the full tool call sequence.

    Assumptions:
      - Agent has MCP tools available via --allowedTools "mcp__openstudio__*"
      - For NEEDS_MODEL skills, model is pre-loaded via LOAD_PREFIX
      - ToolSearch (deferred loading) consumes 1-3 turns before MCP tools
      - Agent may call context-gathering tools before the target tool
      - Retries (conftest MAX_RETRIES) handle LLM non-determinism
    """
    tier = get_tier()
    if tier not in ("all", "1"):
        pytest.skip("Tier 1 not selected")

    # Prepend model load for skills that need model state
    prompt = case["prompt"]
    if case["skill"] in NEEDS_MODEL:
        if not baseline_model_exists():
            pytest.skip("Baseline model not found — run test_01_setup first")
        if case["skill"] == "troubleshoot":
            prompt = _troubleshoot_prefix() + prompt.lower()
        else:
            prompt = LOAD_PREFIX + prompt.lower()
    prompt += SUFFIX

    timeout = SLOW_SKILLS.get(case["skill"], 120)
    result = run_claude(prompt, timeout=timeout)
    tool_names = result.tool_names

    # Merge eval.md expected tools with extra acceptable tools
    expected = set(case["expected_tools"])
    expected.update(EXTRA_EXPECTED.get(case["skill"], []))

    assert any(t in expected for t in tool_names), (
        f"[{case['skill']}] Expected one of {sorted(expected)}, "
        f"got: {tool_names}"
    )
