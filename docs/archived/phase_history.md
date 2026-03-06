# Phase History — Completed Phase Details

> Extracted from CLAUDE.md. See [CLAUDE.md](../CLAUDE.md) for active instructions.

## Phase 2 (COMPLETE ✅)

### Completed:
1. ✅ Step 17: `load_osm_model` + `save_osm_model` to `model_management/`
2. ✅ Step 9: `building/` skill (building info, model summary, building stories)
3. ✅ **Batch 1 (Steps 10-12):** `spaces/`, `geometry/`, `constructions/` - 10 tools, 6 tests ✅
4. ✅ **Batch 2 (Steps 13-14):** `schedules/`, `hvac/` - 6 tools, 10 tests ✅
5. ✅ **Batch 3 (Steps 15-16):** `loads/`, `space_types/` - 7 tools, 10 tests ✅

### Summary:
**Phase 2 delivered 10 query skills with 35 MCP tools and 35 integration tests.**

## Phase 3 (COMPLETE ✅ — Model Mutation & Creation Tools)

### Batch 1 (COMPLETE ✅):
1. ✅ `create_space` — Create spaces w/ optional building story and space type
2. ✅ `create_thermal_zone` — Create thermal zones and assign spaces
3. ✅ `add_air_loop` — Add air loops and connect to thermal zones

### Batch 2 (COMPLETE ✅):
4. ✅ `create_schedule_ruleset` — Create constant schedules (Fractional, Temperature, OnOff)
5. ✅ `add_output_variable` — Add EnergyPlus output variables for simulation results
6. ✅ `add_output_meter` — Add EnergyPlus output meters for energy tracking

### Batch 3 (COMPLETE ✅):
7. ✅ `create_standard_opaque_material` — Create materials w/ thermal properties
8. ✅ `create_construction` — Create layered constructions from materials
9. ✅ `assign_construction_to_surface` — Assign constructions to surfaces

### Summary:
**Phase 3 delivered 9 creation tools with 37 integration tests.**

All tests passing locally. Enables complete building model creation: spaces, zones, HVAC, schedules, materials, constructions, and simulation outputs.

## Phase 4 (COMPLETE ✅ — System-Level HVAC Templates & Baseline Systems)

**Goal:** Provide high-leverage, LLM-friendly system-level HVAC modeling capabilities using patterns from OpenStudio-resources simulation tests.

**Strategy:** System-level tools with internal component wiring, not comprehensive SDK exposure.

### Phase 4A: ASHRAE Baseline Systems 1-3 ✅ COMPLETE

**Implemented:**
- ✅ Skill structure: `hvac_systems/` with baseline.py, wiring.py, catalog.py, validation.py
- ✅ `add_baseline_system` — Create ASHRAE baseline systems
- ✅ `list_baseline_systems` — List all baseline system types + modern templates
- ✅ `get_baseline_system_info` — Get metadata for specific system type
- ✅ System 1: PTAC (zone equipment)
- ✅ System 2: PTHP (zone equipment with heat pump)
- ✅ System 3: PSZ-AC (packaged rooftop unit, single zone)
- ✅ Integration tests (7 tests)
- ✅ CI workflow updated
- ✅ SKILL.md documentation

### Phase 4B: Complete Baseline Systems 4-10 ✅ COMPLETE

**All 10 ASHRAE 90.1 Appendix G baseline systems implemented!**

Completed in 3 batches:
- ✅ Batch 1: Systems 4-6 (PSZ-HP, Packaged VAV variants)
- ✅ Batch 2: Systems 7-8 (Central VAV w/ chiller/boiler/tower)
- ✅ Batch 3: Systems 9-10 (Gas/electric unit heaters)

**Testing:** 18 comprehensive integration tests (all passing)
- Component existence verification
- Plant loop verification (Systems 5, 7-8)
- Multi-zone rejection (PSZ systems)
- Terminal verification (VAV vs PFP)
- Edge case handling

**Code Delivered:**
- baseline.py: 1,277 lines (10 complete system implementations)
- 18 integration tests
- Full API routing (systems 1-10)
- Complete documentation

