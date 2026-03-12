# Plan: Generic Model Object Access + Tool Consolidation

## Status: Phase A+B COMPLETE, Phase C pending

## Context
Claude Desktop session (2026-03-11) on `annex_final_v6.osm` — LLM burned 12+ tool_search calls and 15 min trying to find FourPipeBeam objects. Root cause: no generic way to query arbitrary object types or read/write their properties.

Current: 140 tools x ~200 tokens each = ~28K tokens/session. Many tools are simple list/property wrappers that generic tools can replace.

## Phase A: New Generic Tools — DONE

### W1: `list_model_objects` dynamic fallback
- `_normalize_type_name()` — accepts CamelCase, IDD colon (`OS:Coil:Cooling:Water`), IDD underscore
- `_resolve_getter()` — MANAGED_TYPES fast-path + dynamic `getattr(model, f"get{norm}s")` fallback
- File: `mcp_server/skills/object_management/operations.py`

### W2: `get_object_fields` — generic property read
- Introspects `dir(obj)`, calls useful getters, returns typed values + available setters
- Handles OptionalDouble/String/Int, enums, base types
- Base-class blocklist filters SWIG noise (~40 methods)
- File: `mcp_server/skills/object_management/operations.py`

### W3: `set_object_property` — generic property write
- Accepts getter name (`efficiency`) or setter name (`setEfficiency`)
- Auto-derives setter, type coercion, returns old+new values
- File: `mcp_server/skills/object_management/operations.py`

### W4: Demand terminals in `get_air_loop_details`
- Added `demand_terminals` list with zone/terminal_type/terminal_name
- File: `mcp_server/skills/hvac/operations.py`

## Phase B: Equivalence Tests — DONE (15 tests, all pass)

| Test | What |
|------|------|
| `test_list_model_objects_dynamic_fallback` | SizingSystem via dynamic getter |
| `test_list_model_objects_idd_colon_format` | OS:Coil:Cooling:Water normalization |
| `test_list_model_objects_idd_underscore_format` | OS_Coil_Cooling_Water normalization |
| `test_list_model_objects_unknown_type_error` | helpful error for fake types |
| `test_get_object_fields_boiler` | reads efficiency from BoilerHotWater |
| `test_get_object_fields_by_handle` | handle-based lookup |
| `test_get_object_fields_not_found` | error for missing object |
| `test_set_object_property_boiler_efficiency` | sets efficiency to 0.92 |
| `test_set_object_property_with_set_prefix` | accepts "setNominalThermalEfficiency" |
| `test_set_object_property_invalid_setter` | error for fake setter |
| `test_air_loop_demand_terminals` | demand_terminals in air loop details |
| `test_equivalence_list_people` | generic vs list_people_loads |
| `test_equivalence_list_lights` | generic vs list_lighting_loads |
| `test_equivalence_list_electric_equipment` | generic vs list_electric_equipment |
| `test_equivalence_boiler_properties` | generic vs get_component_properties |

## Phase C: Tool Removal — PENDING

### Validation gate: run LLM test suite with generic tools before removing explicit tools

### Remove (~16 tools)
- 5 load list tools (People, Lights, ElectricEquipment, GasEquipment, Infiltration)
- `list_hvac_components` (use `list_model_objects` per type)
- `get_component_properties` + `set_component_properties`
- `get/set_sizing_system_properties`
- `get/set_sizing_zone_properties`
- `set_sizing_properties` (plant loop)
- `set_economizer_properties`
- `get/set_setpoint_manager_properties`

### Keep (structured topology)
- Air/plant loop detail tools, space/zone details, schedule details
- All creation tools, simulation, measures, building info, model summary
- `list_spaces`, `list_thermal_zones`, `list_surfaces` (enriched fields)
- `list_constructions`, `list_schedule_rulesets`, `list_space_types`

### Net impact (after Phase C)
- **-16 tools, +3 tools** (net from baseline) = ~13 fewer tools = ~2.6K token savings/session
- Eliminates "unsupported type" dead ends (5-10K wasted tokens per incident)
- Deletes ~500 lines of explicit getter/setter code in `components.py`

## Files Modified (Phase A+B)
1. `mcp_server/skills/object_management/operations.py` — W1 fallback + W2/W3 ops
2. `mcp_server/skills/object_management/tools.py` — W2/W3 tool registrations
3. `mcp_server/skills/hvac/operations.py` — W4 demand terminals
4. `tests/test_generic_access.py` — 15 integration tests
5. `.github/workflows/ci.yml` — added test_generic_access to shard 3
6. `CLAUDE.md` — updated tool table + count (140 tools)

## Open Questions
1. Phase C timing — validate with LLM tests first, then remove in separate PR?
2. SWIG blocklist may need tuning for exotic object types (tuned for common HVAC/loads)
