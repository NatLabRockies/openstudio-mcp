# CLAUDE.md — Instructions for Claude Code

## Project: openstudio-mcp
Building energy simulation MCP server using OpenStudio SDK Python bindings and Measures.

**Template project:** This codebase is designed as a reference implementation
that other building energy simulation engines (EnergyPlus, TRNSYS, DOE-2, etc.)
can use as a template. Code must be explicit, well-commented, and easy for
contributors unfamiliar with OpenStudio to understand and adapt.

## Critical: Use MCP Tools — Do Not Reinvent
Always use openstudio-mcp tools for BEM tasks:
- Never generate raw IDF files
- OSM files are created/modified only through MCP tools (create_baseline_osm, create_example_osm, etc.)
- Never write Python/Ruby scripts to parse SQL results, create visualizations, build HVAC wiring, or extract data — equivalent MCP tools already exist (extract_*, query_timeseries, view_model, view_simulation_data, add_baseline_system, etc.)
- If a task genuinely cannot be done with existing tools, ASK THE USER before writing any code or scripts
- For workflow guidance, run: `list_skills()` or `get_skill("new-building")`

## Architecture

### Skills Pattern
- Each skill lives in `mcp_server/skills/<name>/`
- `tools.py` exports `register(mcp)` — MCP tool definitions only
- `operations.py` — business logic, returns plain dicts, no MCP awareness
- `SKILL.md` — Anthropic-style skill definition (Phase 2+)

## Key Modules
- `model_manager.py` — `load_model()`, `get_model()`, `save_model()`, `clear_model()`
- `osm_helpers.py` — `fetch_object()`, `optional_name()`, `list_all_as_dicts()`
- `skills/__init__.py` — `register_all_skills(mcp)` auto-discovers all skills

## Phase Roadmap

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ COMPLETE | Scaffold + migrate existing tools (server info, model mgmt, simulation, results) |
| Phase 2 | ✅ COMPLETE | Query skills - 10 skills, 35 tools |
| Phase 3 | ✅ COMPLETE | Creation tools - 9 tools (spaces/zones/air loops, schedules/outputs, materials/constructions) |
| Phase 4 | ✅ COMPLETE | System-level HVAC templates (10 ASHRAE baseline systems + modern templates) |
| Phase 5 | ✅ COMPLETE | Component properties, controls & loop surgery (2 skills, 10 tools) |
| Phase 6 | ✅ COMPLETE | Loads, object management, weather & measures (3 skills, 13 tools) |
| Phase 7 | 📋 FUTURE | Advanced creation (geometry, space type wizard) |
| Phase 8 | ✅ COMPLETE | Bundle common-measures-gem (20 measures, 11 tools: reporting, thermostat, envelope, PV, visualization) |