All 10 ASHRAE 90.1 Appendix G baseline systems implemented.

### Phase 4C: Air Terminal Replacement ✅ COMPLETE
- `replace_air_terminals(system_name, terminal_type, ...)` — Swap terminals on existing air loops

### Phase 4D: Component-Level Validation Tests ✅ COMPLETE
- 73 validation tests for all 10 baseline systems — all passing
- Enhanced query tools: `get_plant_loop_details`, `get_zone_hvac_details`
- Coil type/fan/economizer/setpoint/plant loop verification
- Fixed coil extraction bug (OS underscore naming: `OS_Coil_Heating_Gas`)

### Phase 4E: Modern HVAC Templates ✅ COMPLETE
- 3 tools: `add_doas_system`, `add_vrf_system`, `add_radiant_system`
- 16 integration tests (6 DOAS + 5 VRF + 5 Radiant) — all passing
- Key API fixes: VRF uses `addTerminal()` not `setVRFSystem()`, HR uses `setRatedEvaporativeCapacity`, radiant surface types are plural (`Floors`/`Ceilings`)
- DOAS, VRF, Radiant system templates

### Phase 4F: Zone-Level Terminal Replacement ✅ COMPLETE
- `replace_zone_terminal(zone_name, terminal_type, ...)` — Replace terminal on single zone
- Enables mixed terminal types on same air loop
- Gradual retrofits and zonal control strategies
- 10 integration tests (5 example model + 5 baseline model)
- Single-zone terminal replacement for mixed configurations

### Implementation Structure:

**Skills modules under `skills/hvac_systems/`:**
- ✅ `baseline.py` — All 10 ASHRAE Appendix G baseline systems
- ✅ `wiring.py` — Common connection patterns (plant loops, OA systems)
- ✅ `validation.py` — Model integrity checks
- ✅ `catalog.py` — Template metadata (all 10 systems + 3 templates)
- ✅ `air_terminals.py` — Terminal replacement logic (Phase 4C)
- ✅ Component validation tests — 73 tests, all passing (Phase 4D)
- ✅ `templates.py` — Modern system templates: DOAS, VRF, Radiant (Phase 4E)

**Testing:** 18 integration tests + 73 component validation tests + 16 modern HVAC tests + 10 zone terminal tests = 117 total

**Delivered:** 1 skill, 9 tools (3 baseline + replace_air_terminals + replace_zone_terminal + 3 modern templates + get_baseline_system_info), 117 tests

## Phase 5 (COMPLETE ✅ — Component Properties, Controls & Loop Surgery)

**Goal:** Generic registry-driven tools to query/modify HVAC component properties, controls, and loop equipment — not 225 per-component tools.

### 5A: Component Query & Modify ✅ COMPLETE
- `list_hvac_components` — list all model HVAC components (15 types: coils, plant, fans, pumps)
- `get_component_properties` — read all registered properties with values + units
- `set_component_properties` — apply property changes, return old/new values
- Explicit per-component getter/setter functions in `components.py` (15 types)
- No dynamic dispatch or getattr() — every API call is grepable and IDE-friendly
- 15 integration tests

### 5B: Controls & Setpoints ✅ COMPLETE
- `set_economizer_properties` — modify OA controller (economizer type, drybulb limits)
- `set_sizing_properties` — modify SizingPlant (exit temp, delta-T)
- `set_setpoint_manager_properties` — modify SPM (min/max supply air temp)
- 10 integration tests

### 5C: Loop & Zone Surgery ✅ COMPLETE
- `add_supply_equipment` — create + add to plant loop supply (Boiler, Chiller, Tower)
- `remove_supply_equipment` — remove from plant loop supply
- `add_zone_equipment` — create + add to zone (Baseboard, Unit Heater)
- `remove_zone_equipment` — remove from zone
- 10 integration tests

**Delivered:** 2 skills, 10 tools, 35 integration tests

## Phase 6 (COMPLETE ✅ — Loads, Object Management, Weather & Measures)

