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

SYSTEMD = "/repo/tests/assets/SystemD_baseline.osm"
BOSTON_EPW_DIR = "/repo/tests/assets"

WORKFLOW_CASES = [
    {
        # End-to-end retrofit from user perspective: load model, set weather,
        # baseline sim, author measure, apply, retrofit sim, compare, save measure.
        # Mimics a real Claude Desktop session with natural language.
        "id": "systemd_fourpipebeam_e2e",
        "prompt": (
            f"I have a model at {SYSTEMD}. "
            f"I want you to run the model with Boston-Logan weather file — "
            f"files are in {BOSTON_EPW_DIR}. "
            "After that, create a measure for me that changes the air terminals "
            "to 4-pipe chilled beams, apply that measure to the model, "
            "run the model, and compare the results for me. "
            "Save the measure in the same location as the model so I have a copy."
        ),
        "required_tools": ["load_osm_model", "change_building_location",
                           "save_osm_model", "run_simulation",
                           "create_measure", "apply_measure"],
        "any_of": ["compare_runs", "extract_summary_metrics",
                    "extract_end_use_breakdown"],
        "min_calls": {"run_simulation": 2},
        "max_turns": 40,
        "timeout": 720,
    },
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
    {
        # Full chain: baseline sim → write measure → apply → retrofit sim → compare
        "id": "measure_set_lights_full_chain",
        "prompt": LOAD_HVAC + (
            "Do these steps in order:\n"
            "1. Save the model and run a baseline simulation. "
            "Extract summary_metrics and note the total EUI.\n"
            f"2. Reload the model from {BASELINE_HVAC_MODEL}.\n"
            "3. Write a Ruby ModelMeasure that sets all LightsDefinition "
            "objects to 8 W/m2 using setWattsperSpaceFloorArea.\n"
            "4. Create it with create_measure, test with test_measure, "
            "apply with apply_measure.\n"
            "5. Save the model and run a second simulation. "
            "Extract summary_metrics.\n"
            "6. Compare baseline vs retrofit EUI and report the difference.\n"
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "create_measure", "test_measure",
                           "apply_measure", "save_osm_model", "run_simulation"],
        "any_of": ["extract_end_use_breakdown", "extract_summary_metrics"],
        "min_calls": {"run_simulation": 2},
        "max_turns": 35,
        "timeout": 600,
    },
    {
        # Full chain: baseline sim → write measure → apply → retrofit sim → compare
        "id": "measure_set_infiltration_full_chain",
        "prompt": LOAD_HVAC + (
            "Do these steps in order:\n"
            "1. Save the model and run a baseline simulation. "
            "Extract summary_metrics and note the total EUI.\n"
            f"2. Reload the model from {BASELINE_HVAC_MODEL}.\n"
            "3. Write a Ruby ModelMeasure that sets all "
            "SpaceInfiltrationDesignFlowRate objects to use "
            "Flow/ExteriorArea method at 0.0003 m3/s-m2 "
            "(setFlowperExteriorSurfaceArea).\n"
            "4. Create it with create_measure, test with test_measure, "
            "apply with apply_measure.\n"
            "5. Save the model and run a second simulation. "
            "Extract summary_metrics.\n"
            "6. Compare baseline vs retrofit EUI and report the difference.\n"
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "create_measure", "test_measure",
                           "apply_measure", "save_osm_model", "run_simulation"],
        "any_of": ["extract_end_use_breakdown", "extract_summary_metrics"],
        "min_calls": {"run_simulation": 2},
        "max_turns": 35,
        "timeout": 600,
    },
    {
        # Full chain: baseline sim → write measure → apply → retrofit sim → compare
        "id": "measure_replace_terminals_full_chain",
        "prompt": LOAD_HVAC + (
            "Do these steps in order:\n"
            "1. Save the model and run a baseline simulation. "
            "Extract summary_metrics and note the total EUI.\n"
            f"2. Reload the model from {BASELINE_HVAC_MODEL}.\n"
            "3. Write a Ruby ModelMeasure that replaces all air terminals "
            "on every air loop with 4-pipe active chilled beam terminals. "
            "For each air loop, iterate thermalZones, removeBranchForZone, "
            "create CoilCoolingFourPipeBeam + CoilHeatingFourPipeBeam, "
            "wire coils to the CHW and HW plant loops, create "
            "AirTerminalSingleDuctConstantVolumeFourPipeBeam, and reconnect "
            "via addBranchForZone.\n"
            "4. Create it with create_measure, test with test_measure, "
            "apply with apply_measure.\n"
            "5. Save the model and run a second simulation. "
            "Extract summary_metrics or end use breakdown.\n"
            "6. Compare baseline vs retrofit results and report the "
            "difference.\n"
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "create_measure", "test_measure",
                           "apply_measure", "save_osm_model", "run_simulation"],
        "any_of": ["extract_end_use_breakdown", "extract_summary_metrics"],
        "min_calls": {"run_simulation": 2},
        "max_turns": 40,
        "timeout": 720,
    },
    {
        # Full chain: baseline sim → write measure → apply → retrofit sim → compare
        "id": "measure_add_baseboards_full_chain",
        "prompt": LOAD_HVAC + (
            "Do these steps in order:\n"
            "1. Save the model and run a baseline simulation. "
            "Extract summary_metrics and note the total EUI.\n"
            f"2. Reload the model from {BASELINE_HVAC_MODEL}.\n"
            "3. Write a Ruby ModelMeasure that adds a "
            "ZoneHVACBaseboardConvectiveElectric to every thermal zone "
            "using addToThermalZone. Name each baseboard after its zone.\n"
            "4. Create it with create_measure, test with test_measure, "
            "apply with apply_measure.\n"
            "5. Save the model and run a second simulation. "
            "Extract summary_metrics.\n"
            "6. Compare baseline vs retrofit EUI and report the difference.\n"
            "Use MCP tools only."
        ),
        "required_tools": ["load_osm_model", "create_measure", "test_measure",
                           "apply_measure", "save_osm_model", "run_simulation"],
        "any_of": ["extract_end_use_breakdown", "extract_summary_metrics"],
        "min_calls": {"run_simulation": 2},
        "max_turns": 35,
        "timeout": 600,
    },
]


