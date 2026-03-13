"""Tier 2: Multi-step workflow tests — load saved model, perform actions.

Each test loads the baseline model from test_01_setup, then performs a
specific action (add HVAC, set weather, delete object, etc.). This tests
the agent's ability to chain multiple MCP tools in the right sequence.

Design:
  - All cases use LOAD prefix to load the saved baseline model
  - Prompts include explicit tool names to minimize ambiguity
  - required_tools are ALL checked (every one must appear in the sequence)
  - any_of is used when multiple tools can achieve the same goal
    (e.g. change_building_location for Chicago weather)
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

from .conftest import (
    BASELINE_MODEL, BASELINE_HVAC_MODEL,
    baseline_model_exists, baseline_hvac_model_exists, get_tier,
    get_sim_run_id,
)
from .runner import run_claude

pytestmark = [pytest.mark.llm, pytest.mark.tier2]

LOAD = f"Load the model at {BASELINE_MODEL} using load_osm_model. Then "
LOAD_HVAC = f"Load the model at {BASELINE_HVAC_MODEL} using load_osm_model. Then "

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
        # Set weather + design days + climate zone via measure
        "id": "set_weather",
        "prompt": LOAD + (
            "set the weather to Boston using change_building_location "
            "with the EPW file at /opt/comstock-measures/ChangeBuildingLocation"
            "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "change_building_location"],
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
        # which can be slow (180s timeout). Uses offset language since
        # adjust_thermostat_setpoints takes offsets, not absolute values.
        # Also accepts replace_thermostat_schedules (valid for absolute setpoints).
        "id": "adjust_thermostat",
        "prompt": LOAD + (
            "adjust the thermostat setpoints using adjust_thermostat_setpoints. "
            "Raise cooling by 2F and lower heating by 1F. Use MCP tools only."
        ),
        "required_tools": ["load_osm_model"],
        "any_of": ["adjust_thermostat_setpoints", "replace_thermostat_schedules",
                    "set_thermostat_schedules"],
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
    {
        # Create bar building — tests geometry creation from scratch
        "id": "create_bar_office",
        "prompt": (
            "Create a SmallOffice bar building using create_bar_building "
            "with 2 stories and 20000 sqft. Then list the spaces. "
            "Use MCP tools only."
        ),
        "required_tools": ["create_bar_building"],
        "any_of": ["list_spaces", "get_model_summary"],
        "timeout": 120,
    },
    {
        # One-call new building — tests convenience tool
        "id": "create_new_building",
        "prompt": (
            "Create a complete MediumOffice building using create_new_building "
            "with 3 stories and 50000 sqft. Use the weather file at "
            "/opt/comstock-measures/ChangeBuildingLocation"
            "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw. "
            "Use MCP tools only."
        ),
        "required_tools": ["create_new_building"],
        "timeout": 180,
    },
    {
        # Bar → weather/DDY → typical chain (manual multi-step version of create_new_building)
        "id": "bar_then_typical",
        "prompt": (
            "Create a SmallOffice bar building using create_bar_building "
            "with 2 stories and 20000 sqft. "
            "After that, call change_building_location with weather_file "
            "/opt/comstock-measures/ChangeBuildingLocation"
            "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw. "
            "After that, call create_typical_building with building_type SmallOffice. "
            "Use MCP tools only."
        ),
        "required_tools": [
            "create_bar_building", "change_building_location",
            "create_typical_building",
        ],
        "max_turns": 25,
        "timeout": 420,
    },
    {
        # Import FloorspaceJS JSON — tests SDK reverse translator
        "id": "import_floorspacejs",
        "prompt": (
            "Import the FloorspaceJS JSON file at "
            "/test-assets/sddc_office/floorplan.json "
            "using import_floorspacejs. Use MCP tools only."
        ),
        "required_tools": ["import_floorspacejs"],
        "timeout": 120,
    },
    {
        # FloorspaceJS → weather/DDY → typical full chain
        "id": "floorspacejs_to_typical",
        "prompt": (
            "Do all 3 steps in order, do not stop early:\n"
            "Step 1: Import the FloorspaceJS file at "
            "/test-assets/sddc_office/floorplan.json "
            "using import_floorspacejs.\n"
            "Step 2: Call change_building_location with weather_file="
            "/opt/comstock-measures/ChangeBuildingLocation"
            "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw "
            "(use this path directly, do not search for files).\n"
            "Step 3: Call create_typical_building to add "
            "constructions, loads, and HVAC.\n"
            "Use MCP tools only. Complete all 3 steps."
        ),
        "required_tools": [
            "import_floorspacejs", "change_building_location",
            "create_typical_building",
        ],
        "max_turns": 25,
        "timeout": 420,
    },
    {
        # Manual geometry with surface matching
        "id": "manual_geometry_match",
        "prompt": (
            "Create two adjacent spaces using create_space_from_floor_print. "
            "Space 1: vertices (0,0), (10,0), (10,10), (0,10) at floor height 0. "
            "Space 2: vertices (10,0), (20,0), (20,10), (10,10) at floor height 0. "
            "Then run match_surfaces to find shared walls. "
            "Use MCP tools only."
        ),
        "required_tools": ["create_space_from_floor_print", "match_surfaces"],
        "timeout": 120,
    },
    {
        # Envelope retrofit: WWR + window upgrade
        "id": "envelope_retrofit",
        "prompt": LOAD + (
            "Set the window-to-wall ratio to 0.4 using set_window_to_wall_ratio. "
            "Then replace window constructions using replace_window_constructions. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "set_window_to_wall_ratio",
                           "replace_window_constructions"],
        "timeout": 180,
    },
    {
        # Create loads and assign to model
        "id": "create_and_assign_loads",
        "prompt": LOAD + (
            "Create a people definition using create_people_definition with "
            "people_per_floor_area 0.05 and name 'Office People'. "
            "Then create a lights definition using create_lights_definition with "
            "watts_per_floor_area 10 and name 'Office Lights'. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "create_people_definition",
                           "create_lights_definition"],
        "timeout": 120,
    },
    {
        # Plant loop with supply equipment
        "id": "plant_loop_with_boiler",
        "prompt": LOAD + (
            "Create a heating plant loop using create_plant_loop with loop_type "
            "heating. Then add a hot water boiler using add_supply_equipment "
            "with equipment_type BoilerHotWater. Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "create_plant_loop",
                           "add_supply_equipment"],
        "timeout": 120,
    },
    {
        # Generic object access: inspect and modify a boiler
        "id": "inspect_and_modify_boiler",
        "prompt": LOAD_HVAC + (
            "List the BoilerHotWater objects using list_model_objects. "
            "Then read the properties of the first boiler using get_object_fields. "
            "Then set its nominalThermalEfficiency to 0.95 using set_object_property. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "list_model_objects",
                           "get_object_fields", "set_object_property"],
        "timeout": 120,
    },
    {
        # Extract multiple result types from a completed simulation
        "id": "extract_results_chain",
        "needs_run": True,
        "prompt": None,  # built dynamically from run_id
        "required_tools": ["extract_summary_metrics", "extract_end_use_breakdown"],
        "timeout": 120,
    },
    {
        # Replace air terminals with CooledBeam, simulate, extract results
        "id": "hvac_chilled_beam_comparison",
        "prompt": LOAD_HVAC + (
            "Get the current air loop details. "
            "Replace all air terminals with CooledBeam type using replace_air_terminals. "
            "Save the model and run a simulation. "
            "Extract the end use breakdown. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "replace_air_terminals",
                           "save_osm_model", "run_simulation"],
        "any_of": ["extract_end_use_breakdown", "extract_summary_metrics"],
        "max_turns": 25,
        "timeout": 300,
    },
    {
        # Measure authoring lifecycle: create → test → apply
        "id": "create_test_apply_measure",
        "prompt": LOAD + (
            "Create a Ruby custom measure named 'set_bldg_name_test' using "
            "create_measure. It should set the building name to 'LLM Test'. "
            "Use language Ruby, and run_body: "
            "\"    model.getBuilding.setName('LLM Test')\\n"
            "    runner.registerInfo('Done')\". "
            "Then test it using test_measure. "
            "Then apply it using apply_measure with the measure_dir from create. "
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "create_measure", "test_measure",
                           "apply_measure"],
        "max_turns": 25,
        "timeout": 180,
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

    # Build prompt for needs_run cases
    prompt = case["prompt"]
    if case.get("needs_run"):
        run_id = get_sim_run_id()
        if not run_id:
            pytest.skip("No simulation run_id — run test_01_setup first")
        prompt = (
            f"Extract results from simulation run '{run_id}'. "
            "First extract summary metrics using extract_summary_metrics. "
            "Then extract end use breakdown using extract_end_use_breakdown. "
            "Use MCP tools only."
        )
    elif BASELINE_HVAC_MODEL in prompt and not baseline_hvac_model_exists():
        pytest.skip("Baseline+HVAC model not found — run test_01_setup first")
    elif BASELINE_MODEL in prompt and not baseline_model_exists():
        pytest.skip("Baseline model not found — run test_01_setup first")

    result = run_claude(
        prompt,
        timeout=case.get("timeout", 120),
        max_turns=case.get("max_turns"),
    )
    tool_names = result.tool_names

    for tool in case["required_tools"]:
        assert tool in tool_names, (
            f"Required tool '{tool}' not found. Tools: {tool_names}"
        )

    if "any_of" in case:
        assert any(t in tool_names for t in case["any_of"]), (
            f"None of {case['any_of']} found. Tools: {tool_names}"
        )