## Current Skills
| Skill | Tools | Phase |
|-------|-------|-------|
| `server_info` | `get_server_status`, `get_versions` | Phase 1 |
| `model_management` | `create_example_osm`, `create_baseline_osm`, `inspect_osm_summary`, `load_osm_model`, `save_osm_model`, `list_files` | Phase 1 + 2 |
| `simulation` | `validate_osw`, `run_osw`, `run_simulation`, `get_run_status`, `get_run_logs`, `get_run_artifacts`, `cancel_run` | Phase 1 |
| `results` | `extract_summary_metrics`, `read_file`, `copy_file`, `extract_end_use_breakdown`, `extract_envelope_summary`, `extract_hvac_sizing`, `extract_zone_summary`, `extract_component_sizing`, `query_timeseries` | Phase 1 + 9 |
| `building` | `get_building_info`, `get_model_summary`, `list_building_stories` | Phase 2 |
| `spaces` | `list_spaces`, `get_space_details`, `list_thermal_zones`, `get_thermal_zone_details`, `create_space`, `create_thermal_zone` | Phase 2 + 3 |
| `geometry` | `list_surfaces`, `get_surface_details`, `list_subsurfaces`, `create_surface`, `create_subsurface`, `create_space_from_floor_print`, `match_surfaces`, `set_window_to_wall_ratio`, `import_floorspacejs` | Phase 2 + 7 |
| `constructions` | `list_materials`, `list_constructions`, `list_construction_sets`, `create_standard_opaque_material`, `create_construction`, `assign_construction_to_surface` | Phase 2 + 3 |
| `schedules` | `list_schedule_rulesets`, `get_schedule_details`, `create_schedule_ruleset` | Phase 2 + 3 |
| `hvac` | `list_air_loops`, `get_air_loop_details`, `list_plant_loops`, `get_plant_loop_details`, `list_zone_hvac_equipment`, `get_zone_hvac_details`, `add_air_loop` | Phase 2 + 3 |
| `loads` | `list_people_loads`, `list_lighting_loads`, `list_electric_equipment`, `list_gas_equipment`, `list_infiltration`, `create_people_definition`, `create_lights_definition`, `create_electric_equipment`, `create_gas_equipment`, `create_infiltration` | Phase 2 + 6A |
| `space_types` | `list_space_types`, `get_space_type_details` | Phase 2 |
| `simulation_outputs` | `add_output_variable`, `add_output_meter` | Phase 3 |
| `hvac_systems` | `add_baseline_system`, `list_baseline_systems`, `get_baseline_system_info`, `replace_air_terminals`, `replace_zone_terminal`, `add_doas_system`, `add_vrf_system`, `add_radiant_system` | Phase 4 |
| `component_properties` | `list_hvac_components`, `get_component_properties`, `set_component_properties`, `set_economizer_properties`, `set_sizing_properties`, `set_sizing_system_properties`, `get_sizing_system_properties`, `set_sizing_zone_properties`, `get_sizing_zone_properties`, `get_setpoint_manager_properties`, `set_setpoint_manager_properties` | Phase 5 |
| `loop_operations` | `create_plant_loop`, `add_supply_equipment`, `remove_supply_equipment`, `add_demand_component`, `remove_demand_component`, `add_zone_equipment`, `remove_zone_equipment`, `remove_all_zone_equipment` | Phase 5 |
| `object_management` | `delete_object`, `rename_object`, `list_model_objects` | Phase 6B |
| `weather` | `get_weather_info`, `add_design_day`, `get_simulation_control`, `set_simulation_control`, `get_run_period`, `set_run_period` | Phase 6C |
| `measures` | `list_measure_arguments`, `apply_measure` | Phase 6D |
| `comstock` | `list_comstock_measures`, `create_bar_building`, `create_typical_building`, `create_new_building` | ComStock |
| `common_measures` | `list_common_measures`, `view_model`, `view_simulation_data`, `generate_results_report`, `run_qaqc_checks`, `adjust_thermostat_setpoints`, `replace_window_constructions`, `enable_ideal_air_loads`, `clean_unused_objects`, `change_building_location`, `set_thermostat_schedules`, `replace_thermostat_schedules`, `shift_schedule_time`, `add_rooftop_pv`, `add_pv_to_shading`, `add_ev_load`, `add_zone_ventilation`, `set_lifecycle_cost_params`, `add_cost_per_floor_area`, `set_adiabatic_boundaries` | Phase 8 |
| `skill_discovery` | `list_skills`, `get_skill` | — |

**Total: 22 skills, 136 MCP tools, ~280 integration tests**

## Model Query Pattern
```python
from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import optional_name, list_all_as_dicts

def _extract_thing(model, obj) -> dict:
    return {"name": obj.nameString(), "attr": optional_name(obj.someOptional())}

def list_things_op() -> dict:
    model = get_model()
    items = list_all_as_dicts(model, "getThings", _extract_thing)
    return {"ok": True, "count": len(items), "items": items}
```

## Stdout Suppression for MCP
OpenStudio SWIG bindings print memory leak warnings to stdout, which breaks MCP JSON-RPC protocol.
The `stdout_suppression.py` module handles this:
- `suppress_openstudio_warnings()` context manager redirects stdout→stderr during operations
- `atexit` handler catches warnings during Python cleanup/garbage collection
- Already integrated into `model_manager.py` and `model_management/operations.py`
- No action needed for new skills unless they create/load models outside of `model_manager`

## Commands

### Docker Build & Test (Primary)
```bash
docker build -f docker/Dockerfile -t openstudio-mcp:dev .
```

Run all tests inside a single Docker container (fastest, matches CI):
```bash
docker run --rm \
  -v "C:/projects/openstudio-mcp:/repo" \
  -v "C:/projects/openstudio-mcp/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 \
  -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_*.py"
```

Run specific test file:
```bash
docker run --rm \
  -v "C:/projects/openstudio-mcp:/repo" \
  -v "C:/projects/openstudio-mcp/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 \
  -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_load_save_model.py"
```

Slow alternative (spawns a new Docker container per test — ~14 min vs ~9 min):
```bash
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" \
  RUN_OPENSTUDIO_INTEGRATION=1 \
  MCP_RUNS_HOST_DIR="/c/projects/openstudio-mcp/runs" \
  MCP_SERVER_CMD=docker \
  MCP_SERVER_ARGS="run --rm -i \
    -v /c/projects/openstudio-mcp/tests/assets/SEB_model:/inputs \
    -v /c/projects/openstudio-mcp/runs:/runs \
    -e OPENSTUDIO_MCP_MODE=prod \
    openstudio-mcp:dev openstudio-mcp" \
  pytest -vv tests/test_*.py
```

