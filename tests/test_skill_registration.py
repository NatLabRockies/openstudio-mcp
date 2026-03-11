"""Verify that skills auto-discovery registers all expected tools.

This is the critical Phase 1 test — it ensures the refactored skill
structure produces the exact same set of MCP tools as the old monolithic
server.py. If this passes, the migration is backward-compatible.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from mcp_server.skills import register_all_skills

EXPECTED_TOOLS = {
    "get_server_status",
    "get_versions",
    "create_example_osm",
    "create_baseline_osm",
    "inspect_osm_summary",
    "load_osm_model",
    "save_osm_model",
    "get_building_info",
    "get_model_summary",
    "list_building_stories",
    "list_spaces",
    "get_space_details",
    "list_thermal_zones",
    "get_thermal_zone_details",
    "create_space",
    "create_thermal_zone",
    "list_surfaces",
    "get_surface_details",
    "list_subsurfaces",
    "create_surface",
    "create_subsurface",
    "create_space_from_floor_print",
    "match_surfaces",
    "set_window_to_wall_ratio",
    "list_materials",
    "list_constructions",
    "list_construction_sets",
    "create_standard_opaque_material",
    "create_construction",
    "assign_construction_to_surface",
    "list_schedule_rulesets",
    "get_schedule_details",
    "create_schedule_ruleset",
    "list_air_loops",
    "get_air_loop_details",
    "add_air_loop",
    "list_plant_loops",
    "get_plant_loop_details",
    "list_zone_hvac_equipment",
    "get_zone_hvac_details",
    "list_people_loads",
    "list_lighting_loads",
    "list_electric_equipment",
    "list_gas_equipment",
    "list_infiltration",
    "list_space_types",
    "get_space_type_details",
    "add_output_variable",
    "add_output_meter",
    "add_baseline_system",
    "list_baseline_systems",
    "get_baseline_system_info",
    "replace_air_terminals",
    "replace_zone_terminal",
    "add_doas_system",
    "add_vrf_system",
    "add_radiant_system",
    # Phase 5: Component Properties
    "list_hvac_components",
    "get_component_properties",
    "set_component_properties",
    "set_economizer_properties",
    "set_sizing_properties",
    "set_sizing_system_properties",
    "get_sizing_system_properties",
    "set_sizing_zone_properties",
    "get_sizing_zone_properties",
    "get_setpoint_manager_properties",
    "set_setpoint_manager_properties",
    # Phase 5: Loop Operations
    "create_plant_loop",
    "add_supply_equipment",
    "remove_supply_equipment",
    "add_demand_component",
    "remove_demand_component",
    "add_zone_equipment",
    "remove_zone_equipment",
    "remove_all_zone_equipment",
    # Phase 6A: Load Creation
    "create_people_definition",
    "create_lights_definition",
    "create_electric_equipment",
    "create_gas_equipment",
    "create_infiltration",
    # Phase 6B: Object Management
    "delete_object",
    "rename_object",
    "list_model_objects",
    # Phase 6C: Weather, Design Days, SimControl, RunPeriod
    "get_weather_info",
    "add_design_day",
    "get_simulation_control",
    "set_simulation_control",
    "get_run_period",
    "set_run_period",
    # Phase 6D: Measures
    "list_measure_arguments",
    "apply_measure",
    # ComStock + geometry workflows
    "list_comstock_measures",
    "create_typical_building",
    "create_bar_building",
    "create_new_building",
    "import_floorspacejs",
    "validate_osw",
    "run_osw",
    "run_simulation",
    "get_run_status",
    "get_run_logs",
    "get_run_artifacts",
    "cancel_run",
    "read_file",
    "extract_summary_metrics",
    "copy_file",
    # Results extraction (Tier 1 + Tier 2)
    "extract_end_use_breakdown",
    "extract_envelope_summary",
    "extract_hvac_sizing",
    "extract_zone_summary",
    "extract_component_sizing",
    "query_timeseries",
    # Model Management extras
    "list_files",
    # Common Measures — Tier 1
    "list_common_measures",
    "view_model",
    "view_simulation_data",
    "generate_results_report",
    "run_qaqc_checks",
    "adjust_thermostat_setpoints",
    "replace_window_constructions",
    "enable_ideal_air_loads",
    "clean_unused_objects",
    "change_building_location",
    # Common Measures — Tier 2
    "set_thermostat_schedules",
    "replace_thermostat_schedules",
    "shift_schedule_time",
    "add_rooftop_pv",
    "add_pv_to_shading",
    "add_ev_load",
    "add_zone_ventilation",
    "set_lifecycle_cost_params",
    "add_cost_per_floor_area",
    "set_adiabatic_boundaries",
    # Skill Discovery
    "list_skills",
    "get_skill",
}


def test_all_skills_registered():
    """All expected skills are discovered and registered."""
    mcp = MagicMock()
    # mcp.tool() must return a decorator that returns the function
    mcp.tool.return_value = lambda fn: fn

    skills = register_all_skills(mcp)

    assert len(skills) >= 4, f"Expected >= 4 skills, got {skills}"
    assert "server_info" in skills
    assert "model_management" in skills
    assert "simulation" in skills
    assert "results" in skills


def test_all_tool_names_registered():
    """Every expected tool function is registered via mcp.tool()."""
    registered_tools = {}

    class FakeMCP:
        def tool(self, name=None):
            def decorator(fn):
                # Use explicit name if provided, otherwise function name
                tool_name = name or fn.__name__
                registered_tools[tool_name] = fn
                return fn
            return decorator
        def prompt(self, **kw):
            return lambda fn: fn
        def resource(self, *a, **kw):
            return lambda fn: fn

    mcp = FakeMCP()
    register_all_skills(mcp)

    registered_names = set(registered_tools.keys())
    missing = EXPECTED_TOOLS - registered_names
    assert not missing, f"Missing tools after registration: {missing}"
