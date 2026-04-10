# Plan: Tool Description Enrichment for ToolSearch Discovery

**Date:** 2026-03-20
**Branch:** optimize
**Status:** planning

## Background

We compressed tool descriptions ~30% in commit `a78d308` (Mar 4) to reduce
context consumption. ToolSearch had already shipped in Claude Code v2.1.7
(Jan 14) — we didn't know. The compression removed keywords ToolSearch uses
for matching, hurting discovery while solving a problem ToolSearch had
already solved.

We also built generic tools (`list_model_objects`, `get_object_fields`,
`set_object_property`) in commits `65bee92`/`cbfba81` and removed 6 typed
list tools (Phase C). The remaining typed tools should stay — they're more
discoverable than generic equivalents.

See `docs/development-process-findings.md` for full timeline and lessons.

## Goal

Enrich all 85 tools with short descriptions (<60 char first line) to
maximize ToolSearch discoverability. No tool count changes. No architecture
changes.

## Files to Change

### 1. Tool description files (22 files)

Every `mcp_server/skills/*/tools.py` needs description enrichment.
Recover useful keywords from pre-compression descriptions
(`git diff a78d308^..a78d308`) and add domain terms.

| File | Tools to enrich | Priority |
|------|----------------|----------|
| `building/tools.py` | get_building_info, get_model_summary | High |
| `model_management/tools.py` | load_osm_model, save_osm_model, list_files, inspect_osm_summary | High |
| `simulation/tools.py` | run_simulation, run_osw, get_run_status, get_run_logs, get_run_artifacts, cancel_run, validate_osw, validate_model | High |
| `results/tools.py` | extract_summary_metrics, read_file, copy_file, extract_end_use_breakdown, extract_envelope_summary, extract_hvac_sizing, extract_zone_summary, extract_component_sizing, query_timeseries, extract_simulation_errors, list_output_variables, compare_runs | High |
| `common_measures/tools.py` | adjust_thermostat_setpoints, replace_window_constructions, enable_ideal_air_loads, clean_unused_objects, change_building_location, set_thermostat_schedules, replace_thermostat_schedules, shift_schedule_time, add_rooftop_pv, add_pv_to_shading, add_ev_load, add_zone_ventilation, set_lifecycle_cost_params, add_cost_per_floor_area, set_adiabatic_boundaries, list_common_measures | Medium |
| `hvac_systems/tools.py` | add_baseline_system, list_baseline_systems, get_baseline_system_info, replace_air_terminals, replace_zone_terminal, add_doas_system, add_vrf_system, add_radiant_system | Medium |
| `component_properties/tools.py` | all 10 get/set tools | Medium |
| `loop_operations/tools.py` | all 9 tools | Medium |
| `hvac/tools.py` | all 7 tools | Medium |
| `geometry/tools.py` | list_surfaces, get_surface_details, list_subsurfaces, create_surface, create_subsurface, create_space_from_floor_print, match_surfaces, set_window_to_wall_ratio, import_floorspacejs | Medium |
| `spaces/tools.py` | list_spaces, get_space_details, list_thermal_zones, get_thermal_zone_details, create_space, create_thermal_zone | Medium |
| `constructions/tools.py` | list_materials, get_construction_details, create_standard_opaque_material, create_construction, assign_construction_to_surface | Lower |
| `loads/tools.py` | get_load_details, create_people_definition, create_lights_definition, create_electric_equipment, create_gas_equipment, create_infiltration | Lower |
| `schedules/tools.py` | get_schedule_details, create_schedule_ruleset | Lower |
| `space_types/tools.py` | get_space_type_details | Lower |
| `weather/tools.py` | list_weather_files, get_weather_info, add_design_day, get_simulation_control, set_simulation_control, get_run_period, set_run_period | Lower |
| `measures/tools.py` | list_measure_arguments, apply_measure | Lower |
| `measure_authoring/tools.py` | list_custom_measures, test_measure, edit_measure | Lower |
| `comstock/tools.py` | list_comstock_measures, create_bar_building, create_typical_building, create_new_building | Lower |
| `simulation_outputs/tools.py` | add_output_variable, add_output_meter | Lower |
| `object_management/tools.py` | delete_object, rename_object | Lower |
| `server_info/tools.py` | get_server_status, get_versions | Lower |

### 2. Documentation updates

| File | Change |
|------|--------|
| `README.md` | Update tool count 134→142, update stats line, add supported clients section with ToolSearch note, add Cursor/Windsurf compatibility note |
| `CLAUDE.md` | Update tool count 138→142 |
| `mcp_server/server.py` | Update instructions string tool count 138→142 |
| `docs/llm-test-benchmark.md` | Already current |

### 3. Test files

| File | Change |
|------|--------|
| `tests/test_tool_baseline.py` | Add `test_min_description_length` — every tool first line ≥ 40 chars |
| New: `tests/test_toolsearch_discovery.py` | ToolSearch discoverability sweep — parameterized test per tool, query ToolSearch with natural language, verify tool appears in results. Requires Docker + ENABLE_TOOL_SEARCH. |

### 4. Description enrichment pattern

Recover from pre-compression (`git diff a78d308^..a78d308`), add domain terms:

**Before (current compressed):**
```python
"""Get building-level attributes (floor area, people/lighting/equipment densities, orientation)."""
```

**After (enriched):**
```python
"""Get building-level attributes: total floor area, conditioned floor area,
exterior wall area, people density, lighting power density, equipment power
density, infiltration rate, north axis orientation, standards building type,
number of stories.

Use to check the building overview, verify areas, or compare densities
before simulation.
"""
```

Rules:
- First line: concise summary (keep existing)
- Second paragraph: keyword-rich content (field lists, use cases, domain terms)
- No boilerplate: no "Requires model loaded", no "Returns dict with ok"
- Keep Args section unchanged
- Add domain terms energy modelers search for

### 5. README supported clients section

Add after "Other MCP Hosts":

```markdown
### Client Compatibility

| Client | Status | Notes |
|--------|--------|-------|
| Claude Desktop | Full support | All 142 tools available |
| Claude Code | Full support | ToolSearch auto-defers tools for efficient discovery |
| VS Code Copilot | Compatible | MCP support via config |
| Windsurf | Compatible | 100-tool limit — works with current count |
| Cursor | Not compatible | 40-tool hard cap — requires server split (see docs/plans/plan-multi-mcp-split.md) |
| Gemini CLI | Compatible | Use includeTools/excludeTools if needed |
| OpenAI API | Compatible | Use defer_loading for best results |
```

## Implementation Order

1. Enrich descriptions — 22 tools.py files, recover from git diff + add domain terms
2. Update README — tool counts, client compatibility section
3. Update CLAUDE.md + server.py — tool counts
4. Add `test_min_description_length` to test_tool_baseline.py
5. Docker rebuild (required for ToolSearch to index new descriptions)
6. Run unit tests — verify no breakage
7. Run LLM test_09 — verify discovery improvement
8. Full LLM regression — verify ≥95.9%

## Unresolved

- Should ToolSearch discoverability sweep test be in CI (needs Docker + claude CLI) or manual only?
- How much description is optimal? Need to test if very long descriptions dilute keyword matching
- Pre-compression descriptions available via `git show a78d308^:mcp_server/skills/*/tools.py` — cherry-pick useful keywords
