from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.skills import register_all_skills

mcp = FastMCP(
    "openstudio-mcp",
    instructions=(
        "Building energy simulation server (OpenStudio SDK) with 142 tools for "
        "creating, modifying, simulating, and analyzing building energy models. "
        "Use these tools for all building energy modeling tasks — if no tool "
        "exists for a task, ask the user before writing code. "
        "NEVER write scripts, code, or files to accomplish tasks that these "
        "tools already handle. Specifically: "
        "- Measures: ALWAYS use create_measure — never write measure.rb/.py/.xml "
        "directly. create_measure handles scaffolding, XML, checksums, and "
        "OS App compatibility. Workflow: create_measure → test_measure → apply_measure. "
        "- Results/data: use extract_summary_metrics, extract_end_use_breakdown, "
        "query_timeseries, extract_envelope_summary, extract_hvac_sizing — "
        "never write Python/SQL scripts to parse eplusout.sql. "
        "- Visualization: use view_model (3D geometry), view_simulation_data "
        "(charts/heatmaps), generate_results_report (HTML report) — never write "
        "matplotlib/plotly/HTML scripts. "
        "- Models: use create_new_building, create_bar_building, import_floorspacejs "
        "— never write raw IDF or OSM files. "
        "- Weather: use change_building_location (sets EPW+DDY+CZ in one call) "
        "or list_weather_files — never download or write weather files. "
        "- HVAC: use add_baseline_system, add_doas_system, add_vrf_system — "
        "never write OpenStudio SDK scripts to wire HVAC components. "
        "For custom HVAC measures, call search_wiring_patterns to get working "
        "Ruby wiring code, and search_api to verify methods exist. "
        "If a file path is given, use it directly. If a file operation fails, "
        "you may call list_files once to find the right path, then retry — "
        "do not call list_files more than once for the same file. "
        "Use list_weather_files for EPW discovery — do not use list_files for weather. "
        "To find objects by type, use list_model_objects(object_type). "
        "List tools default to 10 results — use filters to narrow, or "
        "max_results=0 for all. Prefer list tools before detail tools to "
        "find the right name. "
        "When polling get_run_status, wait at least 1-2 minutes between calls. "
        "For multi-step workflows, call list_skills() first."
    ),
)

register_all_skills(mcp)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
