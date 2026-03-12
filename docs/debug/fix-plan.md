# Fix Plan: Issues from Debug Runs (v6)

## Evidence Base

Issues identified from 6 log/transcript files in `docs/debug/`:
- `mcp.log` — MCP JSON-RPC messages (client↔server), session 1
- `mcp-server-openstudio-mcp.log` — server-side stderr + tool traces
- `chat_transcript.md` — Claude Desktop conversation export (JSON), session 1
- `openstudio-mcp-err-fix-plan.md` — structured .err analysis
- `debug_chat_annex_beam_ventilation_2026-03-10.md` — second run analysis
- `chat_export_move_fcu_coils.json` — **session 3** (2026-03-11): move FCU coils between plant loops

---

## W1. Remove `inject_idf` tool (small) ✅ DONE
- Delete from: tools.py, wrappers.py, operations.py category map, prompts_resources/tools.py, test_skill_registration.py, README.md, CLAUDE.md
- ~15 lines across 7 files

## W2. Redesign `list_files` (medium) ✅ DONE

### Problem
LLM called `list_files("/runs/debug")`, got 183 files. Second call `list_files("/runs", "*")`
returned **574 files / 230K chars** (line 938 of mcp.log). Another call for `*.idf` returned
**538 files / 151K chars** (line 924). Massive context waste per call.

### Design (aligned with MCP filesystem best practices)

Official MCP filesystem server pattern: two tools — shallow `list_directory` (1 level)
and recursive `directory_tree`. Key principle: **minimal metadata, let LLM choose depth.**

**Changes to `list_files`:**
1. Add `max_depth: int | None` param (default=`None` = unlimited, `1` = top-level only)
2. Always skip `measures/*/resources/` and `measures/*/tests/` — never useful to LLM.
   Keep 1 level into `measures/` so measure names + `measure.xml` are visible.
3. Slim output: return `name`, `path`, `type` (`"file"` or `"dir"`) only — drop `size_bytes`
   and `extension` (LLM rarely needs them, extension is in the name)
4. Keep existing `pattern` param for glob filtering (`*.osm`, `*.epw`)

**Context savings:** Dropping size/extension + filtering measure internals cuts ~60% of
tokens for typical run directories. `max_depth=1` gives another 80%+ reduction when
just browsing.

**Test:** `test_list_files_max_depth`, `test_list_files_filters_measure_internals`

## W3. Rename `read_run_artifact` → `read_file`, `copy_run_artifact` → `copy_file` (medium) ✅ DONE

### Problem
`run_id` was just a directory name shorthand — `resolve_run_dir(RUN_ROOT, run_id)` simply
does `(RUN_ROOT / run_id).resolve()` + parent check. External files in `/runs/debug/` or
`/inputs/` had no `run_id`, making these tools useless for anything not started via
`run_simulation`. `run_id` is only truly needed for process-tracking tools
(`get_run_status`, `get_run_logs`, `cancel_run`) that reference the in-memory PID registry.

**MCP log evidence (10 failed attempts across 3 sessions):**
```
id:15 read_run_artifact(run_id="debug/annex_...") → "run_not_found"
id:16 get_run_artifacts(run_id="annex_...")       → "Unknown run_id"
id:98 read_run_artifact(run_id="debug/annex_...") → "run_not_found"  (2nd session!)
id:99 get_run_artifacts(run_id="annex_...")        → "Unknown run_id"
id:100 read_run_artifact(run_id="debug%2Fannex..") → "run_not_found" (URL-encoded!)
id:101 copy_run_artifact(run_id="debug/annex_..") → "run_not_found"
id:105 copy_run_artifact(run_id="debug/annex_..") → "run_not_found"
id:106 read_run_artifact(run_id="debug", path="/runs/debug/...") → "invalid_path"
id:107 read_run_artifact(run_id="debug", path="annex_.../run/eplusout.err") → SUCCESS (finally!)
# Session 3 (chat_export_move_fcu_coils.json):
id:27 read_run_artifact(run_id=".", path="../../../opt/common-measures/...") → "run_not_found"
```