### 6A: Load Creation ✅ COMPLETE
- 5 tools: `create_people_definition`, `create_lights_definition`, `create_electric_equipment`, `create_gas_equipment`, `create_infiltration`
- Extends existing `loads/` skill
- 12 integration tests

### 6B: Object Management ✅ COMPLETE
- 3 tools: `delete_object`, `rename_object`, `list_model_objects`
- New `object_management/` skill
- Supports 28+ types (spaces, zones, HVAC, loads, constructions, schedules)
- Cascade warnings for Space deletion
- 10 integration tests

### 6C: Weather, Design Days, SimControl & RunPeriod ✅ COMPLETE
- 7 tools: `get_weather_info`, `set_weather_file`, `add_design_day`, `get_simulation_control`, `set_simulation_control`, `get_run_period`, `set_run_period`
- `weather/` skill
- Complementary to OSW-level EPW override
- Supports WetBulb + DewPoint humidity types
- SimulationControl flags, Timestep, and RunPeriod management
- 14 integration tests

### 6D: Measures ✅ COMPLETE
- 2 tools: `list_measure_arguments`, `apply_measure`
- New `measures/` skill
- OSW-based approach (save → run measure → reload)
- Test measure at `tests/assets/measures/set_building_name/`
- 6 integration tests

## ComStock Integration ✅

- Bundled ~61 ComStock measures (tag `2025-3`) at `/opt/comstock-measures`
- `list_comstock_measures` — categorized discovery (baseline, upgrade, setup, other)
- `create_typical_building` — wrapper for `create_typical_building_from_model` measure, adds constructions/loads/HVAC/SWH/schedules to a model w/ geometry via openstudio-standards
- Auto-sets `standardsBuildingType` on building + space types if missing
- 1 skill, 2 tools

## Phase 7 (Geometry — Partial ✅)

- `create_space_from_floor_print` — extrude floor polygon to height, auto-creates floor/ceiling/walls
- `match_surfaces` — intersect + match interior boundaries across spaces
- `set_window_to_wall_ratio` — add centered window by glazing ratio
- Added to existing `geometry/` skill

## Phase 8 (COMPLETE ✅ — Bundle common-measures-gem)

**Goal:** Bundle openstudio-common-measures-gem (~79 measures) and expose 11 wrapper tools with typed args so LLMs get consistent, error-resistant recipes.

### Implemented:
- Bundled `openstudio-common-measures-gem` v0.9.0 in Docker image at `/opt/common-measures`
- Discovery: `list_common_measures` (categorized, ~79 measures)
- 10 Tier 1 wrapper tools w/ typed args:
  - **Visualization:** `view_model`, `view_simulation_data`
  - **Reporting:** `generate_results_report`, `run_qaqc_checks`
  - **Thermostat:** `adjust_thermostat_setpoints`
  - **Envelope:** `replace_window_constructions`
  - **Loads:** `enable_ideal_air_loads`, `clean_unused_objects`
  - **IDF:** `inject_idf`
  - **Location:** `change_building_location`
- `wrappers.py` pattern: typed args → measure dir + arguments dict → `apply_measure`
- Rule 10 added: bundled measures get wrapper tools, not raw apply_measure

**Delivered:** 1 skill, 11 tools, 22 integration tests

## CI Optimization ✅

- Parallelized integration tests into 4 shards w/ Docker layer caching
- Build time: ~16min → ~5min

## Bug Fixes ✅

### get_building_info NaN/Inf crash
- OpenStudio aggregate methods (`floorAreaPerPerson()`, `peoplePerFloorArea()`, etc.) return NaN/Inf when model has geometry but no people/lights/equipment
- Trigger: `create_typical_building` w/ `add_hvac=false` leaves partial state → pydantic rejects NaN in JSON serialization
- Fix: `_safe_float()` helper converts NaN/Inf → None for 12 density/ratio fields
- Audited loads + space_types extractors — already safe (is_initialized + try/except guards)

### read_run_artifact MCP size limit
- Large sim outputs (HTML reports ~900KB, SQL databases ~50MB) exceed MCP's ~1MB transport limit or flood context (~100K tokens)
- New `copy_run_artifact` tool — copies to `/runs/exports/` on host-mounted volume, ~150 byte response
- Added `offset` param to `read_run_artifact` for chunked reading
- Added `file_size`/`bytes_read` metadata to responses

