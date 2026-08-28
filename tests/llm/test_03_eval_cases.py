"""Tier 1 tests auto-generated from eval.md files.

Parses "should trigger" tables from skill eval.md files
(.claude/skills/<skill>/eval.md). Each row maps a natural-language prompt
to one or more expected MCP tool names.

Key design decisions:
  - Skills in NEEDS_MODEL get a load prefix prepended so the agent has
    model state. Without this, the agent wastes turns creating a model.
  - EXTRA_EXPECTED supplements eval.md expected tools with tools that are
    reasonable context-gathering responses (e.g. list_thermal_zones before
    adding HVAC). This prevents false failures when the agent does useful
    work but doesn't reach the exact target tool within the turn limit.
  - SLOW_SKILLS get 180s timeout instead of 120s because model creation and
    gbXML import operations can take 30-60s each.
  - Wildcard tool names (e.g. "add_*_system") are filtered out at import
    since we can't match them reliably.
  - All prompts get " Use MCP tools only." appended to discourage the
    agent from writing scripts or raw files.
"""
from __future__ import annotations

import pytest
from doc_contract_lib import load_tool_registry

from .conftest import (
    BASELINE_MODEL,
    EMS_MODEL,
    baseline_model_exists,
    ems_model_exists,
    get_sim_run_id,
    get_tier,
)
from .eval_parser import (
    check_critical_params,
    load_should_not_trigger,
    load_should_trigger,
    normalize_calls,
)
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier1]

# AST-derived tool schemas (pure, no imports) — critical-param assertions
# only apply to expected tools whose schema carries the parameter.
REGISTRY_PARAMS = {
    name: set(sig.params) for name, sig in load_tool_registry().items()
}

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
               "qaqc", "troubleshoot", "view", "attribute-space-types",
               "python-ems"}

# Skills whose target tools need a COMPLETED simulation run_id, not just a
# loaded model (get_run_logs, run_qaqc_checks) — they get the run-id prefix.
NEEDS_RUN_ID = {"troubleshoot", "qaqc"}

LOAD_PREFIX = (
    f"First load the model at {BASELINE_MODEL} using load_osm_model. Then "
)
EMS_LOAD_PREFIX = (
    f"First load the model at {EMS_MODEL} using load_osm_model. Then "
)
SKILL_CONTEXT_PREFIX = {
    "gbxml-import": (
        "The source gbXML is at /inputs/gbxml/25_SpacesOneZE.xml and the "
        "project EPW is at /opt/comstock-measures/ChangeBuildingLocation/tests/"
        "USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw. "
    ),
}
GBXML_MODEL_TOOLS = {
    "repair_and_validate_gbxml_geometry",
    "list_spaces",
    "get_model_summary",
    "validate_model",
    "inspect_osm_summary",
}


def _run_id_prefix() -> str:
    """Prompt prefix including a completed-simulation run_id if available."""
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
# operations (model creation/import ~30-60s, simulation ~60-120s)
SLOW_SKILLS = {"new-building": 180, "retrofit": 180, "gbxml-import": 180}

# Appended to all prompts to discourage raw file/script creation
SUFFIX = " Use MCP tools only."


GUIDE_ROUTING_CASES = [
    {
        "skill": "attribute-space-types",
        "prompt": (
            "Load the workflow guide for assigning standards space types to "
            "conditioned spaces in a mixed-use model."
        ),
    },
    {
        "skill": "gbxml-import",
        "prompt": (
            "Load the workflow guide for importing a Revit gbXML file and "
            "repairing its geometry."
        ),
    },
    {
        "skill": "python-ems",
        "prompt": (
            "Load the workflow guide for adding EnergyPlus Python Plugin EMS "
            "controls."
        ),
    },
    {
        "skill": "measure-authoring",
        "prompt": (
            "Load the workflow guide for writing and testing a custom "
            "OpenStudio measure."
        ),
    },
    {
        "skill": "osaf-analysis",
        "prompt": (
            "Load the workflow guide for OpenStudio Server sampling and OSA "
            "JSON analyses."
        ),
    },
]