### Design
- `read_file(file_path)` — takes absolute path, validates via `is_path_allowed()`
  (covers all Docker mounts: `/runs`, `/inputs`, `/repo`, `/opt/comstock-measures`,
  `/opt/common-measures`, `/skills`)
- `copy_file(file_path, destination)` — same philosophy, same allowed paths
- Keep `max_bytes`, `offset` params for chunked reading
- Hard rename, no deprecation aliases (immediate change)

### Refactoring scope
Files to update:
- `mcp_server/skills/results/operations.py` — rewrite both functions, remove `resolve_run_dir` usage
- `mcp_server/skills/results/tools.py` — rename tool registrations + update signatures
- `mcp_server/skills/prompts_resources/tools.py` — update skill catalog
- `tests/test_skill_registration.py` — rename in EXPECTED_TOOLS
- All test files that call `read_run_artifact` or `copy_run_artifact`
- `README.md`, `CLAUDE.md` — update tool tables

### Security
- `is_path_allowed()` already validates against `ALLOWED_PATH_ROOTS` list
- `.resolve()` + prefix check prevents path traversal
- No change to security model — same roots as `list_files` already allows

**Tests:** `test_read_file_absolute_path`, `test_read_file_rejects_outside_mounts`,
`test_copy_file_absolute_path`, `test_copy_file_rejects_escape`

## W4. `set_sizing_system_properties` tool (medium) ✅ DONE

Access via `air_loop.sizingSystem()` — auto-created with every AirLoopHVAC.

### Properties (12, driven by openstudio-standards usage)

| Property | SDK Setter | Type | Typical Values |
|----------|-----------|------|----------------|
| `type_of_load_to_size_on` | `setTypeofLoadtoSizeOn` | str | "Sensible", "VentilationRequirement" (DOAS) |
| `central_cooling_design_supply_air_temperature` | `setCentralCoolingDesignSupplyAirTemperature` | float C | 12.8 (VAV), 16 (DOAS+beam) |
| `central_heating_design_supply_air_temperature` | `setCentralHeatingDesignSupplyAirTemperature` | float C | 16.7-43 |
| `central_cooling_design_supply_air_humidity_ratio` | `setCentralCoolingDesignSupplyAirHumidityRatio` | float | 0.0085 |
| `central_heating_design_supply_air_humidity_ratio` | `setCentralHeatingDesignSupplyAirHumidityRatio` | float | 0.008 |
| `all_outdoor_air_in_cooling` | `setAllOutdoorAirinCooling` | bool | true for DOAS |
| `all_outdoor_air_in_heating` | `setAllOutdoorAirinHeating` | bool | true for DOAS |
| `preheat_design_temperature` | `setPreheatDesignTemperature` | float C | 7.0 |
| `precool_design_temperature` | `setPrecoolDesignTemperature` | float C | 13.0 |
| `sizing_option` | `setSizingOption` | str | "Coincident", "NonCoincident" |
| `cooling_design_air_flow_method` | `setCoolingDesignAirFlowMethod` | str | "DesignDay" |
| `heating_design_air_flow_method` | `setHeatingDesignAirFlowMethod` | str | "DesignDay" |

Also add `get_sizing_system_properties(air_loop_name)` for reading current values.

**Test:** `test_set_sizing_system_properties` — create air loop, set DOAS config
(VentilationRequirement + all OA + SAT=16), verify round-trip via getter.

## W5. `set_sizing_zone_properties` tool (medium) ✅ DONE

Access via `thermal_zone.sizingZone()` — auto-created with every ThermalZone.

### Properties (12, driven by openstudio-standards usage)

