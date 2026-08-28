"""Verify that skills auto-discovery registers all expected tools.

This is the critical Phase 1 test — it ensures the refactored skill
structure produces the exact same set of MCP tools as the old monolithic
server.py. If this passes, the migration is backward-compatible.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_server.skills import register_all_skills

pytestmark = pytest.mark.unit

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
    "repair_missing_roof_ceiling",
    "merge_coplanar_sliver_surfaces",
    "weld_coincident_vertices",
    "patch_missing_surfaces",
    "set_surface_boundary_conditions",
    "trim_overlapping_surfaces",
    "set_window_to_wall_ratio",
    "list_materials",
    "get_construction_details",
    "create_standard_opaque_material",
    "create_construction",
    "add_layer_to_construction",
    "assign_construction_to_surface",
    "get_schedule_details",
    "create_schedule_ruleset",
    "list_air_loops",
    "get_air_loop_details",
    "add_air_loop",
    "list_plant_loops",
    "get_plant_loop_details",
    "list_zone_hvac_equipment",
    "get_zone_hvac_details",
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
    "set_zone_equipment_priority",
    # Phase 6A: Loads
    "get_load_details",
    "create_people_definition",
    "create_lights_definition",
    "create_electric_equipment",
    "create_gas_equipment",
    "create_infiltration",
    # Phase 6B: Object Management
    "delete_object",
    "rename_object",
    "list_model_objects",
    "get_object_fields",
    "set_object_property",
    # Phase 6C: Weather, Design Days, SimControl, RunPeriod
    "list_weather_files",
    "get_weather_info",
    "add_design_day",
    "get_simulation_control",
    "set_simulation_control",
    "get_run_period",
    "set_run_period",
    # OpenStudio Server analysis workflows
    "openstudio_analysis_create_osa_json",
    "openstudio_analysis_validate_osa_json",
    "openstudio_analysis_default_output_variables",
    "openstudio_analysis_foundational_measures",
    "openstudio_analysis_algorithms",
    "openstudio_analysis_validate_package",
    "openstudio_analysis_preflight_seed",
    "openstudio_analysis_prepare_package",
    "openstudio_analysis_create_osa_json_from_measures",
    "openstudio_analysis_add_measure_to_osa_json",
    "openstudio_analysis_create_project",
    "openstudio_analysis_submit",
    "openstudio_analysis_status",
    "openstudio_analysis_start",
    "openstudio_analysis_start_sampled_run",
    "openstudio_analysis_wait",
    "openstudio_analysis_test_server_config",
    "openstudio_analysis_download_data",
    "openstudio_analysis_results_json",
    "openstudio_analysis_submit_wait_download",
    # Phase 6D: Measures
    "list_local_measures",
    "find_measure",
    "search_bcl_measures",
    "list_measure_arguments",
    "download_measure_from_bcl",
    "apply_measure",
    "list_custom_measures",
    "create_measure",
    "test_measure",
    "edit_measure",
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
    # Run retention / disk management
    "cleanup_runs",
    "delete_run",
    "pin_run",
    "unpin_run",
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
    # Phase 10: Results & Error Management
    "extract_simulation_errors",
    "list_output_variables",
    "compare_runs",
    "validate_model",
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
    # Python EMS (EnergyPlus Python Plugins)
    "create_python_plugin",
    "get_python_plugin",
    "edit_python_plugin",
    "list_ems_actuators",
    "install_plugin_packages",
    # Skill Discovery
    "list_skills",
    "get_skill",
    "get_skill_file",
    # API Reference
    "search_api",
    "search_wiring_patterns",
    # Tool Router
    "recommend_tools",
    # File Transfer (remote/HTTP — get user files to/from the server)
    "request_upload",
    "get_upload",
    "list_uploads",
    "delete_upload",
    "request_download",
    # gbXML Import (Revit gbXML -> OSM via gbxml-to-openstudio measures)
    "import_gbxml",
    "repair_and_validate_gbxml_geometry",
    # Space Type Assignment (post-gbXML standards attribution)
    "assign_space_type_simple",
    "start_space_type_wizard",
    "choose_space_type_templates",
    "choose_space_type_building_types",
    "get_space_type_wizard_status",
    "assign_space_type_batch",
    "finish_space_type_wizard",
    "cancel_space_type_wizard",
}


def test_all_skills_registered():
    # Validates: auto-discovery finds all skill modules and registers them by name
    """All expected skills are discovered and registered."""
    mcp = MagicMock()
    # mcp.tool() must return a decorator that returns the function
    mcp.tool.return_value = lambda fn: fn

    skills = register_all_skills(mcp)

    for expected_skill in ("server_info", "model_management", "simulation", "results"):
        assert expected_skill in skills, f"Skill '{expected_skill}' not discovered"


def test_all_tool_names_registered():
    # Validates: all expected tools are registered, no extras — migration backward-compatibility
    """Every expected tool function is registered via mcp.tool()."""
    registered_tools = {}

    class FakeMCP:
        def tool(self, name=None, **kwargs):
            def decorator(fn):
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

    extra = registered_names - EXPECTED_TOOLS
    assert not extra, f"Unexpected tools not in EXPECTED_TOOLS: {extra}"


# The exact roster removed by the benchmark ablation arm (reviewer-response
# plan D3) — keep in lockstep with _KNOWLEDGE_SKILLS in mcp_server/skills.
KNOWLEDGE_TOOLS = {"list_skills", "get_skill", "get_skill_file", "recommend_tools"}


def test_knowledge_skills_ablation_flag(monkeypatch):
    # Validates: OSMCP_DISABLE_KNOWLEDGE_SKILLS=1 removes exactly the 3
    # knowledge-layer tools (benchmark ablation arm) and nothing else
    registered_tools = {}

    class FakeMCP:
        def tool(self, name=None, **kwargs):
            def decorator(fn):
                registered_tools[name or fn.__name__] = fn
                return fn
            return decorator
        def prompt(self, **kw):
            return lambda fn: fn
        def resource(self, *a, **kw):
            return lambda fn: fn

    monkeypatch.setenv("OSMCP_DISABLE_KNOWLEDGE_SKILLS", "1")
    skills = register_all_skills(FakeMCP())

    assert "skill_discovery" not in skills and "tool_router" not in skills
    registered_names = set(registered_tools.keys())
    assert registered_names == EXPECTED_TOOLS - KNOWLEDGE_TOOLS, (
        f"Ablation must remove exactly {KNOWLEDGE_TOOLS}; "
        f"diff: missing={EXPECTED_TOOLS - KNOWLEDGE_TOOLS - registered_names}, "
        f"extra={registered_names - (EXPECTED_TOOLS - KNOWLEDGE_TOOLS)}"
    )

    # Validates: the ToolDescriptor collector sees the same ablated roster —
    # catalog/router surfaces built from it exclude exactly the knowledge
    # skills' descriptors, nothing else (plan PR 5)
    from mcp_server.tool_registry import descriptors

    collected = descriptors()
    assert set(collected) == EXPECTED_TOOLS - KNOWLEDGE_TOOLS
    assert not {d.package for d in collected.values()} & {
        "skill_discovery", "tool_router",
    }


def test_export_tool_table_matches_expected_roster():
    # Validates: the paper's Table 1 exporter groups every EXPECTED_TOOLS
    # entry under exactly one skill — the artifact counts equal the roster
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from export_tool_table import collect_tools_by_skill

    by_skill = collect_tools_by_skill()
    flat = [t for tools in by_skill.values() for t in tools]
    assert len(flat) == len(set(flat)), "a tool is attributed to two skills"
    assert set(flat) == EXPECTED_TOOLS, (
        f"missing={EXPECTED_TOOLS - set(flat)}, extra={set(flat) - EXPECTED_TOOLS}"
    )
    assert len(by_skill) >= 20, f"suspiciously few skills: {sorted(by_skill)}"