def _prepare_prompt(case: dict) -> str:
    """Add only the model/file context required by an action-routing case."""
    skill = case["skill"]
    prompt = case["prompt"]
    routed_tools = set(case.get("expected_tools", case.get("alternatives", [])))
    needs_model = (
        skill in NEEDS_MODEL
        or (skill == "gbxml-import" and bool(routed_tools & GBXML_MODEL_TOOLS))
    )
    if needs_model:
        if skill == "python-ems":
            if not ems_model_exists():
                pytest.skip("EMS model not found — run test_01_setup first")
            prompt = EMS_LOAD_PREFIX + prompt.lower()
        else:
            if not baseline_model_exists():
                pytest.skip("Baseline model not found — run test_01_setup first")
            prompt = LOAD_PREFIX + prompt.lower()
    context = (
        SKILL_CONTEXT_PREFIX.get(skill, "")
        if "import_gbxml" in case.get("expected_tools", []) else ""
    )
    return context + prompt + SUFFIX


def _case_id(case: dict) -> str:
    return f"{case['skill']}:{case['prompt'][:35]}"


@pytest.mark.parametrize("case", EVAL_CASES, ids=[_case_id(c) for c in EVAL_CASES])
def test_eval_tool_selection(case):
    """Verify agent calls at least one expected MCP tool for an eval.md prompt."""
    # Validates: Claude selects correct tool from eval.md skill tables for natural language prompts
    tier = get_tier()
    if tier not in ("all", "1"):
        pytest.skip("Tier 1 not selected")

    prompt = _prepare_prompt(case)
    if case["skill"] in NEEDS_RUN_ID:
        prompt = _run_id_prefix() + case["prompt"].lower() + SUFFIX

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

    # Critical-param assertions from the eval.md third column (previously
    # parsed and ignored — plan finding E3). Grammar in eval_parser docstring.
    failures = check_critical_params(
        case["critical_params"], case["expected_tools"],
        normalize_calls(result), REGISTRY_PARAMS,
    )
    assert not failures, (
        f"[{case['skill']}] critical-param assertions failed: {failures}; "
        f"calls: {normalize_calls(result)}"
    )


# Negative cases: the prompt must be answered WITHOUT the forbidden tools,
# using at least one declared alternative (parsed from the machine-checkable
# "Should NOT trigger" tables).
NEGATIVE_CASES = load_should_not_trigger()


@pytest.mark.parametrize(
    "case", NEGATIVE_CASES,
    ids=[f"neg:{_case_id(c)}" for c in NEGATIVE_CASES],
)
def test_eval_negative_routing(case):
    """Verify agent avoids forbidden tools and uses a declared alternative."""
    # Regression: "Should NOT trigger" tables were parsed but never asserted
    # (plan finding E3) — negative routing had zero coverage
    tier = get_tier()
    if tier not in ("all", "1"):
        pytest.skip("Tier 1 not selected")

    prompt = _prepare_prompt(case)
    if case["skill"] in NEEDS_RUN_ID:
        prompt = _run_id_prefix() + case["prompt"].lower() + SUFFIX

    result = run_claude(prompt, timeout=180)
    called = set(result.tool_names)

    forbidden_called = called & set(case["forbidden_tools"])
    assert not forbidden_called, (
        f"[{case['skill']}] forbidden tools called for "
        f"'{case['prompt']}': {sorted(forbidden_called)}"
    )
    assert called & set(case["alternatives"]), (
        f"[{case['skill']}] none of the declared alternatives "
        f"{case['alternatives']} called for '{case['prompt']}'; got: "
        f"{sorted(called)}"
    )


@pytest.mark.parametrize(
    "case",
    GUIDE_ROUTING_CASES,
    ids=[f"guide:{case['skill']}" for case in GUIDE_ROUTING_CASES],
)
def test_served_guide_routing(case):
    """Verify natural-language guide requests retrieve the intended served skill."""
    # Validates: guide-seeking prompts route through get_skill with the exact
    # served skill name rather than passing via an unrelated action tool
    tier = get_tier()
    if tier not in ("all", "1"):
        pytest.skip("Tier 1 not selected")

    result = run_claude(case["prompt"] + SUFFIX, timeout=120)
    requested = [
        call["input"].get("name")
        for call in normalize_calls(result)
        if call["tool"] == "get_skill"
    ]
    assert case["skill"] in requested, (
        f"Expected get_skill(name={case['skill']!r}), got names {requested}; "
        f"tools: {result.tool_names}"
    )