| Property | SDK Setter | Type | Typical Values |
|----------|-----------|------|----------------|
| `zone_cooling_design_supply_air_temperature` | `setZoneCoolingDesignSupplyAirTemperature` | float C | per-zone SAT |
| `zone_heating_design_supply_air_temperature` | `setZoneHeatingDesignSupplyAirTemperature` | float C | 40-43 |
| `zone_cooling_sizing_factor` | `setZoneCoolingSizingFactor` | float | 1.1 |
| `zone_heating_sizing_factor` | `setZoneHeatingSizingFactor` | float | 1.3 |
| `zone_cooling_design_supply_air_temp_input_method` | `setZoneCoolingDesignSupplyAirTemperatureInputMethod` | str | "SupplyAirTemperature", "TemperatureDifference" |
| `zone_heating_design_supply_air_temp_input_method` | `setZoneHeatingDesignSupplyAirTemperatureInputMethod` | str | same |
| `cooling_design_air_flow_method` | `setCoolingDesignAirFlowMethod` | str | "DesignDay", "DesignDayWithLimit" |
| `cooling_minimum_air_flow_fraction` | `setCoolingMinimumAirFlowFraction` | float | 1.0 for DOAS HP |
| `account_for_dedicated_outdoor_air_system` | `setAccountforDedicatedOutdoorAirSystem` | bool | true for DOAS zones |
| `dedicated_outdoor_air_system_control_strategy` | `setDedicatedOutdoorAirSystemControlStrategy` | str | "NeutralSupplyAir" |
| `dedicated_outdoor_air_low_setpoint_temp` | `setDedicatedOutdoorAirLowSetpointTemperatureforDesign` | float C | DOAS clg SAT |
| `dedicated_outdoor_air_high_setpoint_temp` | `setDedicatedOutdoorAirHighSetpointTemperatureforDesign` | float C | DOAS htg SAT |

### Bulk update
`zone_names: list[str] | str` param — single zone or list. Uses `parse_str_list()`.
Iterates zones, applies same properties to all. Returns per-zone results.

**Test:** `test_set_sizing_zone_properties_single`, `test_set_sizing_zone_properties_bulk`
— create 3 zones, bulk-update DOAS settings, verify all updated.

## W6. Enhance `list_people_loads` to show source (small) ✅ DONE
- Add `source: "space" | "space_type"` field to `_extract_people()`
- Check: `people.space().is_initialized()` → "space"; `people.spaceType().is_initialized()` → "space_type"
- **Test:** `test_people_loads_show_source` — model with People on space + space type

## W7. Improve `list_model_objects` discoverability + output (small) ✅ DONE

### Problem
Tool already requires `object_type` param (well-scoped), but LLM couldn't find it
in the debug sessions. Issues:
1. Docstring uses OpenStudio jargon ("IddObjectType") — LLMs searching for
   "list people" or "find zones" won't discover it
2. Returns `handle` (UUID) per object — zero utility for LLMs, wastes context
3. No indication of supported types in tool description — failed call needed
   to see the supported list

**MCP log evidence:**
- Line 797: `list_model_objects("ZoneHVACEquipmentList")` — unsupported type, wasted call
- Line 912: `get_component_properties("73 Zone DOAS SAT Warmest Reset")` — LLM tried
  component_properties for a SPM because it didn't know about list_model_objects or
  that SPMs aren't in COMPONENT_TYPES
- Session 3 id:17: `list_model_objects("AirTerminalSingleDuctConstantVolumeFourPipeBeam")` — unsupported

### Changes
1. Rewrite docstring — plain language, list common type examples inline
   (Space, ThermalZone, People, Lights, AirLoopHVAC, PlantLoop, ScheduleRuleset, etc.)
2. Drop `handle` from output — return only `name` per object
3. Add to server `instructions` near other query tools so agents discover it
4. No structural changes — tool is already well-scoped by required `object_type` param

**Test:** existing tests cover functionality; just docstring/output changes

## W8. Expand `set_setpoint_manager_properties` (medium-large) ✅ DONE

### Current support: 2 types (SingleZoneReheat, Scheduled)

### Add 6 types (all used in openstudio-standards)

**Tier 1 — used by our wiring code + very common:**