### LLM Tests (Claude Max usage)
Each `claude -p` invocation loads ~27K tokens of tool definitions. Full suite (90 tests)
uses ~9M cache tokens per run. To minimize usage:
- **Iterate with targeted tests:** `LLM_TESTS_ENABLED=1 pytest tests/llm/test_06_progressive.py -k "thermostat_L1" -v`
- **Run full suite only for final validation**
- **Use tier filters:** `LLM_TESTS_TIER=1` runs only tier 1 (14 tests, ~5 min)

### Local Development
- Lint: `ruff check mcp_server/`
- Unit tests (no Docker): `pytest tests/test_skill_registration.py -v`

### Notes
- Integration tests require Docker and OpenStudio
- Use `C:/` Windows-style paths for Docker volume mounts (MSYS `/c/` paths don't resolve dotfile dirs)
- Tests create temporary models in `runs/` (mounted as `/runs` in container)
- After builds, prune dangling images: `docker image prune -f`

### Adding New Tests to CI
CI uses 4 parallel shards in `.github/workflows/ci.yml`. To add a new test file,
append it to the lightest shard's `FILES=` list in the `case` block. Keep shards
roughly balanced (~200s each). See shard comments in the workflow for current balance.

## API Reference
- **OpenStudio SDK (3.11.0):** `openstudio.model` (70+ classes), `openstudio.osversion.VersionTranslator`, `openstudio.BCLMeasure`
  - SDK docs: https://openstudio-sdk-documentation.s3.amazonaws.com/index.html
- **OpenStudio CLI:** `openstudio run -w <osw>` (simulation), `openstudio run --measures_only -w <osw>` (measure execution)
- **openstudio-resources** — HVAC wiring patterns, baseline model geometry
  - https://github.com/NatLabRockies/OpenStudio-resources/tree/develop/model/simulationtests
- **ComStock measures** (~61 bundled) — standards-based templates for typical buildings
  - https://github.com/NatLabRockies/ComStock (tag: `2025-3`, installed at `/opt/comstock-measures`)

## Adding New Component Types
To add a new HVAC component type to `component_properties`:
1. Add a `_get_<type>_props(obj)` function in `components.py` — returns dict of
   property_name -> {"value": ..., "unit": "..."}. Comment each API call.
2. Add a `_set_<type>_props(obj, properties)` function — uses explicit if/elif
   for each property. Returns (changes_dict, errors_list).
3. Add an entry to `COMPONENT_TYPES` at the bottom of `components.py`.
4. Add a test in `tests/test_component_properties.py`.

**No getattr() or string-based dispatch.** Every OpenStudio API method must be
called directly so it's grepable, lintable, and visible in stack traces.

## Adding Setpoint Manager Types
To add a new SPM type to `set_setpoint_manager_properties`:
1. Add a `_get_spm_<type>_props(obj)` function in `operations.py` — returns dict of
   property_name -> {"value": ..., "unit": "..."}
2. Add a `_set_spm_<type>_props(obj, properties)` function — explicit if/elif per property.
   Returns (changes_dict, errors_list).
3. Add an entry to `SPM_TYPES` registry with getter method name and get/set functions.
4. Add a test in `tests/test_component_controls.py`.

## Active Fix Plan
See `docs/debug/fix-plan.md` for current work items (11 items from Claude Desktop
debug sessions). Key changes: remove inject_idf, rename read_run_artifact→read_file,
list_files redesign, sizing system/zone tools, 6 new SPM types.

## Rules
1. Keep files small where practical — aim for under 250 lines, but don't split artificially just to hit a number
2. Every MCP tool must have a test in `tests/skills/` (Phase 2+) or `tests/` (existing)
3. **Integration tests must be added to `.github/workflows/ci.yml`** — add a new step following the existing pattern
4. Operations return dicts with `{"ok": True/False, ...}` — never raise through MCP
5. Use `openstudio` Python bindings directly.
6. All OpenStudio attribute access must handle `is_initialized()` checks
7. `_extract_*` functions return dicts with `snake_case` keys matching OpenStudio attribute names
8. Python tool functions keep `_tool` suffix (avoids import collision with operations.py), but MCP-visible names strip it via `@mcp.tool(name="...")`
9. **Never commit generated/temp files** — `.gitignore` covers `__pycache__/`, `*.pyc`, `runs/`, `.claude/`, `.pytest_cache/`. If adding new generated paths, update `.gitignore` first. Test artifacts (OSM files from `create_example_osm`) go to `runs/` which is gitignored. Only permanent reference models belong in `tests/assets/`.
10. **Bundled measures get wrapper tools** — don't expose raw `apply_measure` as the primary interface for bundled measures. Build named wrapper tools with typed args so LLMs get a consistent, error-resistant recipe every time.
