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
    get_retrofit_run_id, get_sim_run_id,
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
#
# Optional "expected_args": {level: {tool: {arg: value | (value, rel_tol)}}}.
# Asserted on the FIRST call to that tool, only at levels whose prompt states
# the value unambiguously, and only when that tool was the one called (cases
# satisfied via an alternative accepted tool skip the arg check).
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
        "expected_args": {
            "L2": {"add_baseline_system": {"system_type": 7}},
            "L3": {"add_baseline_system": {"system_type": 7}},
        },
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
        # Custom EMS control logic → Python plugin authoring (or actuator
        # discovery first) — not a thermostat/schedule edit tool.
        "id": "python_ems_control",
        "needs_model": True,
        "expected": ["create_python_plugin", "list_ems_actuators"],
        "L1": "Add custom control logic that sets the heating setpoint back at night.",
        "L2": "Create a Python EMS plugin that overrides the heating setpoint "
              "schedule to 15.6 C outside 6am-6pm.",
        "L3": "Use create_python_plugin with the schedule_override template to set "
              "the heating schedule to 15.6 outside hours 6-18.",
    },
    {
        "id": "set_weather",
        "needs_model": True,
        "expected": ["change_building_location"],
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
                     "get_building_info", "list_thermal_zones", "validate_model"],
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
        "expected_args": {
            "L2": {"adjust_thermostat_setpoints": {"cooling_offset_f": (2.0, 0.001)}},
            "L3": {"adjust_thermostat_setpoints": {"cooling_offset_f": (2.0, 0.001)}},
        },
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
        "expected": ["list_model_objects", "get_schedule_details"],
        "L1": "What schedules does the building use?",
        "L2": "List all the schedule rulesets in the model.",
        "L3": "List the schedules using list_model_objects with object_type ScheduleRuleset.",
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
        "expected_args": {
            "L2": {"set_object_property": {"value": (0.92, 0.001)}},
            "L3": {"set_object_property": {"value": (0.92, 0.001)}},
        },
    },
    {
        "id": "list_dynamic_type",
        "needs_model": True,
        "needs_hvac": True,
        "expected": ["list_model_objects", "get_sizing_system_properties",
                     "get_sizing_zone_properties"],
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
    # --- Simulation & results (need completed simulation) ---
    {
        "id": "run_simulation",
        "needs_model": True,
        "expected": ["run_simulation", "run_osw"],
        "L1": "Simulate the building and get the energy results.",
        "L2": "Run an EnergyPlus simulation on this model.",
        "L3": "Run the simulation using run_simulation.",
    },
    {
        "id": "get_eui",
        "needs_model": False,
        "needs_run": True,
        "expected": ["extract_summary_metrics"],
        "L1": "What's the building's energy use?",
        "L2": "Extract the EUI from the simulation results.",
        "L3": "Extract summary metrics using extract_summary_metrics.",
    },
    {
        "id": "end_use_breakdown",
        "needs_model": False,
        "needs_run": True,
        "expected": ["extract_end_use_breakdown"],
        "L1": "How much energy goes to heating vs cooling?",
        "L2": "Show the end use breakdown from the simulation.",
        "L3": "Extract end use breakdown using extract_end_use_breakdown.",
    },
    {
        "id": "hvac_sizing",
        "needs_model": False,
        "needs_run": True,
        "expected": ["extract_hvac_sizing", "extract_component_sizing"],
        "L1": "Are the HVAC systems properly sized?",
        "L2": "Show the HVAC sizing results from the simulation.",
        "L3": "Extract HVAC sizing using extract_hvac_sizing.",
    },
    # --- Envelope ---
    {
        "id": "set_wwr",
        "needs_model": True,
        "expected": ["set_window_to_wall_ratio"],
        "L1": "Add windows to the building.",
        "L2": "Set the window-to-wall ratio to 40% on all facades.",
        "L3": "Set the window to wall ratio to 0.4 using set_window_to_wall_ratio.",
        "expected_args": {
            "L2": {"set_window_to_wall_ratio": {"ratio": (0.4, 0.001)}},
            "L3": {"set_window_to_wall_ratio": {"ratio": (0.4, 0.001)}},
        },
    },
    {
        "id": "replace_windows",
        "needs_model": True,
        "expected": ["replace_window_constructions", "list_common_measures",
                     "list_materials", "get_construction_details"],
        "L1": "Upgrade the windows to double-pane low-e.",
        "L2": "Replace all window constructions with better performing glazing.",
        "L3": "Replace window constructions using replace_window_constructions.",
    },
    {
        "id": "construction_details",
        "needs_model": True,
        "expected": ["get_construction_details"],
        "L1": "What layers make up the exterior wall?",
        "L2": "Show the material layers of a wall construction.",
        "L3": "Get construction details using get_construction_details.",
    },
    # --- Loads ---
    {
        "id": "check_loads",
        "needs_model": True,
        "expected": ["get_load_details", "get_object_fields", "list_model_objects",
                     "get_space_details", "get_space_type_details"],
        "L1": "What loads are assigned to the first space?",
        "L2": "Get the people and lighting load details for a space.",
        "L3": "Get load details using get_load_details.",
    },
    {
        "id": "create_loads",
        "needs_model": True,
        "expected": ["create_people_definition", "create_lights_definition"],
        "L1": "Add people and lighting to the office spaces.",
        "L2": "Create a people load of 0.05 people per square meter and "
              "lighting at 10 W per square meter.",
        "L3": "Create a people definition using create_people_definition with "
              "people_per_area 0.05.",
        "expected_args": {
            "L2": {"create_people_definition": {"people_per_area": (0.05, 0.001)}},
            "L3": {"create_people_definition": {"people_per_area": (0.05, 0.001)}},
        },
    },
    # --- Plant loops ---
    {
        "id": "create_plant_loop",
        "needs_model": True,
        "expected": ["create_plant_loop"],
        "L1": "Create a hot water heating loop.",
        "L2": "Create a plant loop for hot water heating with a 82C design temp.",
        "L3": "Create a plant loop using create_plant_loop with loop_type heating.",
        "expected_args": {
            "L2": {"create_plant_loop": {"loop_type": "Heating",
                                         "design_exit_temp_c": (82.0, 0.001)}},
            "L3": {"create_plant_loop": {"loop_type": "Heating"}},
        },
    },
    # --- Schedules & space types ---
    {
        "id": "schedule_details",
        "needs_model": True,
        "expected": ["get_schedule_details"],
        "L1": "What hours is the HVAC running?",
        "L2": "Show the details of an HVAC operation schedule.",
        "L3": "Get schedule details using get_schedule_details.",
    },
    {
        "id": "space_type_info",
        "needs_model": True,
        "expected": ["get_space_type_details", "get_object_fields"],
        "L1": "What type of space is this and what are its defaults?",
        "L2": "Show the space type details including default loads and schedules.",
        "L3": "Get space type details using get_space_type_details.",
    },
    # --- Design conditions ---
    {
        "id": "set_run_period",
        "needs_model": True,
        "expected": ["set_run_period", "get_run_period"],
        "L1": "Set the simulation to run for a full year.",
        "L2": "Set the run period from January 1 to December 31.",
        "L3": "Set the run period using set_run_period with start 1/1 end 12/31.",
        "expected_args": {
            "L2": {"set_run_period": {"begin_month": 1, "begin_day": 1,
                                      "end_month": 12, "end_day": 31}},
            "L3": {"set_run_period": {"begin_month": 1, "begin_day": 1,
                                      "end_month": 12, "end_day": 31}},
        },
    },
    {
        "id": "ideal_air",
        "needs_model": True,
        "expected": ["enable_ideal_air_loads"],
        "L1": "Use ideal air loads for quick sizing.",
        "L2": "Enable ideal air loads on all zones for sizing runs.",
        "L3": "Enable ideal air loads using enable_ideal_air_loads.",
    },
    # --- Model management & misc ---
    {
        "id": "save_model",
        "needs_model": True,
        "expected": ["save_osm_model"],
        "L1": "Save my changes.",
        "L2": "Save the model to /runs/my_model.osm.",
        "L3": "Save the model using save_osm_model to /runs/my_model.osm.",
    },
    {
        "id": "add_ev",
        "needs_model": True,
        "expected": ["add_ev_load"],
        "L1": "Add electric vehicle charging to the building.",
        "L2": "Add EV charging load to the parking area.",
        "L3": "Add EV charging using add_ev_load.",
    },
    # --- Measure authoring (Phase 9) ---
    {
        "id": "list_measures",
        "needs_model": False,
        "expected": ["list_custom_measures"],
        "L1": "What custom measures do I have?",
        "L2": "List all custom measures I've created.",
        "L3": "List custom measures using list_custom_measures.",
    },
    {
        "id": "create_measure",
        "needs_model": False,
        "expected": ["create_measure"],
        "L1": "Write a custom measure that sets the building name.",
        "L2": "Create a Ruby ModelMeasure that sets the building name to 'Test'.",
        "L3": "Create a custom measure using create_measure with language Ruby "
              "and run_body that calls model.getBuilding.setName.",
    },
    {
        "id": "test_measure",
        "needs_model": False,
        "expected": ["test_measure"],
        "L1": "Run the tests for my custom measure.",
        "L2": "Run the test suite for the measure at /measures/local/custom/my_measure.",
        "L3": "Test the measure using test_measure with measure_dir "
              "/measures/local/custom/my_measure.",
    },
    {
        "id": "apply_existing_measure",
        "needs_model": True,
        "expected": ["apply_measure", "list_measure_arguments"],
        "L1": "Apply the set_building_name measure from /repo/tests/assets/measures/.",
        "L2": "Apply the measure at /repo/tests/assets/measures/set_building_name "
              "with building_name 'New Name'.",
        "L3": "Apply the measure at /repo/tests/assets/measures/set_building_name "
              "using apply_measure with arguments {building_name: 'New Name'}.",
    },
    # --- CooledBeam + zone priority ---
    {
        "id": "replace_terminals_cooled_beam",
        "needs_model": True,
        "needs_hvac": True,
        "expected": ["replace_air_terminals"],
        "L1": "Replace the air terminals with cooling-only chilled beams.",
        "L2": "Replace the air terminals on the air loop with CooledBeam type using replace_air_terminals.",
        "L3": "Use replace_air_terminals with terminal_type='CooledBeam'.",
        "expected_args": {
            "L1": {"replace_air_terminals": {"terminal_type": "CooledBeam"}},
            "L2": {"replace_air_terminals": {"terminal_type": "CooledBeam"}},
            "L3": {"replace_air_terminals": {"terminal_type": "CooledBeam"}},
        },
    },
    {
        "id": "replace_terminals_four_pipe_beam",
        "needs_model": True,
        "needs_hvac": True,
        "expected": ["replace_air_terminals"],
        "L1": "Replace the air terminals with 4-pipe chilled beams that provide both heating and cooling.",
        "L2": "Replace the air terminals on the air loop with FourPipeBeam type using replace_air_terminals.",
        "L3": "Use replace_air_terminals with terminal_type='FourPipeBeam'.",
        "expected_args": {
            "L1": {"replace_air_terminals": {"terminal_type": "FourPipeBeam"}},
            "L2": {"replace_air_terminals": {"terminal_type": "FourPipeBeam"}},
            "L3": {"replace_air_terminals": {"terminal_type": "FourPipeBeam"}},
        },
    },
    {
        "id": "measure_replace_terminals",
        "needs_model": True,
        "needs_hvac": True,
        "expected": ["create_measure"],
        "L1": "Write a custom measure that replaces VAV terminals with 4-pipe chilled beams on all air loops.",
        "L2": "Create a Ruby measure using create_measure that walks air loops and replaces terminals with 4-pipe chilled beam terminals.",
        "L3": "Use create_measure (language Ruby). run_body should iterate model.getAirLoopHVACs, removeBranchForZone for each zone, create AirTerminalSingleDuctConstantVolumeFourPipeBeam, reconnect via addBranchForZone.",
    },
    {
        "id": "zone_equipment_priority",
        "needs_model": True,
        "needs_hvac": True,
        "expected": ["set_zone_equipment_priority", "add_zone_equipment"],
        "L1": "Add a baseboard heater to the first zone, then reorder zone equipment priority.",
        "L2": "Add a ZoneHVACBaseboardConvectiveElectric to the first zone using add_zone_equipment, "
              "then use set_zone_equipment_priority to change the serving order.",
        "L3": "Use add_zone_equipment to add a ZoneHVACBaseboardConvectiveElectric to the first zone. "
              "Then call set_zone_equipment_priority to set the baseboard as highest priority.",
    },
    {
        "id": "edit_measure",
        "needs_model": False,
        "expected": ["edit_measure", "list_custom_measures"],
        "L1": "Update my custom measure to also log the old building name.",
        "L2": "Edit the run body of custom measure my_measure to add logging.",
        "L3": "Edit measure my_measure using edit_measure with run_body "
              "'    runner.registerInfo(\"updated\")'.",
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
            "needs_run": case.get("needs_run", False),
            "prompt": case[level],
            "expected": case["expected"],
            "expected_args": case.get("expected_args", {}).get(level, {}),
        })


