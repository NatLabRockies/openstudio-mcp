# Plan: Optimize MCP Tool Descriptions for Runtime Token Efficiency

## Context

When an LLM connects to this MCP server (e.g. via Claude Desktop), it receives all 107 tool definitions in its context window. Current cost: ~34,000 chars → ~8,500-13,000 tokens. This plan trims descriptions to reduce runtime token cost while preserving accuracy for building-science-specific tools. No functional changes — only docstring edits.

## Current State

| Category | Count | Total chars | Avg chars/tool |
|----------|-------|------------|----------------|
| All tools | 107 | ~34,400 | 321 |
| Worst offenders | hvac_systems (8) | 6,244 | 780 |
| | comstock (2) | 1,646 | 823 |
| | simulation_outputs (2) | 1,487 | 744 |
| Best examples | simulation (7) | 907 | 130 |
| | results (2) | 109 | 55 |

## Optimization Rules

Apply these in order. Each rule has a before/after example.

### Rule 1: Remove "Requires a model" boilerplate (~4,000 chars saved)

Appears in ~70 tools. The LLM learns this after one call. Remove entirely.

```
BEFORE: "...Requires a model to be loaded via load_osm_model_tool first."
AFTER: (removed)
```

Also remove variants: "Requires a model to be loaded.", "Requires a completed simulation.", "Does not require a model to be loaded.", "Use save_osm_model_tool to persist changes."

### Rule 2: Remove embedded JSON examples (~1,500 chars saved)

3 tools in hvac_systems have full JSON response bodies. LLM sees actual response when it calls the tool.

```
BEFORE (add_doas_system):
    "Example:
        {
          "ok": true,
          "system": {
            "name": "DOAS",
            ...15 more lines...
          }
        }"

AFTER: (removed entirely)
```

Affects: `add_doas_system`, `add_vrf_system`, `add_radiant_system`

### Rule 3: Remove "Returns:" bullet lists on query tools (~2,000 chars saved)

Query tools list every returned field. The LLM discovers fields from the actual response. Replace with nothing or a single line if needed.

```
BEFORE (list_spaces):
    "Returns array of space objects with:
    - Name, handle, floor area, volume
    - Space type and thermal zone assignments
    - Building story
    - Default construction and schedule sets
    - Origin coordinates and orientation
    - Counts of surfaces, people, lights, equipment"

AFTER: (removed — the 1-liner "List all spaces in the currently loaded model." is sufficient)
```

Affects: ~25 query tools across building, spaces, geometry, constructions, schedules, hvac, loads, space_types

### Rule 4: Remove "Args:" sections where param names are self-documenting (~1,200 chars saved)

MCP sends parameter names and types in the schema. Only keep Args text when it adds info the name/type doesn't convey (constraints, enum values, domain-specific units).

```
BEFORE (get_space_details):
    "Args:
        space_name: Name of the space to retrieve

    Returns detailed space attributes including geometry, loads,
    and assignments."

AFTER: "Get detailed information about a specific space."
```

**Keep** Args text when it conveys constraints or enum options not obvious from param name:
- `system_type: ASHRAE baseline system type (1-10)` — keep
- `terminal_type: "VAV_Reheat" | "VAV_NoReheat" | "PFP_Electric" | ...` — keep
- `space_name: Name of the space to retrieve` — remove (obvious)

### Rule 5: Remove educational/marketing text (~1,200 chars saved)

Explanations of what building science concepts mean, advantage lists, etc. The LLM doesn't need to learn building science from tool descriptions.

```
BEFORE (list_people_loads):
    "People loads represent occupants and their heat gain, moisture
    generation, and ventilation requirements."

BEFORE (add_vrf_system):
    "VRF advantages:
    - High efficiency (COP 3-5 typical)
    - Zonal control (independent setpoints per zone)
    - Heat recovery between zones
    - No ductwork or plant loops required"

BEFORE (add_radiant_system):
    "Considerations:
    - Slow response time (thermal mass)
    - Requires ventilation system (DOAS recommended)
    - Floor coverings affect performance"

AFTER: (removed)
```

### Rule 6: Remove phase markers and cross-tool references (~300 chars saved)

```
BEFORE: "NEW in Phase 4D for component validation testing."
BEFORE: "Enhanced in Phase 4D for component validation testing."
BEFORE: "Use `get_run_status_tool` to poll for completion, then `extract_summary_metrics_tool` to get results."
BEFORE: "Supports the same types as delete_object_tool."

AFTER: (removed)
```

### Rule 7: Compress the ASHRAE system list in add_baseline_system

Keep it — the LLM needs the number-to-name mapping — but compress from 10 lines to inline:

```
BEFORE:
    "All 10 ASHRAE 90.1 Appendix G baseline systems supported:
    - System 1: PTAC (Packaged Terminal Air Conditioner)
    - System 2: PTHP (Packaged Terminal Heat Pump)
    ...8 more lines..."

AFTER:
    "Systems 1-10: PTAC, PTHP, PSZ-AC, PSZ-HP, Packaged VAV Reheat, Packaged VAV PFP, VAV Reheat, VAV PFP, Htg&Vent Gas, Htg&Vent Electric."
```

## What to Keep

- **First-line summary** — always keep, this is the primary description
- **Constraint notes** — "Exactly one sizing method required" (prevents errors)
- **Enum values for non-obvious params** — terminal_type options, system_type range, reporting_frequency options
- **Domain-specific units** — "in W/m²", "in meters", "in °C" (prevents unit errors)
- **Behavioral caveats** — "Disconnects existing HVAC", "Clones schedules so originals are not mutated"

## Target Examples

**Query tool (before: 361 chars → after: ~50 chars):**
```
BEFORE: "List all spaces in the currently loaded model.\n\nReturns array of space objects with:\n- Name, handle, floor area, volume\n- Space type and thermal zone assignments\n- Building story\n- Default construction and schedule sets\n- Origin coordinates and orientation\n- Counts of surfaces, people, lights, equipment\n\nRequires a model to be loaded via load_osm_model_tool first."

AFTER: "List all spaces in the loaded model."
```

**Creation tool (before: 427 chars → after: ~150 chars):**
```
BEFORE: "Create a people (occupancy) load and assign to a space.\n\nArgs:\n    name: ...\n    space_name: ...\n    people_per_area: People per m² (use this OR num_people)\n    num_people: Absolute number (use this OR people_per_area)\n    schedule_name: Optional ScheduleRuleset for occupancy fraction\n\nExactly one sizing method required.\nRequires a model to be loaded via load_osm_model_tool first."

AFTER: "Create a people (occupancy) load and assign to a space. Provide exactly one of people_per_area (per m²) or num_people."
```

**Complex tool (before: 1,232 chars → after: ~300 chars):**
```
BEFORE: (add_radiant_system with advantages list, considerations list, full Args, JSON example)

AFTER: "Add low-temperature radiant heating/cooling system with plant loops. Optionally adds DOAS for ventilation. radiant_type: Floor | Ceiling | Walls. ventilation_system: DOAS | None."
```

## Estimated Savings

| Rule | Chars saved | Tokens saved |
|------|-----------|-------------|
| 1. Boilerplate removal | ~4,000 | ~1,000 |
| 2. JSON examples | ~1,500 | ~375 |
| 3. Returns bullet lists | ~2,000 | ~500 |
| 4. Redundant Args | ~1,200 | ~300 |
| 5. Educational text | ~1,200 | ~300 |
| 6. Phase markers/cross-refs | ~300 | ~75 |
| 7. Compress system list | ~400 | ~100 |
| **Total** | **~10,600** | **~2,650** |

**Before: ~34,400 chars → After: ~23,800 chars (~31% reduction)**
**Before: ~8,500 tokens → After: ~5,950 tokens (~30% reduction)**

## Files to Modify

All 21 `tools.py` files — every file under `mcp_server/skills/*/tools.py`.

No operations.py, no test files, no functional changes.

## Execution Order

0. **Backup** — save `docs/tool_descriptions_backup.md` with all 107 original docstrings (tool name + full docstring). Git-tracked, easy to diff/revert.
1. **hvac_systems/tools.py** — biggest win (6,244 → ~2,500 chars), most rules apply
2. **loads/tools.py** — highly repetitive, same pattern ×10
3. **building, spaces, geometry, constructions, hvac, schedules, space_types** — query tool Return lists
4. **common_measures, comstock, weather, measures** — lighter touch
5. **simulation, results, server_info** — already lean, minimal changes
6. **component_properties, loop_operations, object_management, simulation_outputs, model_management** — moderate

## Verification

1. `ruff check mcp_server/` — no syntax errors
2. `pytest tests/test_skill_registration.py -v` — all tools still register
3. Spot-check: read a few tools.py files, confirm descriptions are clear and accurate
4. Full CI run — all 235 tests pass (descriptions don't affect test behavior)

## Unresolved Questions

1. Keep or remove "Exactly one sizing method required" constraint notes on loads create tools? (I say keep — prevents errors)
2. The enum lists in `replace_air_terminals` terminal_type — keep full list or compress? Values aren't obvious from param name. (I say keep)
3. Should we standardize wording for "Requires a model" into a single-word convention like prefixing tool name, or just drop entirely? (I say drop entirely)