## Results Extraction (COMPLETE ✅ — SQL Extraction Tools)

**Goal:** Replace ~100K-token raw HTML reads with surgical SQL extraction returning ~300-1K tokens.

### Implemented:
- 5 Tier 1 tabular extractors: `extract_end_use_breakdown`, `extract_envelope_summary`, `extract_hvac_sizing`, `extract_zone_summary`, `extract_component_sizing`
- 1 Tier 2 timeseries: `query_timeseries` (date range filter, max_points cap)
- Shared helpers: `_pivot_rows`, `_pivot_rows_map`, `_snake`, `_resolve_sql`
- Pre-baked SQL fixture: `tests/assets/eplusout_seb4.sql` (trimmed from SEB4 sim)

**Delivered:** 6 tools, 16 tests (no Docker needed)

## Claude Code Skills (COMPLETE ✅)

**Goal:** Add `.claude/skills/` prompt-based workflow guides so Claude Code (and other repo-aware agents) can orchestrate multi-tool workflows via `/slash` commands.

### Tier 3: Background Knowledge Skills
- `ashrae-baseline-guide` — ASHRAE 90.1 Table G3.1.1 system selection criteria (auto-loaded)
- `openstudio-patterns` — Tool dependencies, model object relationships, common errors (auto-loaded)
- `tool-workflows` — 12 multi-tool recipes for common operations (auto-loaded)
- Validation test: `tests/test_skill_docs.py` — checks YAML frontmatter + cross-references tool names against MCP registry

### Tier 2: Task Skills
- `/qaqc` — Pre-simulation model quality check (7 inspection tools, reports by severity)
- `/add-hvac` — Guided ASHRAE system selection based on building attributes
- `/view` — Quick 3D model visualization via ViewModel measure

### Tier 1: Workflow Skills
- `/simulate` — Fire-and-forget (`context: fork`): save → run → poll → extract metrics + end-use
- `/energy-report` — Fire-and-forget: extract all 6 result categories from completed sim
- `/new-building` — Full model creation: baseline → glazing → schedules → loads → weather → simulate
- `/retrofit` — Before/after ECM analysis with `ecm-catalog.md` supporting file

### Testing
- 7 integration tests: `test_skill_simulate.py`, `test_skill_energy_report.py`, `test_skill_qaqc.py`, `test_skill_add_hvac.py`, `test_skill_new_building.py`, `test_skill_retrofit.py`, `test_skill_view.py`
- 1 validation test: `test_skill_docs.py` (unit, no Docker)
- All added to CI shards in `.github/workflows/ci.yml`

### Documentation
- 7 example docs: `docs/examples/12_simulate.md` through `docs/examples/18_view.md`
- README updated with Examples 12-18 + Claude Code Skills table

**Delivered:** 10 skills (7 user-invocable + 3 background knowledge), 8 tests, 7 example docs

## Skill Discovery (COMPLETE ✅)

**Goal:** Serve `.claude/skills/` workflow guides to all MCP clients (Claude Desktop, Cursor, etc.) via `list_skills` / `get_skill` tools, not just repo-aware agents.

### Implemented:
- `skill_discovery` skill: `list_skills` (scan `/skills/`, parse YAML frontmatter) + `get_skill` (strip frontmatter, return body + supporting files)
- Simple frontmatter parser (no pyyaml dependency)
- `SKILLS_DIR` env var (default `/skills`), added to `ALLOWED_PATH_ROOTS`
- Path traversal protection in `get_skill`
- Graceful degradation when no skills directory mounted
- Docker volume mount: `-v ./.claude/skills:/skills:ro`

### Testing:
- 14 unit tests: `tests/test_skill_tools.py` (frontmatter parsing, list/get with various dir states)
- 1 integration test: `tests/test_skill_tools_integration.py` (MCP client calling both tools)
- Updated `tests/test_skill_registration.py` with new tool names

**Delivered:** 1 skill, 2 tools, 15 tests