| SPM Type | Properties to Expose | Context |
|----------|---------------------|---------|
| **Warmest** | `minimum_setpoint_temperature`, `maximum_setpoint_temperature`, `strategy` | Multi-zone VAV SAT reset |
| **FollowOutdoorAirTemperature** | `reference_temperature_type`, `offset_temperature_difference`, `minimum_setpoint_temperature`, `maximum_setpoint_temperature` | Condenser loop control |
| **OutdoorAirReset** | `setpoint_at_outdoor_low_temperature`, `outdoor_low_temperature`, `setpoint_at_outdoor_high_temperature`, `outdoor_high_temperature` | HW/CHW supply temp reset |

**Tier 2 — used in specific prototypes:**

| SPM Type | Properties to Expose | Context |
|----------|---------------------|---------|
| **Coldest** | `minimum_setpoint_temperature`, `maximum_setpoint_temperature`, `strategy` | Mirror of Warmest (heating) |
| **ScheduledDualSetpoint** | `high_setpoint_schedule`, `low_setpoint_schedule` | Heat pump loop deadband |
| **SingleZoneHumidityMinimum** | (control_zone only — read-only useful) | Hospital humidification |

**Also add `get_setpoint_manager_properties`** for reading any SPM's current values.

### Lookup refactoring
Current code iterates `getSetpointManagerSingleZoneReheats()` + `getSetpointManagerScheduleds()`.
Extend to iterate all 8 supported getter methods. Use dict registry like COMPONENT_TYPES:

```python
SPM_TYPES = {
    "SetpointManagerSingleZoneReheat": {"getter": "getSetpointManagerSingleZoneReheats", ...},
    "SetpointManagerScheduled": {"getter": "getSetpointManagerScheduleds", ...},
    "SetpointManagerWarmest": {"getter": "getSetpointManagerWarmests", ...},
    ...
}
```

### Tests (1 per type = 8 tests)
- `test_spm_single_zone_reheat` (existing)
- `test_spm_scheduled` (existing)
- `test_spm_warmest` — create, set min/max temp, verify round-trip
- `test_spm_follow_oat` — create, set reference type + offset, verify
- `test_spm_outdoor_air_reset` — create, set 4-point reset curve, verify
- `test_spm_coldest` — create, set min/max temp, verify
- `test_spm_scheduled_dual_setpoint` — create with 2 schedules, verify
- `test_spm_single_zone_humidity_min` — create with control zone, verify

## W9. `save_osm_model` param name mismatch (small) ✅ DONE

### Problem
Session 1 LLM called `save_osm_model(osm_path=...)` → Pydantic error. Session 3 LLM
used `save_osm_model(save_path=...)` → success. The param is `save_path` but LLMs
pattern-match from `load_osm_model(osm_path=...)` and guess `osm_path`.

### Fix
Rename `save_path` → `osm_path` in both `tools.py` and `operations.py` to match
`load_osm_model`'s parameter name. Consistent naming across load/save prevents guessing.

**Files:** `model_management/tools.py`, `model_management/operations.py`
**Test:** existing save tests — just rename param

## W10. `get_run_status` polling loop — add guidance (small) ✅ DONE

### Problem
MCP log lines 869-929: LLM called `get_run_status` **22 times in 7 minutes** polling a
running simulation (~every 15-20 seconds). Burns context with repeated identical responses.

### Fix options
1. **Docstring guidance:** Add "Poll no more than once per minute. For long simulations
   (>2 min), poll every 2-3 minutes." to `get_run_status` docstring
2. **Server instructions:** Add anti-polling guidance to MCP server instructions
3. **Future:** Add `wait_for_completion` param to `run_simulation`/`run_osw` that blocks
   until done (eliminates polling entirely). Lower priority — docstring fix is immediate.

**Test:** none needed (docstring change only for now)

## W11. `get_component_properties` — better error for unknown component types (small) ✅ DONE

### Problem
MCP log line 912: LLM called `get_component_properties("73 Zone DOAS SAT Warmest Reset")`
for a SetpointManagerWarmest. Got generic "Component not found" error. LLM then tried
`get_component_properties("Zone - 210 Open Office FCU")` for a FourPipeFanCoil — also
not found.