SYSTEMD_MODEL = SYSTEMD  # alias for the standalone test below


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

    if "min_calls" in case:
        for tool, min_count in case["min_calls"].items():
            actual = tool_names.count(tool)
            assert actual >= min_count, (
                f"Expected {tool} >= {min_count} times, got {actual}. "
                f"Tools: {tool_names}"
            )


def test_complex_model_multi_query():
    """Load 44-zone complex model and run multiple query tools — transport regression test.

    Reproduces the failure mode from Claude Desktop: SWIG stdout warnings on
    large models corrupt MCP JSON-RPC, causing "No result received" timeouts.
    The agent must successfully complete all 4 queries without transport errors.
    """
    tier = get_tier()
    if tier not in ("all", "2"):
        pytest.skip("Tier 2 not selected")

    prompt = (
        f"Load the model at {SYSTEMD_MODEL} using load_osm_model. Then:\n"
        "1. Call get_building_info to get building details.\n"
        "2. Call list_air_loops with max_results=0 to list all air loops.\n"
        "3. Call list_plant_loops with max_results=0 to list all plant loops.\n"
        "4. Call list_thermal_zones with max_results=5.\n"
        "Report a summary of what you found. Use MCP tools only."
    )

    result = run_claude(prompt, timeout=120)
    tool_names = result.tool_names

    assert "load_osm_model" in tool_names, f"Missing load_osm_model. Tools: {tool_names}"
    assert "get_building_info" in tool_names, f"Missing get_building_info. Tools: {tool_names}"

    # At least 2 of the 3 list tools should succeed (agent may reorder or skip one)
    list_tools = {"list_air_loops", "list_plant_loops", "list_thermal_zones"}
    found = list_tools & set(tool_names)
    assert len(found) >= 2, (
        f"Expected >=2 of {list_tools}, got: {found}. Tools: {tool_names}"
    )

    # Verify no error in final text (transport failures show up as error messages)
    assert not result.is_error, f"Claude reported error: {result.final_text[:500]}"
