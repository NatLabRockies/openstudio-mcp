"""Progressive prompt tests — measure tool discovery at varying specificity.

Each case tests the same operation at 3 levels:
  L1 (vague):    Natural language, no tool names, minimal context
  L2 (moderate): Includes key details (file paths, values) but no tool names
  L3 (explicit): Includes exact tool name in the prompt

Pass rates by level reveal whether failures are due to:
  - Tool descriptions (L1 fails, L2/L3 pass → description needs keywords)
  - Tool discovery (L1+L2 fail, L3 passes → ToolSearch can't find it)
  - Tool execution (all fail → tool itself has issues)

Cases that need a loaded model use LOAD prefix. Cases that create models
don't need one.
"""
from __future__ import annotations

import pytest

from .conftest import (
    BASELINE_MODEL, BASELINE_HVAC_MODEL,
    baseline_model_exists, baseline_hvac_model_exists, get_tier,
)
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier1]

LOAD = f"Load the model at {BASELINE_MODEL} using load_osm_model. Then "
LOAD_HVAC = f"Load the model at {BASELINE_HVAC_MODEL} using load_osm_model. Then "

# Boston EPW with .stat/.ddy companions
BOSTON_EPW = (
    "/opt/comstock-measures/ChangeBuildingLocation"
    "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
)

FLOORPLAN = "/test-assets/sddc_office/floorplan.json"

# (id, needs_model, expected_tools, L1_prompt, L2_prompt, L3_prompt)
PROGRESSIVE_CASES = [
    {
        "id": "import_floorplan",
        "needs_model": False,
        "expected": ["import_floorspacejs"],
        "L1": "Import a floor plan into a new model.",
        "L2": f"Import the floor plan at {FLOORPLAN} into a new model.",
        "L3": f"Import the FloorspaceJS file at {FLOORPLAN} using import_floorspacejs.",
    },
    {
        "id": "add_hvac",
        "needs_model": True,
        "expected": ["add_baseline_system", "add_doas_system",
                     "add_vrf_system", "add_radiant_system"],
        "L1": "Add HVAC to the building.",
        "L2": "Add a VAV reheat system (System 7) to all zones.",
        "L3": "Add System 7 VAV reheat to all zones using add_baseline_system.",
    },
    {
        "id": "view_model",
        "needs_model": True,
        "expected": ["view_model"],
        "L1": "Show me the building.",
        "L2": "Generate a 3D visualization of the model.",
        "L3": "Show me a 3D view of the model using view_model.",
    },
    {
        "id": "set_weather",
        "needs_model": True,
        "expected": ["change_building_location", "set_weather_file"],
        "L1": "Set the weather to Boston.",
        "L2": f"Set the weather file to {BOSTON_EPW}.",
        "L3": f"Set the weather using change_building_location with weather_file {BOSTON_EPW}.",
    },
    {
        # run_qaqc_checks requires a run_id (post-simulation). Pre-sim QA can
        # use inspect_osm_summary or get_model_summary. All are valid QA tools.
        "id": "run_qaqc",
        "needs_model": True,
        "expected": ["run_qaqc_checks", "inspect_osm_summary", "get_model_summary",
                     "get_building_info", "list_thermal_zones"],
        "L1": "Check the model for problems.",
        "L2": "Run quality assurance checks on the model.",
        "L3": "Check the model for issues using run_qaqc_checks or inspect_osm_summary.",
    },
    {
        "id": "create_building",
        "needs_model": False,
        "expected": ["create_new_building", "create_bar_building"],
        "L1": "Create a small office building.",
        "L2": "Create a 2-story, 20000 sqft small office building.",
        "L3": "Create a SmallOffice bar building using create_bar_building "
              "with 2 stories and 20000 sqft.",
    },
    {
        "id": "add_pv",
        "needs_model": True,
        "expected": ["add_rooftop_pv", "add_pv_to_shading"],
        "L1": "Add solar panels to the building.",
        "L2": "Add rooftop photovoltaic panels to the building.",
        "L3": "Add rooftop solar panels using add_rooftop_pv.",
    },
    {
        # adjust_thermostat_setpoints takes offsets, not absolute values.
        # replace_thermostat_schedules / set_thermostat_schedules work for
        # absolute setpoints — all are valid thermostat tools.
        "id": "thermostat",
        "needs_model": True,
        "expected": ["adjust_thermostat_setpoints", "set_thermostat_schedules",
                     "replace_thermostat_schedules"],
        "L1": "Make the building warmer in winter.",
        "L2": "Raise the cooling setpoint by 2 degrees F.",
        "L3": "Adjust the thermostat setpoints using adjust_thermostat_setpoints. "
              "Raise cooling by 2F.",
    },
    {
        "id": "list_spaces",
        "needs_model": True,
        "expected": ["list_spaces"],
        "L1": "What rooms are in the building?",
        "L2": "List all the spaces in the model.",
        "L3": "List the spaces using list_spaces.",
    },
    {
        "id": "schedules",
        "needs_model": True,
        "expected": ["list_schedule_rulesets", "get_schedule_details"],
        "L1": "What schedules does the building use?",
        "L2": "List all the schedule rulesets in the model.",
        "L3": "List the schedules using list_schedule_rulesets.",
    },
    # --- Generic object access (needs HVAC model) ---
    {
        "id": "inspect_component",
        "needs_model": True,
        "needs_hvac": True,
        "expected": ["get_object_fields", "get_component_properties"],
        "L1": "What are the properties of the hot water boiler?",
        "L2": "Show me all properties of the BoilerHotWater in the model.",
        "L3": "Use get_object_fields to read properties of the BoilerHotWater.",
    },
    {
        "id": "modify_component",
        "needs_model": True,
        "needs_hvac": True,
        "expected": ["set_object_property", "set_component_properties"],
        "L1": "Make the boiler more efficient.",
        "L2": "Set the boiler's nominal thermal efficiency to 0.92.",
        "L3": "Use set_object_property to set nominalThermalEfficiency to 0.92 "
              "on the BoilerHotWater.",
    },
    {
        "id": "list_dynamic_type",
        "needs_model": True,
        "needs_hvac": True,
        "expected": ["list_model_objects"],
        "L1": "What sizing parameters exist in the model?",
        "L2": "List all SizingSystem objects in the model.",
        "L3": "Use list_model_objects with object_type SizingSystem to list sizing objects.",
    },
    # --- Migrated from test_02 (formerly with-model only) ---
    {
        "id": "floor_area",
        "needs_model": True,
        "expected": ["get_building_info", "get_model_summary"],
        "L1": "How big is the building?",
        "L2": "What is the building's total floor area?",
        "L3": "Get the building floor area using get_building_info.",
    },
    {
        "id": "materials",
        "needs_model": True,
        "expected": ["list_materials"],
        "L1": "What materials are used in the building?",
        "L2": "List all materials in the model.",
        "L3": "List the materials using list_materials.",
    },
    {
        "id": "thermal_zones",
        "needs_model": True,
        "expected": ["list_thermal_zones"],
        "L1": "How many zones does the building have?",
        "L2": "List all thermal zones in the model.",
        "L3": "List the thermal zones using list_thermal_zones.",
    },
    {
        "id": "subsurfaces",
        "needs_model": True,
        "expected": ["list_subsurfaces"],
        "L1": "What windows does the building have?",
        "L2": "List all subsurfaces (windows and doors) in the model.",
        "L3": "List the subsurfaces using list_subsurfaces.",
    },
    {
        "id": "surface_details",
        "needs_model": True,
        "expected": ["get_surface_details", "list_surfaces"],
        "L1": "Tell me about the south wall.",
        "L2": "Show details for a wall surface in the model.",
        "L3": "Show surface details using get_surface_details or list_surfaces.",
    },
]