### Fix
Improve error message to say: "Component not found. Supported types: [list].
For setpoint managers use `set_setpoint_manager_properties`. For zone HVAC use
`get_zone_hvac_details`." This steers the LLM to the right tool.

**Test:** none needed (error message change only)

## W12. `create_plant_loop` tool (medium) — NEW from session 3 ✅ DONE

### Problem
LLM needed to create a new ChW PlantLoop to move FCU coils onto. No tool exists.
`add_supply_equipment` requires an existing loop. LLM had to fall back to writing
a Ruby OpenStudio measure — 25 min of investigation before concluding no tool exists.

### Design
- `create_plant_loop(name, loop_type, design_exit_temp_c, design_delta_temp_c)` — creates
  PlantLoop with sizing, bypass pipe, SPM. Returns loop name + handle.
- `loop_type`: "Cooling" or "Heating" (sets fluid type, sizing defaults)
- Optional: `supply_pump_type` ("variable" or "constant"), `pump_head_pa`, `pump_motor_eff`
- Auto-creates: supply inlet/outlet nodes, demand inlet/outlet nodes, bypass pipe,
  SetpointManagerScheduled on supply outlet

### SDK API
```python
loop = openstudio.model.PlantLoop(model)
loop.setName(name)
sizing = loop.sizingPlant()
sizing.setDesignLoopExitTemperature(temp_c)
sizing.setLoopDesignTemperatureDifference(delta_c)
sizing.setLoopType(loop_type)
```

Auto-creates SetpointManagerScheduled on supply outlet node with constant schedule
at `design_exit_temp_c` (matches openstudio-standards pattern for new CHW/HW loops).

**Files:** `mcp_server/skills/loop_operations/operations.py`, `tools.py` (keep in existing skill)
**Test:** `test_create_plant_loop_cooling`, `test_create_plant_loop_heating`
**CI shard:** 1 (already has `test_loop_operations.py`)

## W13. Demand-side loop operations (medium) — NEW from session 3 ✅ DONE

### Problem
`add_supply_equipment`/`remove_supply_equipment` only work on supply side.
No tools to add/remove coils from plant loop demand side. LLM needed
`removeDemandBranchWithComponent` + `addDemandBranchForComponent` to move
73 FCU cooling coils between loops.

### Design
- `add_demand_component(component_name, plant_loop_name)` — calls
  `plant_loop.addDemandBranchForComponent(component)`. Component found by name
  via existing `_find_component_by_name()` in `component_properties/operations.py`
  (searches all COMPONENT_TYPES by `get<Type>ByName`).
- `remove_demand_component(component_name, plant_loop_name)` — calls
  `plant_loop.removeDemandBranchWithComponent(component)`
- Both return `{"ok": True, "component": name, "plant_loop": name}`

### SDK API
```python
plant_loop.addDemandBranchForComponent(coil)     # add
plant_loop.removeDemandBranchWithComponent(coil)  # remove
```

**Files:** `mcp_server/skills/loop_operations/operations.py`, `tools.py`
**Test:** `test_add_demand_component`, `test_remove_demand_component`,
`test_move_coil_between_loops` (remove from A + add to B)
**CI shard:** 1 (with existing `test_loop_operations.py`)

## W14. Expand `list_model_objects` supported types (small) — NEW from session 3 ✅ DONE

### Problem
Session 3 id:17: `list_model_objects("AirTerminalSingleDuctConstantVolumeFourPipeBeam")`
failed. LLM couldn't enumerate beam air terminals, beam coils, or FourPipeFanCoil objects.

### Add types
- `AirTerminalSingleDuctConstantVolumeFourPipeBeam`
- `CoilCoolingFourPipeBeam` / `CoilHeatingFourPipeBeam`
- `ZoneHVACFourPipeFanCoil`

These are common in DOAS+beam and DOAS+FCU systems. SDK has getter methods for all.

**Files:** `mcp_server/skills/object_management/operations.py` — add to `SUPPORTED_TYPES` dict
**Test:** update existing `test_list_model_objects` or add new

## W15. Slim list tool responses (medium) — NEW from session 3 ✅ DONE

