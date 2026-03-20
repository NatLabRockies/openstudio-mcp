# Plan: Tool Description Usage Guidance

**Date:** 2026-03-20
**Branch:** optimize
**Status:** planning

## Problem

Audit of 142 tool descriptions against Anthropic's best practices:

| Criterion | Current | Target |
|-----------|---------|--------|
| No when-to-use guidance | 116/142 (82%) | 0 |
| No negative scope | 132/142 (93%) | ~40-50 (tools with confusion targets) |
| Short (<150 chars) | 26/142 (18%) | 0 |
| Has emphasis keywords | 3/142 (2%) | ~15-20 (bypass-prone tools) |
| Has examples | 48/142 (34%) | ~80+ |

Anthropic's guidance: "Provide extremely detailed descriptions. This is by
far the most important factor in tool performance." Each description should
cover what it does, when to use it, when NOT to use it, and parameter
examples. Aim for 3-4 sentences minimum.

## What to Add

### 1. When-to-use guidance (116 tools)

One line per tool: "Use when [scenario]." or "Use to [action]."

Not a formula — each should match the natural language an energy modeler
would use. The L1 failure analysis shows the gap:

| L1 Failure | User says | Tool should say |
|------------|-----------|----------------|
| run_qaqc_L1 | "Check model for issues" | "Use after simulation to check model quality" |
| check_loads_L1 | "What loads?" | "Use to inspect people, lights, equipment, infiltration on a space" |
| replace_windows_L1 | "Upgrade the windows" | "Use to upgrade or replace all window constructions at once" |
| thermostat_L1 | "Change thermostat settings" | "Use to raise or lower heating/cooling setpoints" |

### 2. Negative scope (tools with confusion targets)

Not every tool needs this — only where two tools could be confused:

| Tool | Confused with | Add |
|------|-------------|-----|
| `run_qaqc_checks` | `validate_model` | "Requires completed simulation. For pre-sim checks, use validate_model." |
| `validate_model` | `run_qaqc_checks` | "Pre-simulation only. For post-sim QA/QC, use run_qaqc_checks." |
| `get_load_details` | `get_space_details` | "Returns load-specific fields. For space geometry, use get_space_details." |
| `get_object_fields` | `get_component_properties` | "Works with ANY type. For HVAC components with typed properties, get_component_properties is more structured." |
| `list_model_objects` | typed list tools | "Works with any OpenStudio type. For common types, typed tools (list_spaces, list_air_loops) provide more detail." |
| `extract_summary_metrics` | `extract_end_use_breakdown` | "Returns EUI + unmet hours only. For per-category breakdown, use extract_end_use_breakdown." |
| `inspect_osm_summary` | `get_model_summary` | "Reads from disk without loading. If model already loaded, use get_model_summary." |
| `copy_file` | `read_file` | "Copies to /runs for host access. To read contents, use read_file." |
| `list_files` | `list_weather_files` | Already has this. |
| `create_baseline_osm` | `create_new_building` | "For testing/demos. For production models, use create_new_building." |
| `create_example_osm` | `create_baseline_osm` | "Minimal single-zone demo. For multi-zone baseline, use create_baseline_osm." |
| `apply_measure` | `create_measure` | "Runs an existing measure. To create a new measure, use create_measure." |
| `set_thermostat_schedules` | `replace_thermostat_schedules` | "Sets schedules if none exist. To overwrite existing, use replace_thermostat_schedules." |
| `replace_thermostat_schedules` | `set_thermostat_schedules` | "Overwrites existing schedules. To set on unassigned zones, use set_thermostat_schedules." |
| `add_output_variable` | `add_output_meter` | "For zone/surface-level variables. For whole-building energy meters, use add_output_meter." |
| `add_output_meter` | `add_output_variable` | "For facility-level energy tracking. For zone/surface variables, use add_output_variable." |

### 3. Emphasis keywords (bypass-prone tools)

Only on tools with known bypass patterns (FM1/FM2/FM3):

