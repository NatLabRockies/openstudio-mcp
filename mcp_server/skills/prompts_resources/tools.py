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
            "Compare two HVAC systems on the same building with "
            "standards-tuned equipment (decision-grade results). Returns a "
            "step-by-step tool sequence."
        ),
    )
    def baseline_comparison_prompt(
        system_a: str = "PSZ-AC with gas coil",
        system_b: str = "VAV chiller with gas boiler reheat",
        climate_city: str = "Chicago",
    ) -> str:
        # hvac_only swaps preserve loads/schedules between candidates, and the
        # standards path applies real equipment efficiencies and controls —
        # generic add_baseline_system templates are for wiring, not comparisons
        # (issue #97: they produced misleading EUI/comfort numbers)
        return (
            f"Compare HVAC system '{system_a}' vs '{system_b}' "
            f"for an office in {climate_city}, with decision-grade results.\n\n"
            "Steps:\n"
            f'1. create_new_building(building_type="SmallOffice", '
            f'weather_file="/inputs/{climate_city}.epw")  # builds typical model\n'
            f'2. create_typical_building(system_type="{system_a}", '
            'hvac_only=True)  # standards-tuned swap, loads untouched\n'
            '3. save_osm_model(save_name="sweep_a") and '
            "run_simulation(osm_path=<osm_path from save>)\n"
            "4. get_run_status(run_id=<id from run_simulation>) until complete\n"
            f'5. create_typical_building(system_type="{system_b}", '
            'hvac_only=True)  # swap to candidate B on the SAME model\n'
            '6. save_osm_model(save_name="sweep_b") and '
            "run_simulation(osm_path=<osm_path from save>)\n"
            "7. compare_runs(baseline_run_id=<run A id>, "
            "retrofit_run_id=<run B id>) — EUI, end uses, unmet hours\n\n"
            "Note: system_type takes openstudio-standards names — call "
            "create_typical_building's docs or list them via the tool schema. "
            "Do NOT use add_baseline_system for comparisons; it is a generic "
            "wiring template without standards efficiencies."
        )

    @mcp.prompt(
        name="envelope_retrofit",
        description=(
            "Upgrade wall insulation on an existing model — add an "
            "insulation layer to the existing construction and assign it."
        ),
    )
    def envelope_retrofit_prompt(
        r_value: str = "R-20",
        surface_type: str = "exterior walls",
    ) -> str:
        # Lead with add_layer_to_construction: rebuilding the assembly from a
        # hand-typed layer list silently drops the original layers (benchmark
        # F7 — every model made the roof WORSE replacing it with a bare slab)
        return (
            f"Upgrade {surface_type} to {r_value} insulation.\n\n"
            "Steps:\n"
            "1. load_osm_model(osm_path=<your model>)\n"
            "2. list_surfaces() — find the target surfaces and their "
            "current construction\n"
            "3. get_construction_details(construction_name=<current "
            "construction>) — review existing layers\n"
            '4. create_standard_opaque_material(name="New_Insulation", '
            "thickness_m=0.089, conductivity_w_m_k=0.04, "
            "density_kg_m3=30, specific_heat_j_kg_k=1000)\n"
            "5. add_layer_to_construction(construction_name=<current "
            'construction>, material_name="New_Insulation") — keeps all '
            "existing layers; verify assembly_r_si_after > before\n"
            "6. assign_construction_to_surface(surface_name=<target surface>, "
            "construction_name=<new construction>) for each target surface\n"
            '7. save_osm_model(save_name="retrofit") — the server picks a '
            "new path, never over a read-only input"
        )

    @mcp.prompt(
        name="full_building_simulation",
        description=(
            "Build a complete energy model from scratch — baseline "
            "geometry, loads, weather, design days — then simulate."
        ),
    )
    def full_building_simulation_prompt(
        system_type: str = "Inferred",
        climate_city: str = "Chicago",
    ) -> str:
        # system_type takes openstudio-standards names ("VAV chiller with gas
        # boiler reheat", ...); "Inferred" auto-selects by building type
        return (
            f"Create a full building model with HVAC system '{system_type}' "
            f"in {climate_city}, add loads, and simulate.\n\n"
            "Steps:\n"
            f'1. create_new_building(building_type="SmallOffice", '
            f'weather_file="/inputs/{climate_city}.epw", '
            f'system_type="{system_type}")\n'
            "2. list_spaces() — verify geometry and loads\n"
            '3. save_osm_model(save_name="full_building") and '
            "run_simulation(osm_path=<osm_path from save>)\n"
            "4. Poll get_run_status(run_id=<id from run_simulation>) "
            "until complete\n"
            "5. extract_summary_metrics(run_id=<id>) — review EUI and "
            "unmet hours"
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
            '6. list_model_objects(object_type="Construction") — inspect envelope\n'
            '7. save_osm_model(save_name="typical") — the server picks a '
            "path, never over a read-only input"
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
            '4. list_model_objects(object_type="Construction") — verify envelope is defined\n'
            "5. get_weather_info() — verify weather file is set\n"
            "6. get_run_period() — verify simulation period\n"
            "7. get_simulation_control() — check sizing flags\n"
            "8. validate_model() — automated pre-flight diagnostics "
            "(run_qaqc_checks needs a completed simulation)\n"
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
        # Derived from the registration collector — never hand-maintained.
        # Grouped by owning skill package; value is the tool's first
        # docstring line.
        from mcp_server.tool_registry import descriptors, ensure_collected

        ensure_collected()
        catalog: dict[str, dict[str, str]] = {}
        for d in sorted(descriptors().values(),
                        key=lambda d: (d.package, d.name)):
            catalog.setdefault(d.package, {})[d.name] = d.description
        return json.dumps(catalog, indent=2)