### Problem
Session 3 context waste (~280K chars from oversized + repeated responses):
- `list_thermal_zones(detailed=true)` — 80 zones, **91K chars** (id:14)
- `list_hvac_components()` — 228 components, **62K chars** (id:35)
- `list_hvac_components(category="coil")` — 148 coils, **41K chars** (id:8, called 3x!)
- `list_common_measures(category="other")` — 59 measures, **40K chars** (id:25)
- `list_zone_hvac_equipment()` — 73 items, **23K chars** (id:13, called 2x)
- `list_model_objects("CoilCoolingWater")` — 74 objects, **14K chars** (id:34)

### Per-tool field analysis (current → target)

**`list_thermal_zones(detailed=true)`** — 91K → ~15K
- Drop `handle` (UUID, unactionable)
- Drop `multiplier`, `num_spaces` (rarely needed)
- Drop `equipment[]` array — biggest offender, 80 zones x 2 equip = 16K;
  redundant with `list_zone_hvac_equipment`. Add docstring: "Use
  get_thermal_zone_details or list_zone_hvac_equipment for equipment info"
- Keep: name, floor_area_m2, num_equipment, thermostat, htg/clg schedules, air_loop

**`list_zone_hvac_equipment`** — 23K → ~18K
- Drop `handle`
- Keep: type, name, thermal_zone

**`list_hvac_components`** — 62K → ~50K
- Drop `category` (derivable from type, already in COMPONENT_TYPES)
- Keep: name, type

**`list_model_objects`** — 14K → ~7K (already in W7)
- Drop `handle`
- Keep: name

**`list_common_measures`** — 40K → ~12K
- Drop `path` (system path, LLM uses name to call wrapper tools)
- Drop `description` (200-char truncated blurb, rarely useful for tool selection)
- Keep: name, display_name, category, num_arguments

### Implementation
No pagination needed — field trimming alone cuts total from ~280K to ~100K.
All changes are in `_extract_*` functions, backward compatible (less data, same shape).

**Files:**
- `mcp_server/skills/spaces/operations.py` — `_extract_thermal_zone()` line 50
- `mcp_server/skills/hvac/operations.py` — `_extract_zone_hvac_component()`
- `mcp_server/skills/component_properties/operations.py` — `list_hvac_components_op()`
- `mcp_server/skills/object_management/operations.py` — `list_model_objects()` (W7)
- `mcp_server/skills/common_measures/operations.py` — `list_common_measures()`

**Test impact:** 12 test files assert on `handle` in various list/create responses. BUT
W15 only drops handles from *list* responses, not *create* responses. Check which tests
assert handle on list results specifically:
- `test_hvac.py` — asserts handle on `list_air_loops`, `list_plant_loops`, `list_zone_hvac_equipment`
- `test_loads.py` — asserts handle on `list_people_loads`
- `test_schedules.py` — asserts handle on `list_schedule_rulesets`
- `test_space_types.py` — asserts handle on `list_space_types`
- `test_building.py` — asserts handle on `get_building_info`, `list_building_stories`

These `assert "handle" in item` lines need removal when handles are dropped.
Create responses (test_create_space, test_create_thermal_zone, etc.) keep handles — not affected.

---

## File Path Reference (for cold-start implementation)

### W1 files
- `mcp_server/skills/common_measures/tools.py` — remove `inject_idf` tool decorator + function
- `mcp_server/skills/common_measures/wrappers.py` — remove `inject_idf_op()` function
- `mcp_server/skills/common_measures/operations.py` — remove `"inject_idf_objects": "idf"` from category map
- `mcp_server/skills/prompts_resources/tools.py` — remove from common_measures skill tool list
- `tests/test_skill_registration.py` — remove from EXPECTED_TOOLS, update count

### W2 files
- `mcp_server/skills/model_management/operations.py` — `list_files()` at line ~233

