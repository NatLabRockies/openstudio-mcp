# LLM Test Plan: Tier 2/3 Geometry Workflows

## Background

Phase A+B geometry tools added 3 new MCP tools:
- `create_bar_building` — bar geometry from DOE prototype params
- `create_new_building` — one-call: bar + weather + design days + typical
- `import_floorspacejs` — SDK-native FloorspaceJS JSON import

LLM tests need to verify agents pick these tools correctly and chain them
properly, replacing the old create_baseline_osm-centric patterns.

## Changes Made (This Round)

### eval.md Updates
- `.claude/skills/new-building/eval.md` — replaced create_baseline_osm
  expectations with create_new_building/create_bar_building/import_floorspacejs

### Tier 1: Tool Selection (test_02_tool_selection.py)
Added cases:
- "Create a small office building using create_new_building" → create_new_building
- "Create bar geometry for a retail building" → create_bar_building
- "list the subsurfaces" → list_subsurfaces
- "show me surface details" → get_surface_details

### Tier 2: Workflows (test_04_workflows.py)
Added cases:
- `create_bar_office` — create_bar_building + list_spaces (120s)
- `create_new_building` — create_new_building with EPW path (180s)

### Tier 4: Guardrails (test_05_guardrails.py)
- Added create_bar_building, create_new_building, import_floorspacejs to
  CREATION_TOOLS set

---

## Tier 2 Tests (Implemented)

### Bar → Typical Chain ✅
- Dropped `add_design_day` from required (too complex for LLM to parameterize)
- Natural language prompt style works better than numbered steps
- Needs `max_turns=25` for 3-tool chain (ToolSearch eats turns)
- Timeout: 420s

### FloorspaceJS Import ✅
- Uses `/test-assets/sddc_office/floorplan.json` (Docker mount added to runner)
- Timeout: 120s

### FloorspaceJS → Typical Chain ✅
- `max_turns=25`, timeout 420s
- Requires: import_floorspacejs, set_weather_file, create_typical_building

### Surface Matching After Manual Geometry ✅
- Two adjacent spaces with explicit vertex coordinates in prompt
- Requires: create_space_from_floor_print, match_surfaces
- Timeout: 120s

---

## Future Tier 3 Tests (E2E with Simulation)

### Create → Simulate → Report
```python
{
    "id": "new_building_simulate",
    "prompt": "Create a SmallOffice with weather, run simulation, "
              "extract summary metrics, report the EUI.",
    "required_tools": ["create_new_building", "run_simulation",
                       "extract_summary_metrics"],
    "timeout": 600,
}
```

### Bar → HVAC → Simulate
```python
{
    "id": "bar_hvac_simulate",
    "prompt": "Create a bar building, add System 7 VAV reheat, "
              "set weather, simulate, report EUI.",
    "required_tools": ["create_bar_building", "add_baseline_system",
                       "run_simulation", "extract_summary_metrics"],
    "timeout": 600,
}
```

---

## Priority Order

1. **Done**: Tier 1 tool selection, Tier 2 all geometry workflows, Tier 4 guardrails
2. **Next**: Tier 3 E2E simulation tests (expensive, ~5min each)
3. **Stretch**: FloorspaceJS→typical→simulate E2E

## Test Count Impact

| Tier | Before | After | Delta |
|------|--------|-------|-------|
| Tier 1 | 21 | 25 | +4 |
| Tier 2 | 8 | 14 | +6 |
| Tier 4 | 2 | 2 | 0 |
| **Total** | ~55 | ~65 | +10 |

## Unresolved

- Should we add a Tier 1 case for import_floorspacejs without Docker test
  assets? (need file path accessible to MCP server)
- Tier 3 tests need weather file inside container — use ComStock bundled EPW?
- Should test_01_setup create a bar model in addition to baseline?
  (downstream tier 2 tests would load it)
