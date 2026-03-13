# Plan: Generic Model Object Access + Tool Consolidation

## Status: Phase A+B+C COMPLETE

## Context
Claude Desktop session (2026-03-11) on `annex_final_v6.osm` — LLM burned 12+ tool_search calls and 15 min trying to find FourPipeBeam objects. Root cause: no generic way to query arbitrary object types or read/write their properties.

Current: 131 tools x ~200 tokens each = ~26K tokens/session.

## Phase A: New Generic Tools — DONE

### W1: `list_model_objects` dynamic fallback
- `_normalize_type_name()` — accepts CamelCase, IDD colon (`OS:Coil:Cooling:Water`), IDD underscore
- `_resolve_getter()` — MANAGED_TYPES fast-path + dynamic `getattr(model, f"get{norm}s")` fallback
- File: `mcp_server/skills/object_management/operations.py`

### W2: `get_object_fields` — generic property read
- Introspects `dir(obj)`, calls useful getters, returns typed values + available setters
- Handles OptionalDouble/String/Int, enums, base types
- Base-class blocklist filters SWIG noise (~40 methods)
- **Definition traversal** (Phase C): follows `*Definition` links 1 level deep, returns nested scalar fields inline
- File: `mcp_server/skills/object_management/operations.py`

### W3: `set_object_property` — generic property write
- Accepts getter name (`efficiency`) or setter name (`setEfficiency`)
- Auto-derives setter, type coercion, returns old+new values
- File: `mcp_server/skills/object_management/operations.py`

### W4: Demand terminals in `get_air_loop_details`
- Added `demand_terminals` list with zone/terminal_type/terminal_name
- File: `mcp_server/skills/hvac/operations.py`

## Phase B: Equivalence Tests — DONE

Verified generic tools return same data as explicit tools. Tests in `tests/test_generic_access.py`.

## Phase C: Remove 6 Redundant List/Discovery Tools — DONE

### Removed tools (142 → 136)
| Removed | Replacement |
|---------|-------------|
| `list_people_loads` | `list_model_objects("People")` → `get_object_fields` |
| `list_lighting_loads` | `list_model_objects("Lights")` → `get_object_fields` |
| `list_electric_equipment` | `list_model_objects("ElectricEquipment")` |
| `list_gas_equipment` | `list_model_objects("GasEquipment")` |
| `list_infiltration` | `list_model_objects("SpaceInfiltrationDesignFlowRate")` |
| `list_hvac_components` | `list_model_objects` per type + loop detail tools |

### Kept
- `get/set_component_properties` — unit metadata, not a discovery issue
- `get_load_details` — type dispatcher (tries all 5 load types by name), genuinely unique
- All sizing/economizer/SPM tools — future merge candidate but not a discovery problem
- All creation tools, detail/topology tools

### Definition traversal (`_extract_value` `_depth` parameter)
- `_extract_value(val, _depth=0)` — when a getter returns a model object with "Definition" in class name (Optional-wrapped or direct), recursively extracts scalar fields at `_depth=1`
- Result: `get_object_fields("People", "Office People")` returns `{"peopleDefinition": {"numberofPeople": 10.0, ...}, ...}`

### Additional: `list_construction_sets` pagination
- Added `max_results` param (default 10, 0=unlimited) following standard pattern

### Files modified
1. `mcp_server/skills/object_management/operations.py` — definition traversal in `_extract_value`
2. `mcp_server/skills/loads/tools.py` — removed 5 list tool registrations
3. `mcp_server/skills/component_properties/tools.py` — removed list_hvac_components
4. `mcp_server/skills/constructions/operations.py` + `tools.py` — list_construction_sets pagination
5. `mcp_server/skills/prompts_resources/tools.py` — updated tool catalog
6. `tests/test_loads.py` — converted to use list_model_objects
7. `tests/test_generic_access.py` — replaced equivalence tests with definition traversal tests
8. `tests/test_response_sizes.py` — removed 6 tools from PAGINATED_TOOLS
9. `tests/test_create_loads.py` — verification calls use list_model_objects
10. `tests/test_component_properties.py` — rewritten to use list_model_objects
11. `tests/test_loop_operations.py` — list_model_objects per component type
12. `tests/test_plant_loop_demand.py` — list_model_objects for CoilCoolingWater
13. `tests/test_example_workflows.py` — list_model_objects replacements
14. `tests/test_skill_registration.py` — removed 6 from expected tools
15. `tests/eval_tool_selection.py` — updated expected tool names
16. `tests/llm/conftest.py` — updated FLAKY_TESTS
17. `CLAUDE.md` — loads 11→6, component_properties 11→10, total 142→136
18. `README.md` — updated tool counts and tables

### Test results
- 102 passed, 0 failed, 2 skipped across 9 affected test files

## Phase D: Remove 5 More Redundant List Tools — DONE

Removed 5 additional list tools (136 → 131) that are fully covered by `list_model_objects`:

| Removed | Replacement |
|---------|-------------|
| `list_space_types` | `list_model_objects("SpaceType")` |
| `list_building_stories` | `list_model_objects("BuildingStory")` |
| `list_constructions` | `list_model_objects("Construction")` |
| `list_construction_sets` | `list_model_objects("DefaultConstructionSet")` |
| `list_schedule_rulesets` | `list_model_objects("ScheduleRuleset")` |

### Kept (unique value beyond listing)
- `list_air_loops` — returns topology (supply/demand components), not just names
- All `get_*_details` tools — computed values, nested traversal
- All creation tools

### LLM test validation (Run 6: 153/159 = 96.2%)
- 16 new progressive cases covering all gap categories
- 4 new workflow cases
- No regressions from tool removal

## Future candidates (not planned)
- Merge sizing/economizer/SPM tools into `get/set_object_property` if LLM tests show confusion
- `list_model_objects` category filter (e.g. "show all coils") — defer unless needed