### W3 files
- `mcp_server/skills/results/operations.py` — `read_run_artifact()` at line ~187, `copy_run_artifact()` at line ~336
- `mcp_server/skills/results/tools.py` — tool registrations lines ~18-53
- `mcp_server/skills/prompts_resources/tools.py` — skill catalog references
- `tests/test_skill_registration.py` — EXPECTED_TOOLS
- Grep for `read_run_artifact|copy_run_artifact` across all `tests/` to find test references

### W4/W5 files (new code in component_properties skill)
- `mcp_server/skills/component_properties/operations.py` — add sizing system/zone ops (~line 244+)
- `mcp_server/skills/component_properties/tools.py` — add tool registrations
- New test file: `tests/test_sizing_properties.py` (add to CI shard)

### W6 files
- `mcp_server/skills/loads/operations.py` — `_extract_people()` at line ~16

### W7 files
- `mcp_server/skills/object_management/tools.py` — `list_model_objects_tool` docstring
- `mcp_server/skills/object_management/operations.py` — `list_model_objects()` output at line ~169
- `mcp_server/server.py` — server `instructions` text

### W8 files
- `mcp_server/skills/component_properties/operations.py` — `set_setpoint_manager_properties_op()` at line ~247
- New test file or extend: `tests/test_component_controls.py`

### W9 files
- `mcp_server/skills/model_management/tools.py` — rename `save_path` → `osm_path`
- `mcp_server/skills/model_management/operations.py` — rename `save_path` → `osm_path`

### W10 files
- `mcp_server/skills/simulation/tools.py` — `get_run_status_tool` docstring
- `mcp_server/server.py` — server `instructions` text

### W11 files
- `mcp_server/skills/component_properties/operations.py` — error message in `get_component_properties_op()`

### W12 files
- `mcp_server/skills/loop_operations/operations.py` — add `create_plant_loop_op()`
- `mcp_server/skills/loop_operations/tools.py` — tool registration

### W13 files
- `mcp_server/skills/loop_operations/operations.py` — add demand-side ops
- `mcp_server/skills/loop_operations/tools.py` — tool registrations
- New tests in `tests/test_loop_operations.py` or `tests/test_demand_operations.py`

### W14 files
- `mcp_server/skills/object_management/operations.py` — expand `SUPPORTED_TYPES`

### W15 files
- Multiple list tool operations across skills — add `max_results`/`offset` params
- Priority targets: `list_thermal_zones`, `list_hvac_components`, `list_zone_hvac_equipment`

### Post-implementation updates
- `CLAUDE.md` — update tool tables (remove inject_idf, rename read/copy_run_artifact, add new tools, update counts)
- `README.md` — same tool table updates
- `.github/workflows/ci.yml` — add new test files to appropriate shard

## W16. Context-waste reduction: detail tools + remaining list tools ✅ DONE

Extends W15 guardrails to detail tools, catalog tools, and remaining unpaginated list tools.

### Critical
- **C1.** `read_file` default 400KB→50KB (results/operations.py, tools.py)
- **C2.** `query_timeseries` default 10K→2000 points (results/tools.py, sql_extract.py, operations.py)
- **C3.** `get_space_type_details` nested loads: brief `{name, schedule}` format, capped at 10 items w/ truncation hint (space_types/operations.py)

### High
- **H1.** `list_space_types` — added `max_results=10` pagination via `build_list_response` (space_types/operations.py, tools.py)
- **H2.** `extract_component_sizing` — added `max_results=50` w/ `total_available`/`truncated` metadata (sql_extract.py, operations.py, tools.py)
- **H3.** `list_comstock_measures` — dropped `path` field (comstock/operations.py)

### Medium
- **M1.** `list_common_measures` — dropped `path` field (common_measures/operations.py)
- **M2.** `get_schedule_details` — docstring warns about large rule sets (schedules/tools.py)
- **M3.** Server instructions — added pagination/filter guidance, updated tool count 136→138 (server.py)

### Tests
- `list_space_types` added to `PAGINATED_TOOLS` in test_response_sizes.py (6 existing assertions)
- 4 new tests: `test_read_file_default_under_budget`, `test_space_type_details_under_budget`, `test_space_type_details_brief_loads`, `test_space_types_truncation`
- Fixed pre-existing `total`→`count` in test_load_save_model.py, test_common_measures.py
- Fixed `path` references in test_comstock.py, test_common_measures.py (construct from name)

