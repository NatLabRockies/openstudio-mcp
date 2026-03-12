"""MCP prompts and resources for openstudio-mcp.

Prompts: reusable workflow templates that guide LLMs through multi-tool
sequences (exposed via prompts/list, prompts/get).

Resources: read-only reference data (exposed via resources/list,
resources/read).
"""
from __future__ import annotations

import json

from mcp_server.skills.hvac_systems.catalog import (
    BASELINE_SYSTEMS,
    MODERN_TEMPLATES,
)


def register(mcp):
    # ------------------------------------------------------------------
    # Prompts — workflow templates for common energy modeling tasks
    # ------------------------------------------------------------------

    @mcp.prompt(
        name="baseline_comparison",
        description=(
            "Compare two ASHRAE 90.1 baseline HVAC systems on the same "
            "building geometry. Returns a step-by-step tool sequence."
        ),
    )
    def baseline_comparison_prompt(
        system_a: str = "03",
        system_b: str = "07",
        climate_city: str = "Chicago",
    ) -> str:
        return (
            f"Compare ASHRAE baseline System {system_a} vs System {system_b} "
            f"for a 10-zone office in {climate_city}.\n\n"
            "Steps:\n"
            f'1. create_new_building(building_type="SmallOffice", '
            f'weather_file="/inputs/{climate_city}.epw")\n'
            f'2. add_baseline_system(system_type="{system_a}")\n'
            "3. save_osm_model() and run_simulation()\n"
            "4. extract_summary_metrics() — note EUI and unmet hours\n"
            f'5. Repeat steps 1-4 with system_type="{system_b}"\n'
            "6. Compare EUI, heating/cooling energy, and unmet hours"
        )

    @mcp.prompt(
        name="envelope_retrofit",
        description=(
            "Upgrade wall insulation on an existing model — create "
            "materials, build a construction, assign to exterior walls."
        ),
    )
    def envelope_retrofit_prompt(
        r_value: str = "R-20",
        surface_type: str = "exterior walls",
    ) -> str:
        return (
            f"Upgrade {surface_type} to {r_value} insulation.\n\n"
            "Steps:\n"
            "1. load_osm_model(osm_path=<your model>)\n"
            "2. list_constructions() — review current assemblies\n"
            "3. list_surfaces() — find exterior walls\n"
            '4. create_standard_opaque_material(name="New_Insulation", '
            "thickness_m=0.089, conductivity_w_m_k=0.04, "
            "density_kg_m3=30, specific_heat_j_kg_k=1000)\n"
            '5. create_construction(name="High_R_Wall", '
            'material_names=["Exterior Finish", "New_Insulation", '
            '"Gypsum Board"])\n'
            "6. assign_construction_to_surface() for each exterior wall\n"
            "7. save_osm_model()"
        )

    @mcp.prompt(
        name="full_building_simulation",
        description=(
            "Build a complete energy model from scratch — baseline "
            "geometry, loads, weather, design days — then simulate."
        ),
    )
    def full_building_simulation_prompt(
        system_type: str = "05",
        climate_city: str = "Chicago",
    ) -> str:
        return (
            f"Create a full building model with ASHRAE System {system_type} "
            f"in {climate_city}, add loads, and simulate.\n\n"
            "Steps:\n"
            f'1. create_new_building(building_type="SmallOffice", '
            f'weather_file="/inputs/{climate_city}.epw")\n'
            "2. list_spaces() — verify geometry and loads\n"
            "3. save_osm_model() and run_simulation()\n"
            "4. Poll get_run_status() until complete\n"
            "5. extract_summary_metrics() — review EUI and unmet hours"
        )

    @mcp.prompt(
        name="results_deep_dive",
        description=(
            "Extract structured results from a completed simulation — "
            "energy breakdown, envelope, HVAC sizing, and timeseries."
        ),
    )
    def results_deep_dive_prompt(run_id: str = "<run_id>") -> str:
        return (
            f"Extract all results from simulation run {run_id}.\n\n"
            "Steps:\n"
            f'1. extract_summary_metrics(run_id="{run_id}") — EUI overview\n'
            f'2. extract_end_use_breakdown(run_id="{run_id}") — '
            "energy by fuel/end-use\n"
            f'3. extract_envelope_summary(run_id="{run_id}") — '
            "wall/window U-values\n"
            f'4. extract_hvac_sizing(run_id="{run_id}") — '
            "autosized capacities\n"
            f'5. extract_zone_summary(run_id="{run_id}") — '
            "per-zone conditions\n"
            f'6. extract_component_sizing(run_id="{run_id}", '
            'component_type="Coil")\n'
            f'7. query_timeseries(run_id="{run_id}", '
            'variable_name="Electricity:Facility", frequency="Monthly")'
        )

    @mcp.prompt(
        name="typical_building_from_standards",
        description=(
            "Apply ASHRAE 90.1 standards template to a model with "
            "geometry — adds constructions, loads, HVAC, and schedules."
        ),
    )
    def typical_building_prompt(
        template: str = "90.1-2019",
        climate_zone: str = "ASHRAE 169-2013-5A",
    ) -> str:
        return (
            f"Apply {template} standards template for climate zone "
            f"{climate_zone}.\n\n"
            "Steps:\n"
            "1. load_osm_model(osm_path=<model with geometry>)\n"
            "2. change_building_location(weather_file=<matching EPW>)\n"
            f'3. create_typical_building(template="{template}", '
            f'climate_zone="{climate_zone}")\n'
            "4. get_model_summary() — verify what was added\n"
            "5. list_air_loops() — inspect HVAC\n"
            "6. list_constructions() — inspect envelope\n"
            "7. save_osm_model()"
        )

    @mcp.prompt(
        name="model_qaqc",
        description=(
            "Quality check a model before simulation — verify zones, "
            "HVAC, weather, constructions, and run period."
        ),
    )
    def model_qaqc_prompt() -> str:
        return (
            "Pre-flight quality check before running a simulation.\n\n"
            "Steps:\n"
            "1. get_model_summary() — overall object counts\n"
            "2. list_thermal_zones() — verify all zones exist\n"
            "3. list_air_loops() — verify HVAC serves zones\n"
            "4. list_constructions() — verify envelope is defined\n"
            "5. get_weather_info() — verify weather file is set\n"
            "6. get_run_period() — verify simulation period\n"
            "7. get_simulation_control() — check sizing flags\n"
            "8. run_qaqc_checks() — automated diagnostics\n"
            "9. Report any issues found before proceeding"
        )

    # ------------------------------------------------------------------
    # Resources — read-only reference data
    # ------------------------------------------------------------------

    @mcp.resource(
        "openstudio://ashrae-baseline-systems",
        name="ASHRAE 90.1 Baseline Systems",
        description=(
            "Reference table of all 10 ASHRAE 90.1 Appendix G baseline "
            "HVAC system types with heating, cooling, and distribution info."
        ),
        mime_type="application/json",
    )
    def ashrae_baseline_systems_resource() -> str:
        return json.dumps(BASELINE_SYSTEMS, indent=2)

    @mcp.resource(
        "openstudio://modern-hvac-templates",
        name="Modern HVAC Templates",
        description=(
            "Reference table of modern HVAC system templates available "
            "beyond ASHRAE baselines (DOAS, VRF, Radiant)."
        ),
        mime_type="application/json",
    )
    def modern_templates_resource() -> str:
        return json.dumps(MODERN_TEMPLATES, indent=2)

    @mcp.resource(
        "openstudio://common-materials",
        name="Common Building Materials",
        description=(
            "Thermal properties of common building materials for use "
            "with create_standard_opaque_material()."
        ),
        mime_type="application/json",
    )
    def common_materials_resource() -> str:
        materials = {
            "concrete": {
                "conductivity_w_m_k": 1.7,
                "density_kg_m3": 2400,
                "specific_heat_j_kg_k": 900,
            },
            "insulation_fiberglass": {
                "conductivity_w_m_k": 0.04,
                "density_kg_m3": 30,
                "specific_heat_j_kg_k": 1000,
            },
            "insulation_xps": {
                "conductivity_w_m_k": 0.029,
                "density_kg_m3": 35,
                "specific_heat_j_kg_k": 1500,
            },
            "insulation_polyiso": {
                "conductivity_w_m_k": 0.022,
                "density_kg_m3": 32,
                "specific_heat_j_kg_k": 1400,
            },
            "gypsum_board": {
                "conductivity_w_m_k": 0.16,
                "density_kg_m3": 800,
                "specific_heat_j_kg_k": 1090,
            },
            "wood": {
                "conductivity_w_m_k": 0.15,
                "density_kg_m3": 600,
                "specific_heat_j_kg_k": 1600,
            },
            "steel": {
                "conductivity_w_m_k": 50.0,
                "density_kg_m3": 7800,
                "specific_heat_j_kg_k": 500,
            },
            "brick": {
                "conductivity_w_m_k": 0.72,
                "density_kg_m3": 1920,
                "specific_heat_j_kg_k": 790,
            },
            "glass_clear": {
                "conductivity_w_m_k": 0.9,
                "density_kg_m3": 2500,
                "specific_heat_j_kg_k": 750,
            },
        }
        return json.dumps(materials, indent=2)

    @mcp.resource(
        "openstudio://tool-catalog",
        name="Tool Catalog",
        description=(
            "All MCP tools organized by skill, with descriptions."
        ),
        mime_type="application/json",
    )
    def tool_catalog_resource() -> str:
        catalog = {
            "server_info": ["get_server_status", "get_versions"],
            "model_management": [
                "create_example_osm", "create_baseline_osm",
                "inspect_osm_summary", "load_osm_model",
                "save_osm_model", "list_files",
            ],
            "simulation": [
                "validate_osw", "run_osw", "run_simulation",
                "get_run_status", "get_run_logs",
                "get_run_artifacts", "cancel_run",
            ],
            "results": [
                "extract_summary_metrics", "read_file",
                "copy_file", "extract_end_use_breakdown",
                "extract_envelope_summary", "extract_hvac_sizing",
                "extract_zone_summary", "extract_component_sizing",
                "query_timeseries",
            ],
            "building": [
                "get_building_info", "get_model_summary",
                "list_building_stories",
            ],
            "spaces": [
                "list_spaces", "get_space_details",
                "list_thermal_zones", "get_thermal_zone_details",
                "create_space", "create_thermal_zone",
            ],
            "geometry": [
                "list_surfaces", "get_surface_details",
                "list_subsurfaces", "create_surface",
                "create_subsurface", "create_space_from_floor_print",
                "match_surfaces", "set_window_to_wall_ratio",
                "import_floorspacejs",
            ],
            "constructions": [
                "list_materials", "list_constructions",
                "list_construction_sets",
                "create_standard_opaque_material",
                "create_construction",
                "assign_construction_to_surface",
            ],
            "schedules": [
                "list_schedule_rulesets", "get_schedule_details",
                "create_schedule_ruleset",
            ],
            "hvac": [
                "list_air_loops", "get_air_loop_details",
                "list_plant_loops", "get_plant_loop_details",
                "list_zone_hvac_equipment", "get_zone_hvac_details",
                "add_air_loop",
            ],
            "loads": [
                "get_load_details",
                "create_people_definition",
                "create_lights_definition",
                "create_electric_equipment",
                "create_gas_equipment", "create_infiltration",
            ],
            "space_types": [
                "list_space_types", "get_space_type_details",
            ],
            "simulation_outputs": [
                "add_output_variable", "add_output_meter",
            ],
            "hvac_systems": [
                "add_baseline_system", "list_baseline_systems",
                "get_baseline_system_info", "replace_air_terminals",
                "replace_zone_terminal", "add_doas_system",
                "add_vrf_system", "add_radiant_system",
            ],
            "component_properties": [
                "get_component_properties",
                "set_component_properties",
                "set_economizer_properties",
                "set_sizing_properties",
                "set_sizing_system_properties", "get_sizing_system_properties",
                "set_sizing_zone_properties", "get_sizing_zone_properties",
                "get_setpoint_manager_properties", "set_setpoint_manager_properties",
            ],
            "loop_operations": [
                "create_plant_loop",
                "add_supply_equipment", "remove_supply_equipment",
                "add_demand_component", "remove_demand_component",
                "add_zone_equipment", "remove_zone_equipment",
                "remove_all_zone_equipment",
            ],
            "object_management": [
                "delete_object", "rename_object",
                "list_model_objects", "get_object_fields",
                "set_object_property",
            ],
            "weather": [
                "get_weather_info",
                "add_design_day", "get_simulation_control",
                "set_simulation_control", "get_run_period",
                "set_run_period",
            ],
            "measures": [
                "list_measure_arguments", "apply_measure",
            ],
            "comstock": [
                "list_comstock_measures", "create_typical_building",
                "create_bar_building", "create_new_building",
            ],
            "common_measures": [
                "list_common_measures", "view_model",
                "view_simulation_data", "generate_results_report",
                "run_qaqc_checks", "adjust_thermostat_setpoints",
                "replace_window_constructions",
                "enable_ideal_air_loads", "clean_unused_objects",
                "change_building_location",
                "set_thermostat_schedules",
                "replace_thermostat_schedules",
                "shift_schedule_time", "add_rooftop_pv",
                "add_pv_to_shading", "add_ev_load",
                "add_zone_ventilation", "set_lifecycle_cost_params",
                "add_cost_per_floor_area", "set_adiabatic_boundaries",
            ],
            "skill_discovery": ["list_skills", "get_skill"],
        }
        return json.dumps(catalog, indent=2)