_GENERIC_IDS = {"inspect_component", "modify_component", "list_dynamic_type"}


@pytest.mark.progressive
@pytest.mark.parametrize("case", _FLAT_CASES, ids=[c["id"] for c in _FLAT_CASES])
def test_progressive(case):
    """Test tool discovery at varying prompt specificity levels."""
    # Validates: Claude routes L1/L2/L3 prompts to correct tools — lower levels passing = better discoverability
    tier = get_tier()
    if tier not in ("all", "1"):
        pytest.skip("Tier 1 not selected")

    prompt = case["prompt"]
    if case.get("needs_run"):
        run_id = get_sim_run_id()
        if not run_id:
            pytest.skip("No simulation run_id — run test_01_setup first")
        prompt = f"Use run_id '{run_id}'. " + prompt
    elif case.get("needs_hvac"):
        if not baseline_hvac_model_exists():
            pytest.skip("Baseline+HVAC model not found — run test_01_setup first")
        prompt = LOAD_HVAC + prompt
    elif case["needs_model"]:
        if not baseline_model_exists():
            pytest.skip("Baseline model not found — run test_01_setup first")
        prompt = LOAD + prompt
    prompt += SUFFIX

    timeout = 300 if case.get("needs_run") or case["case_id"] == "run_simulation" else 120
    result = run_claude(prompt, timeout=timeout)
    tool_names = result.tool_names

    matched = [t for t in tool_names if t in case["expected"]]
    assert matched, (
        f"[{case['case_id']} {case['level']}] "
        f"Expected one of {case['expected']}, got: {tool_names}"
    )

    # Right tool called AND its first call succeeded (ok:false = tool_error)
    assert result.tool_ok(matched[0]) is not False, (
        f"[{case['case_id']} {case['level']}] "
        f"{matched[0]} was called but returned ok:false"
    )

    _assert_expected_args(case, result)


def _assert_expected_args(case, result):
    """Check pinned argument values on the first call to each spec'd tool.

    Skips tools the agent never called — the case may have been satisfied
    via an alternative accepted tool, which the expected-tool assert covers.
    """
    prefix = "mcp__openstudio__"
    for tool, spec in case["expected_args"].items():
        calls = [c for c in result.mcp_tool_calls
                 if c["tool"].removeprefix(prefix) == tool]
        if not calls:
            continue
        got_input = calls[0]["input"]
        for arg, want in spec.items():
            got = got_input.get(arg)
            label = f"[{case['case_id']} {case['level']}] {tool}.{arg}"
            if isinstance(want, tuple):
                target, rel = want
                try:
                    got_num = float(got)
                except (TypeError, ValueError):
                    got_num = None
                assert got_num == pytest.approx(target, rel=rel), (
                    f"{label} expected ~{target}, got {got!r}"
                )
            elif isinstance(want, str) and isinstance(got, str):
                # Case-insensitive: casing correctness is the TOOL's contract —
                # a casing the tool rejects already fails the tool_ok assert.
                assert got.lower() == want.lower(), (
                    f"{label} expected {want!r}, got {got!r}"
                )
            else:
                assert got == want, f"{label} expected {want!r}, got {got!r}"