### Commit: `11e6b06` (13 files, 192+/95-)

## Scope Exclusions
- ~~Duplicate People QA/QC check~~ — W6 + existing delete_object handles it
- ~~WaterHeaterMixed, ChillerElectricEIR expansion, plant loop temp limits, warmup days~~ — model-specific
- SPM types not used in openstudio-standards: MixedAir (auto-created by E+), MultiZone*,
  SingleZoneCooling/Heating, FollowGround*, FollowSystemNode*, SystemNodeReset*,
  OutdoorAirPretreat (complex node wiring, defer), WarmestTemperatureFlow (never created)
- Claude Desktop internal errors (CSP, React, segment metrics) — Anthropic platform issues, not actionable
- Docker Desktop pipe errors — Docker not running when Claude Desktop started MCP server

## Implementation Order

**Batch 1 — quick wins (docstrings, renames, field drops):**
1. W1 (inject_idf removal) — cleanest, no deps
2. W9 (save_osm_model param rename) — 2 files
3. W10 (polling guidance) — docstring only
4. W11 (component error message) — error string only
5. W7 + W15 (drop handles + slim list responses) — do together, same pattern across files
6. W14 (expand list_model_objects types) — pairs with W7

**Batch 2 — medium refactors:**
7. W3 (read_file/copy_file rename) — touches results skill + tests
8. W2 (list_files redesign) — independent
9. W6 (people source) — independent, small

**Batch 3 — new tools:**
10. W12 (create_plant_loop) — new tool in loop_operations
11. W13 (demand-side loop ops) — same skill, depends on W12 for testing
12. W8 (setpoint managers) — independent, can parallelize with W4/W5
13. W4 (sizing system) — component_properties skill
14. W5 (sizing zone) — same skill, same pattern

## Test Summary

| Item | New Tests | Total |
|------|-----------|-------|
| W1 | 0 (update existing registration test) | — |
| W2 | 2 (max_depth, measure filter) | 2 |
| W3 | 4 (read + copy, valid + escape) | 4 |
| W4 | 2 (set + get sizing system, unknown prop error) | 2 |
| W5 | 3 (single zone, bulk, unknown prop error) | 3 |
| W6 | 1 (source field) | 1 |
| W7 | 0 (docstring/output only) | — |
| W8 | 6 new + 2 existing (warmest, followOAT, OAR, coldest, dualSetpoint, humidityMin) | 8 |
| W9 | 0 (verify + close) | — |
| W10 | 0 (docstring only) | — |
| W11 | 0 (error message only) | — |
| W12 | 2 (cooling + heating loop) | 2 |
| W13 | 3 (add demand, remove demand, move coil) | 3 |
| W14 | 1 (new supported types) | 1 |
| W15 | 0 (param additions, no new test files) | — |
| W16 | 4 (read_file budget, space_type_details x2, space_types truncation) | 4 |
| **Total** | **29 new tests** | **30** |

## Log File Reference

| Log | Location | What it captures | How to get it |
|-----|----------|-----------------|---------------|
| `mcp.log` | `%APPDATA%\Claude\logs\mcp.log` | MCP JSON-RPC messages (tool calls + responses) | Auto-generated by Claude Desktop |
| `mcp-server-*.log` | `%APPDATA%\Claude\logs\mcp-server-*.log` | Server stderr (tracebacks, OS warnings) | Auto-generated by Claude Desktop |
| `main.log` | `%APPDATA%\Claude\logs\main.log` | Electron main process (extensions, permissions) | Auto-generated by Claude Desktop |
| `claude.ai-web.log` | `%APPDATA%\Claude\logs\claude.ai-web.log` | Web renderer (CSP, React, fetch errors) | Auto-generated by Claude Desktop |
| Chat transcript | Claude Desktop > Settings > Account > Export Data | Full conversation JSON with tool calls | Manual export |
