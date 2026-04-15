# Windsurf (Cascade) Setup

> **Last verified:** April 2026 · Windsurf latest · [Docs](https://docs.windsurf.com/windsurf/cascade/mcp)

Windsurf's Cascade AI supports MCP via a global config file. The **100-tool hard limit** means openstudio-mcp is not plug-and-play — you must disable at least 42 tools before Cascade will connect. This guide covers which tools to keep for common BEM workflows.

---

## Prerequisites

- **Docker Desktop** running
- **Windsurf** installed ([download](https://windsurf.com/download))
- openstudio-mcp image built: `docker build -t openstudio-mcp:dev -f docker/Dockerfile .`

---

## Configuration

Edit (or create) `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "openstudio-mcp": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/absolute/path/to/your/inputs:/inputs",
        "-v", "/absolute/path/to/your/runs:/runs",
        "-e", "OPENSTUDIO_MCP_MODE=prod",
        "openstudio-mcp:dev", "openstudio-mcp"
      ]
    }
  }
}
```

After saving, open the **MCP panel** in Windsurf (click the MCPs icon in the top-right Cascade panel). The openstudio-mcp server will appear but will be over the 100-tool limit. Proceed to tool selection below.

---

## Selecting Tools (Required)

Cascade has a hard cap of 100 active tools across all MCP servers. From the MCP settings page, toggle tools off until you are at or below 100. The table below shows a **recommended 80-tool starter set** organized by workflow.

### Always Keep (Core — 22 tools)

| Tool | Why |
|------|-----|
| `list_skills`, `get_skill` | Workflow guides — most important for BEM orientation |
| `get_server_status`, `get_versions` | Health checks |
| `load_osm_model`, `save_osm_model`, `create_example_osm`, `create_baseline_osm` | Model load/save |
| `get_model_summary`, `get_building_info` | Model inspection |
| `list_thermal_zones`, `list_spaces`, `list_air_loops`, `list_plant_loops` | Inventory tools |
| `run_simulation`, `get_run_status` | Simulation |
| `extract_summary_metrics`, `extract_end_use_breakdown` | Results |
| `validate_model` | Pre-sim QA |
| `recommend_tools` | Tool router |
| `change_building_location` | Weather setup |

### Add by Workflow

| Workflow | Additional Tools to Enable |
|----------|--------------------------|
| New building from scratch | `create_new_building`, `create_bar_building`, `create_typical_building` |
| HVAC changes | `add_baseline_system`, `list_baseline_systems`, `add_air_loop`, `list_zone_hvac_equipment`, `set_component_properties` |
| Envelope work | `list_surfaces`, `list_subsurfaces`, `replace_window_constructions`, `get_construction_details`, `list_materials` |
| Measures | `create_measure`, `test_measure`, `apply_measure`, `list_custom_measures` |
| Results deep-dive | `extract_hvac_sizing`, `extract_envelope_summary`, `extract_zone_summary`, `compare_runs`, `generate_results_report` |
| Schedules/loads | `list_thermal_zones` (detailed), `adjust_thermostat_setpoints`, `get_schedule_details` |

### Safe to Disable

Low-use tools that can be re-enabled on demand:
- `add_pv_to_shading`, `add_rooftop_pv`, `add_ev_load` — renewables
- `set_lifecycle_cost_params`, `add_cost_per_floor_area` — lifecycle costing
- `set_adiabatic_boundaries` — special boundary conditions
- `inspect_osm_summary`, `validate_osw`, `run_osw` — raw file operations
- `import_floorspacejs` — only if not doing custom geometry imports
- `add_design_day` — only if not defining custom design days

---

## Verification

After configuring your tool selection:

1. Restart Windsurf or click "Refresh" in the MCP panel
2. Confirm the tool count shows ≤ 100 in the panel
3. Send a test prompt in Cascade:

   > *"Use the openstudio MCP tools to list the available skills."*

---

## First Prompts

```
"Create a baseline 5-zone office building with VAV reheat using openstudio-mcp"
"Load /inputs/MyBuilding.osm and tell me about its HVAC system"
"Run a simulation on /runs/model.osm and extract the EUI"
```

---

## Context & Performance Notes

Windsurf puts all enabled tool schemas into context without deferral, similar to Claude Desktop. With a curated 80-tool set, schema overhead is approximately **9–11K tokens**. See [Token Context & Performance](./token-context-performance.md).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| "Tool limit exceeded" error | More than 100 tools enabled | Disable tools via MCP settings panel |
| Server listed but tools not available | Tool count > 100 (Cascade rejects the whole server) | Must disable tools before connecting |
| Config not picked up | Wrong path | Confirm `~/.codeium/windsurf/mcp_config.json` — note: `windsurf/` subdirectory, not `codeium/` directly |
| Cascade uses its own tools instead of MCP | Prompt doesn't mention MCP | Include "use openstudio-mcp" or "use the openstudio tools" in your prompt |
