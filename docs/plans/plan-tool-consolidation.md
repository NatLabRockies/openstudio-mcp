# Plan: Tool Description Enrichment

**Date:** 2026-03-20
**Branch:** optimize
**Status:** planning

## Context: What We Already Did

| Commit | What | Effect |
|--------|------|--------|
| `a78d308` | Compressed all 127 tool descriptions ~30% | Reduced context but hurt ToolSearch discovery |
| `65bee92` | Built generic tools (list_model_objects, get_object_fields, set_object_property) | Universal replacements for typed tools |
| `cbfba81` | Removed 6 redundant list tools (Phase C) | 142→136 tools, replaced with generic access |
| `39d7608` | Added tags to all tools, recommend_tools, search_api | Tags inert (not in MCP spec), recommend_tools works |
| `c09d6ee` | Enriched search_api + search_wiring_patterns descriptions | Both now discoverable by ToolSearch |

**The irony:** We compressed descriptions to reduce context, then discovered
ToolSearch (which defers tools from context entirely). Now short descriptions
hurt discovery because ToolSearch matches on keywords in descriptions.

## Problem

85/142 tools have first-line descriptions under 60 chars. ToolSearch can't
find them with natural language queries. The tools work — the LLM just
can't discover them.

We already proved enriched descriptions work: `search_api` went from
invisible to 1st-result after adding use cases, examples, and keywords.

## What NOT to do

- **Don't remove typed tools** (list_spaces, get_space_details, etc.).
  We already removed 6 in Phase C. The remaining typed tools are MORE
  discoverable than their generic equivalents. `list_spaces` is findable;
  `list_model_objects("Space")` requires knowing the generic tool exists.

- **Don't consolidate get/set pairs** into single tools. Separate tools
  are more discoverable — "get sizing properties" finds `get_sizing_system_properties`
  but won't find a combined tool as easily.

- **Don't add back removed tools.** Phase C removals were correct — those
  tools had true duplicates in generic access.

## What to do: Enrich Descriptions

Restore keyword-rich descriptions without restoring bloat. The old
descriptions had useful content (field lists, use cases) mixed with
noise ("Requires a model to be loaded"). Keep the useful, drop the noise.

### Pattern

Before (compressed, commit a78d308):
```python
"""Get building-level attributes (floor area, people/lighting/equipment densities, orientation)."""
```

After (enriched for ToolSearch):
```python
"""Get building-level attributes: floor area, conditioned area, exterior
wall area, people density, lighting power density, equipment power density,
infiltration rates, north axis orientation, standards building type.

Use this to check the building overview before simulation.
"""
```

Key principles:
- **First line:** concise summary (same as now)
- **Second paragraph:** keyword-rich field list or use cases
- **No boilerplate:** no "Requires model loaded", no "Returns dict with ok"
- **Include domain terms** energy modelers would search for

### Tools to Enrich (85 with short descriptions)

Priority order — tools most likely searched by energy modelers:

**High priority (core workflow tools):**
- `run_simulation` — add "EnergyPlus", "annual", "design day"
- `extract_summary_metrics` — add "EUI", "energy use intensity", "unmet hours"
- `get_building_info` — add field list (floor area, densities, orientation)
- `get_model_summary` — add "object counts", "spaces", "zones", "HVAC"
- `load_osm_model` — add "open", "import", "version translate"
- `save_osm_model` — add "export", "write", "save as"
- `create_new_building` — add "office", "school", "retail", "DOE prototype"
- `view_model` — add "3D", "Three.js", "geometry viewer"
- `list_files` — add "/inputs", "/runs", "find", "discover"

**Medium priority (HVAC tools):**
- `add_baseline_system` — add all 10 system type names
- `add_doas_system` — add "dedicated outdoor air", "ventilation"
- `add_vrf_system` — add "variable refrigerant flow", "multi-zone"
- `create_plant_loop` — add "hot water", "chilled water", "condenser"
- `add_supply_equipment` — add "boiler", "chiller", "pump"
- All get/set component/sizing/SPM tools — add property names

**Medium priority (results tools):**
- `extract_end_use_breakdown` — add "heating", "cooling", "lighting", "by fuel"
- `extract_hvac_sizing` — add "capacity", "airflow", "autosize"
- `query_timeseries` — add "hourly", "timestep", "output variable"
- `compare_runs` — add "baseline", "retrofit", "delta", "percent change"

**Lower priority (geometry/loads/envelope):**
- All list/detail tools — add field names they return
- All create tools — add what they create and key parameters

### Test Strategy

Use existing `tests/test_tool_baseline.py` to measure:
- `test_total_schema_chars` — will increase (expected, acceptable)
- `test_core_schema_chars` — core ratio may change

New test: ToolSearch discoverability sweep
- For each tool, query ToolSearch with a natural language prompt
- Record which tools are findable vs invisible
- Before/after comparison

### Existing Tests to Verify

- `tests/test_skill_registration.py` — tool count unchanged (142)
- `tests/test_tool_routing.py` — recommend_tools accuracy unchanged (25/25)
- `tests/test_wiring_recipes.py` — recipe search unchanged (17/17)
- `tests/llm/test_09_tool_routing.py` — 12/12 should stay or improve
- Full LLM suite — 164/171 should stay or improve

## Implementation

~2 hours across 22 tools.py files. Mechanical work — no architecture
changes, no new tools, no test changes except the new ToolSearch sweep.

## Unresolved

- How much description is too much? ToolSearch may have a sweet spot
  between too-short (not findable) and too-long (dilutes keywords)
- Should we measure ToolSearch hit rate per-tool before and after?
- The old pre-compression descriptions (commit a78d308^) could be
  partially restored — worth diffing to recover useful keywords
