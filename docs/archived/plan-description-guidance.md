# Plan: Tool Description Usage Guidance

**Date:** 2026-03-20
**Branch:** optimize
**Status:** planning

## Context: Two Conflicting Sets of Anthropic Guidance

**Pre-ToolSearch (mid-2024):** "Provide extremely detailed descriptions.
This is by far the most important factor in tool performance. Aim for at
least 3-4 sentences per tool description."
Source: [How to implement tool use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use)
Written for: all tools loaded in context simultaneously.

**Post-ToolSearch (Nov 2025):** "Write clear, descriptive tool names and
descriptions. Use semantic keywords in descriptions that match how users
describe tasks."
Source: [Tool search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
Written for: deferred tools discovered via keyword matching.

**These were never reconciled by Anthropic.** With 142 tools, ToolSearch
is always active (>10% context threshold in Claude Code). Our descriptions
serve two purposes:

1. **Discovery** — ToolSearch matches keywords in name + description
2. **In-context guidance** — once loaded, description guides tool selection

Verbose usage guidance helps (2) but may hurt (1) by diluting keywords
with filler. The keyword enrichment we already did targets (1). This plan
targets (2) selectively — only where we have measured confusion.

## Revised Approach: Targeted, Not Exhaustive

Don't add usage guidance to all 116 tools. Instead:
- **Confusion pairs** (16 tools) — add negative scope to disambiguate
- **L1 failure tools** (7 tools) — add when-to-use matching vague prompts
- **Bypass-prone tools** (8 tools) — add emphasis keywords
- **Short descriptions** (12 tools) — expand the worst offenders only

Total: **~35 tools to change** (down from 142).

## Changes

### 1. Confusion pairs — negative scope (16 tools, 8 pairs)

These tools get confused with each other. Add one line: "For [X], use [Y]."

| Tool | Confused with | Add |
|------|-------------|-----|
| `run_qaqc_checks` | `validate_model` | "Requires completed simulation run_id. For pre-sim checks, use validate_model." |
| `validate_model` | `run_qaqc_checks` | "Pre-simulation only. For post-sim QA/QC with ASHRAE checks, use run_qaqc_checks." |
| `get_load_details` | `get_space_details` | "Returns load-specific fields (watts, people, schedules). For space geometry, use get_space_details." |
| `get_space_details` | `get_load_details` | "Returns space geometry, surfaces, zone. For load values (W/m2, people), use get_load_details." |
| `inspect_osm_summary` | `get_model_summary` | "Reads from disk without loading into memory. If model already loaded, use get_model_summary." |
| `get_model_summary` | `inspect_osm_summary` | "Requires loaded model. To preview an OSM without loading, use inspect_osm_summary." |
| `create_baseline_osm` | `create_new_building` | "For testing and demos. For production models with DOE prototypes, use create_new_building." |
| `create_example_osm` | `create_baseline_osm` | "Minimal single-zone demo. For multi-zone baseline, use create_baseline_osm." |
| `set_thermostat_schedules` | `replace_thermostat_schedules` | "Sets schedules on zones without existing thermostats. To overwrite existing, use replace_thermostat_schedules." |
| `replace_thermostat_schedules` | `set_thermostat_schedules` | "Overwrites existing thermostat schedules. To set on unassigned zones, use set_thermostat_schedules." |
| `add_output_variable` | `add_output_meter` | "For zone/surface-level variables. For whole-building energy meters, use add_output_meter." |
| `add_output_meter` | `add_output_variable` | "For facility-level energy meters. For zone/surface variables, use add_output_variable." |
| `extract_summary_metrics` | `extract_end_use_breakdown` | "Returns EUI + unmet hours only. For per-category energy breakdown by fuel, use extract_end_use_breakdown." |
| `copy_file` | `read_file` | "Copies to /runs for host access. To read file contents, use read_file." |
| `apply_measure` | `create_measure` | "Runs an existing measure on the loaded model. To write a new measure, use create_measure." |
| `list_model_objects` | typed list tools | "Works with any OpenStudio type. Typed tools (list_spaces, list_air_loops) return more detail for common types." |

### 2. L1 failure tools — when-to-use (7 tools)

Match the vague natural language that causes L1 failures:

| Tool | L1 prompt that fails | Add |
|------|---------------------|-----|
| `run_qaqc_checks` | "Check model for issues" | (covered by confusion pair above) |
| `get_load_details` | "What loads?" | (covered by confusion pair above) |
| `replace_window_constructions` | "Upgrade the windows" | "Use to upgrade or replace all window constructions at once." |
| `adjust_thermostat_setpoints` | "Change thermostat settings" | "Use to raise or lower all heating/cooling setpoints by a degree offset." |
| `import_floorspacejs` | "Import the floor plan" | "Use to import geometry from a FloorSpaceJS JSON file." |
| `save_osm_model` | "Save the model" | "IMPORTANT: call after making changes to persist the model to disk." |
| `list_model_objects` | "What sizing parameters?" | (structural — prompt is too vague for any tool) |

### 3. Bypass-prone tools — emphasis (8 tools)

Only tools with known FM1/FM2/FM3 bypass patterns:

| Tool | Emphasis to add |
|------|----------------|
| `extract_summary_metrics` | "ALWAYS use this for EUI — do not parse eplusout.sql directly." |
| `add_baseline_system` | "ALWAYS use for ASHRAE systems 1-10 — do not write HVAC scripts." |
| `search_api` | "IMPORTANT: call before writing measures that use SDK method calls." |
| `run_simulation` | "IMPORTANT: requires weather file (EPW) and design days set on model." |
| `save_osm_model` | "IMPORTANT: save after modifications to persist changes." |
| `create_measure` | Already has "ALWAYS use this tool" |
| `view_model` | Already has "Use this instead of" |
| `generate_results_report` | Already has "Use this instead of" |

### 4. Short descriptions to expand (12 worst)

Only the ones under 100 chars — the 100-150 range are acceptable:

| Tool | Current chars | Fix |
|------|-------------|-----|
| `get_run_period` | 57 | Add "annual or partial-year simulation start/end dates" |
| `get_server_status` | 73 | Add "loaded model path, run root, concurrency limit" |
| `get_versions` | 75 | Expand to mention "OpenStudio SDK 3.x, EnergyPlus 24.x" |
| `enable_ideal_air_loads` | 83 | Add "for quick load calculations and sizing studies" |
| `get_simulation_control` | 84 | Add "zone/system/plant sizing, run periods, timestep" |
| `get_weather_info` | 87 | Already has fields listed |
| `cancel_run` | 89 | Add "while status is 'running' or 'queued'" |
| `match_surfaces` | 92 | Add "after creating adjacent spaces with shared walls" |
| `set_lifecycle_cost_params` | 116 | Add "for NIST BLCC lifecycle cost analysis" |
| `validate_model` | 124 | Covered by confusion pair above |
| `create_example_osm` | 120 | Covered by confusion pair above |
| `get_sizing_zone_properties` | 128 | Add "design air flow, supply temperatures, DOAS settings" |

## Files to Change

~15 of the 22 tools.py files (only those containing the ~35 targeted tools):

| File | Tools to change | Type |
|------|----------------|------|
| `results/tools.py` | extract_summary_metrics, copy_file | confusion + emphasis |
| `simulation/tools.py` | run_simulation, validate_model, cancel_run, get_run_period | emphasis + confusion + short |
| `common_measures/tools.py` | replace_window_constructions, adjust_thermostat_setpoints, set/replace_thermostat_schedules, enable_ideal_air_loads | L1 + confusion + short |
| `model_management/tools.py` | save_osm_model, inspect_osm_summary, create_example_osm, create_baseline_osm | emphasis + confusion |
| `building/tools.py` | get_model_summary | confusion |
| `object_management/tools.py` | list_model_objects | confusion |
| `hvac_systems/tools.py` | add_baseline_system | emphasis |
| `loads/tools.py` | get_load_details | confusion |
| `spaces/tools.py` | get_space_details | confusion |
| `measures/tools.py` | apply_measure | confusion |
| `geometry/tools.py` | import_floorspacejs, match_surfaces | L1 + short |
| `simulation_outputs/tools.py` | add_output_variable, add_output_meter | confusion |
| `weather/tools.py` | get_simulation_control, get_run_period | short |
| `api_reference/tools.py` | search_api | emphasis |
| `server_info/tools.py` | get_server_status, get_versions | short |

## Testing

- `test_tool_baseline.py` — all existing tests pass
- New: `test_confusion_pairs_documented` — each confusion pair tool has "use [other tool]" in description
- Full LLM suite — compare against Run 12 (163/170, 95.9%)
- Targeted L1: re-run the 7 L1 failure cases

## What NOT to Do

- Don't add when-to-use to all 116 tools — most are self-evident from name
- Don't add negative scope to all 132 tools — only where confusion exists
- Don't use IMPORTANT/ALWAYS on more than ~12 tools — dilutes the signal
- Don't expand descriptions beyond ~300 chars for simple tools — hurts ToolSearch

## Citations

- Pre-ToolSearch guidance (mid-2024): [implement-tool-use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/implement-tool-use)
- Post-ToolSearch guidance (Nov 2025): [tool-search-tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- "Writing effective tools for AI agents" (Sep 11, 2025): [blog](https://www.anthropic.com/engineering/writing-tools-for-agents)
- "Advanced tool use" (Nov 24, 2025): [blog](https://www.anthropic.com/engineering/advanced-tool-use)
- ToolSearch in Claude Code: v2.1.7 (Jan 14, 2026), ENABLE_TOOL_SEARCH env var
- Tool use GA: May 30, 2024 (API release notes)
- Tool Search GA: Feb 17, 2026 (API release notes)