SUFFIX = " Use MCP tools only."

# Flatten into parametrized cases: (case_id, level, prompt, expected)
_FLAT_CASES = []
for case in PROGRESSIVE_CASES:
    for level in ("L1", "L2", "L3"):
        _FLAT_CASES.append({
            "id": f"{case['id']}_{level}",
            "case_id": case["id"],
            "level": level,
            "needs_model": case["needs_model"],
            "needs_hvac": case.get("needs_hvac", False),
            "prompt": case[level],
            "expected": case["expected"],
        })


_GENERIC_IDS = {"inspect_component", "modify_component", "list_dynamic_type"}


@pytest.mark.progressive
@pytest.mark.parametrize("case", _FLAT_CASES, ids=[c["id"] for c in _FLAT_CASES])
def test_progressive(case):
    """Test tool discovery at varying prompt specificity levels.

    L1 (vague) → L2 (moderate) → L3 (explicit). Tracks which level
    the agent starts succeeding at. Lower levels passing = better
    tool discoverability.
    """
    tier = get_tier()
    if tier not in ("all", "1"):
        pytest.skip("Tier 1 not selected")

    prompt = case["prompt"]
    if case.get("needs_hvac"):
        if not baseline_hvac_model_exists():
            pytest.skip("Baseline+HVAC model not found — run test_01_setup first")
        prompt = LOAD_HVAC + prompt.lower()
    elif case["needs_model"]:
        if not baseline_model_exists():
            pytest.skip("Baseline model not found — run test_01_setup first")
        prompt = LOAD + prompt.lower()
    prompt += SUFFIX

    result = run_claude(prompt, timeout=120)
    tool_names = result.tool_names

    assert any(t in case["expected"] for t in tool_names), (
        f"[{case['case_id']} {case['level']}] "
        f"Expected one of {case['expected']}, got: {tool_names}"
    )