| Tool | Add |
|------|-----|
| `create_measure` | Already has "ALWAYS use this tool" |
| `view_model` | Already has "Use this instead of writing matplotlib/plotly" |
| `view_simulation_data` | Already has "Use this instead of..." |
| `generate_results_report` | Already has "Use this instead of..." |
| `read_file` | Already has "/inputs and /runs are inside the MCP container" |
| `run_simulation` | Add "IMPORTANT: requires weather file and design days" |
| `extract_summary_metrics` | Add "ALWAYS use this for EUI — do not parse eplusout.sql manually" |
| `search_api` | Add "IMPORTANT: call before writing measures with SDK method calls" |
| `add_baseline_system` | Add "ALWAYS use this for ASHRAE systems — do not write HVAC setup scripts" |
| `save_osm_model` | Add "IMPORTANT: save after modifications to persist changes" |
| `change_building_location` | Already has "IMPORTANT: EPW must have companion .stat and .ddy" |
| `list_skills` | Already has "IMPORTANT: Call this FIRST" |

### 4. Short descriptions to expand (26 tools)

These need 1-2 additional lines:

**Simulation/run tools (9):**
- `get_run_period`, `get_simulation_control`, `get_weather_info`,
  `cancel_run`, `get_run_artifacts`, `get_run_logs`, `get_run_status` (already covered above),
  `validate_model`

**Detail/get tools (11):**
- `get_air_loop_details`, `get_plant_loop_details`, `get_zone_hvac_details`,
  `get_space_details`, `get_thermal_zone_details`, `get_surface_details`,
  `get_construction_details`, `get_sizing_system_properties`,
  `get_sizing_zone_properties`, `get_baseline_system_info`

**Other (6):**
- `get_server_status`, `get_versions`, `enable_ideal_air_loads`,
  `match_surfaces`, `set_lifecycle_cost_params`, `create_example_osm`,
  `extract_envelope_summary`, `extract_hvac_sizing`, `extract_zone_summary`

## Files to Change

All 22 `mcp_server/skills/*/tools.py` files — same set as the keyword
enrichment pass. No new files, no architecture changes.

## Implementation Pattern

For each tool, add 1-2 lines after the first-line summary:

```python
"""Get building-level attributes: total floor area, conditioned floor area,
exterior wall area, people density, lighting power density, equipment power
density, infiltration rate, north axis orientation, standards building type,
number of stories.

Use to check the building overview before simulation or compare densities.
For detailed space-level info, use get_space_details instead.
"""
```

Pattern:
- Line 1: What it does (existing, keep)
- Line 2-3: Keywords/fields (existing from enrichment, keep)
- New line: "Use [when/to] [scenario]."
- New line (where applicable): "For [alternative scenario], use [other tool] instead."

## Prioritization

**Tier 1 — Core workflow tools (23):** These are called in every session.
When-to-use + negative scope where confusion exists.

**Tier 2 — HVAC tools (35):** Most complex domain. When-to-use + emphasis
on tools with bypass patterns (add_baseline_system).

**Tier 3 — Results tools (15):** When-to-use + distinguish between the
many extract_* tools.

**Tier 4 — Everything else (69):** When-to-use line. Negative scope only
where confusion targets exist.

## Testing

- `test_tool_baseline.py::test_min_description_length` — still passes (≥40 chars)
- New: `test_when_to_use_coverage` — every tool has "use" in description
- Full LLM suite — compare against Run 12 (163/170, 95.9%)
- Targeted: re-run L1 failures to see if descriptions help

## Risks

- **Over-engineering descriptions** may dilute keywords for ToolSearch.
  Each added line is more text to match against — could reduce precision.
- **Diminishing returns** — Run 12 showed 95.9% unchanged after keyword
  enrichment. Usage guidance may also plateau.
- **Description bloat** — long descriptions consume more tokens when loaded
  by ToolSearch. The auto-deferral threshold (10% context) may shift.
- **False confidence** — "ALWAYS use this" on too many tools reduces
  the signal strength of emphasis keywords.

## Unresolved

- Should we measure ToolSearch precision before/after? (adding text may hurt matching)
- How many "IMPORTANT" markers before they lose effectiveness?
- Should negative scope be "For X, use Y instead" or "Does not do X"?
- Do L1 failures even matter? They're vague prompts where multiple tools are correct.
