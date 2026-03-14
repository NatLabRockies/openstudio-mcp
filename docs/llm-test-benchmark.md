# LLM Test Benchmark Report

## Latest Run Summary

| Run | Date | Model | Tests | Passed | Rate | Runtime | Notes |
|-----|------|-------|-------|--------|------|---------|-------|
| **7** | **2026-03-12** | **sonnet** | **159** | **155** | **97.5%** | **94 min** | **Test consolidation (no tool/prompt changes)** |

*Cost is notional API pricing from Claude Code CLI — free on Claude Max.*

## Per-Tool Discovery Matrix

One row per progressive case. L1=vague, L2=moderate, L3=explicit.

| Case | Tool(s) | L1 | L2 | L3 | Flaky? | Added | Notes |
|------|---------|----|----|-----|--------|-------|-------|
| import_floorplan | import_floorspacejs | FAIL | PASS | PASS | L1 | Run 2 | No file path in prompt — agent asks for one |
| add_hvac | add_baseline_system | PASS | PASS | PASS | L1 | Run 2 | Was flaky L1 before docstring fix (Run 3) |
| view_model | view_model | PASS | PASS | PASS | — | Run 2 | |
| set_weather | change_building_location | PASS | PASS | PASS | — | Run 2 | |
| run_qaqc | run_qaqc_checks | PASS | PASS | PASS | — | Run 2 | Accepts pre-sim QA tools too |
| create_building | create_new_building | PASS | PASS | PASS | — | Run 2 | |
| add_pv | add_rooftop_pv | PASS | PASS | PASS | — | Run 2 | |
| thermostat | adjust_thermostat_setpoints | PASS | PASS | PASS | L1 | Run 2 | Was flaky L1 until prompt used offsets (Run 3) |
| list_spaces | list_spaces | PASS | PASS | PASS | — | Run 2 | |
| schedules | get_schedule_details | PASS | PASS | PASS | — | Run 2 | |
| inspect_component | get_component_properties | PASS | PASS | PASS | — | Run 5 | Generic access test |
| modify_component | set_component_properties | PASS | PASS | PASS | — | Run 5 | Generic access test |
| list_dynamic_type | list_model_objects | FAIL | PASS | PASS | L1 | Run 5 | L1 uses explicit sizing tools instead |
| floor_area | get_building_info | PASS | PASS | PASS | — | Run 5 | |
| materials | list_materials | PASS | PASS | PASS | — | Run 5 | |
| thermal_zones | list_thermal_zones | PASS | PASS | PASS | — | Run 5 | |
| subsurfaces | list_subsurfaces | PASS | PASS | PASS | — | Run 5 | |
| surface_details | get_surface_details | PASS | PASS | PASS | — | Run 5 | |
| run_simulation | run_simulation | PASS | PASS | PASS | — | Run 6 | |
| get_eui | extract_summary_metrics | PASS | PASS | PASS | — | Run 6 | |
| end_use_breakdown | extract_end_use_breakdown | PASS | PASS | PASS | — | Run 6 | |
| hvac_sizing | extract_hvac_sizing | PASS | PASS | PASS | — | Run 6 | |
| set_wwr | set_window_to_wall_ratio | PASS | PASS | PASS | L1 | Run 6 | |
| replace_windows | replace_window_constructions | PASS | PASS | PASS | — | Run 6 | |
| construction_details | get_construction_details | PASS | PASS | PASS | — | Run 6 | |
| check_loads | get_load_details | FAIL | PASS | PASS | L1 | Run 6 | "What loads?" too vague |
| create_loads | create_people_definition + create_lights_definition | PASS | PASS | PASS | L1 | Run 6 | |
| create_plant_loop | create_plant_loop | PASS | PASS | PASS | — | Run 6 | |
| schedule_details | get_schedule_details | PASS | PASS | PASS | L1 | Run 6 | |
| space_type_info | get_space_type_details | PASS | PASS | PASS | — | Run 6 | |
| set_run_period | set_run_period | PASS | PASS | PASS | — | Run 6 | |
| ideal_air | enable_ideal_air_loads | PASS | PASS | PASS | L1 | Run 6 | |
| save_model | save_osm_model | PASS | PASS | PASS | L1 | Run 6 | |
| add_ev | add_ev_load | PASS | PASS | PASS | — | Run 6 | |
| list_measures | list_custom_measures | PASS | PASS | PASS | — | Run 8 | Measure authoring |
| create_measure | create_measure | PASS | PASS | PASS | — | Run 8 | |
| test_measure | test_measure | PASS | PASS | PASS | — | Run 8 | |
| export_measure | export_measure | FAIL | FAIL | PASS | L1+L2 | Run 8 | Agent can't discover export without explicit name |
| edit_measure | edit_measure | PASS | PASS | PASS | — | Run 8 | |
| replace_terminals_cooled_beam | replace_air_terminals | PASS | PASS | PASS | — | Run 8 | CooledBeam 2-pipe docstring works well |
| measure_replace_terminals | create_measure | PASS | PASS | PASS | — | Run 8 | Agent chose measure authoring path at L1 |
| zone_equipment_priority | set_zone_equipment_priority | PASS | PASS | PASS | — | Run 8 | Prompt must add equipment first |
| **Totals** | | **38/42** | **40/42** | **42/42** | | | |

**Summary:** L1=90%, L2=95%, L3=100%

*Run 8 cases (measure authoring, cooled beam) tested separately — not yet in main suite run.*

## Per-Tier Summary (Run 7)

| Tier | Passed | Total | Rate |
|------|--------|-------|------|
| setup | 5 | 5 | 100% |
| tier1 | 4 | 4 | 100% |
| tier2 | 18 | 19 | 95% |
| tier3 | 26 | 26 | 100% |
| tier4 | 3 | 3 | 100% |
| progressive | 99 | 102 | 97% |
| **Total** | **155** | **159** | **97.5%** |

## Workflow Tests

| Workflow | Required Tools | Result | Notes |
|----------|---------------|--------|-------|
| Add VAV reheat | load + list_thermal_zones + add_baseline_system | PASS | |
| Add DOAS | load + list_thermal_zones + add_doas_system | PASS | |
| Add VRF | load + list_thermal_zones + add_vrf_system | PASS | |
| Set weather | load + change_building_location | PASS | |
| Add PV | load + add_rooftop_pv | PASS | |
| Delete space | load + list_spaces + delete_object | PASS | |
| Bar building | create_bar_building + list_spaces | PASS | |
| New building | create_new_building | PASS | |
| Bar then typical | create_bar + change_building_location + create_typical | PASS | |
| Import floorspacejs | import_floorspacejs + list_files | PASS | |
| Surface matching | create_space_from_floor_print x2 + match_surfaces | PASS | |
| FloorspaceJS to typical | import + weather + create_typical + sim | FLAKY | Multi-step chain stalls |
| Envelope retrofit | load + set_wwr + replace_windows | PASS | Run 6+ |
| Create+assign loads | load + create_people + create_lights | PASS | Run 6+ |
| Plant loop w/ boiler | load + create_plant_loop + add_supply_equipment | PASS | Run 6+ |
| Extract results chain | extract_summary_metrics + extract_end_use_breakdown | PASS | Run 6+ |
| HVAC chilled beam comparison | load + replace_air_terminals + sim + extract | PASS | 22 turns (sim recovery) |

## Token & Cost Profile

| Tier | Avg In | Avg Out | Avg Cache | Avg Cost | Avg Turns |
|------|--------|---------|-----------|----------|-----------|
| setup | — | — | — | — | — |
| tier1 | ~10 | ~400 | ~45k | $0.06 | 3 |
| tier2 | ~15 | ~800 | ~80k | $0.10 | 5 |
| tier3 | ~10 | ~500 | ~50k | $0.07 | 3 |
| progressive | ~10 | ~400 | ~45k | $0.06 | 3 |
| measure authoring | ~9 | ~600 | ~64k | $0.06 | 4 |
| cooled beam workflow | 30 | 2.8k | 495k | $0.28 | 22 |

## Run History

| Run | Date | Tests | Passed | Rate | Cost | Changes |
|-----|------|-------|--------|------|------|---------|
| 1 | 2026-03-05 | 50 | 22 | 44.0% | $9.31 | Baseline (no system prompt, wrong model path) |
| 2 | 2026-03-06 | 90 | 75 | 83.3% | $11.55 | + system prompt, model path fix, pre-check |
| 3 | 2026-03-07 | 90 | 82 | 91.1% | $11.39 | + test def fixes, tool description improvements |
| 4 | 2026-03-07 | 90 | 84 | 93.3% | $11.62 | No code changes (stability run) |
| 5 | 2026-03-10 | 107 | 103 | 96.3% | $8.87 | + generic access tests, test cleanup |
| 6 | 2026-03-11 | 159 | 153 | 96.2% | — | + 16 progressive cases, 4 workflows, sim setup |
| 7 | 2026-03-12 | 159 | 155 | 97.5% | — | Test consolidation (no tool/prompt changes) |
| 8* | 2026-03-13 | 25 | 23 | 92.0% | $3.01 | Measure authoring + cooled beam (separate runs) |

*Run 8 = combined results from two separate targeted runs (measure authoring 13/15 + cooled beam 10/10).*

## Tool Verification Failures

Only cases where expected tool wasn't called.

| Test | Expected Tool | Actually Called | Root Cause |
|------|--------------|----------------|------------|
| import_floorplan_L1 | import_floorspacejs | (asks for file path) | No path in prompt — structurally vague |
| list_dynamic_type_L1 | list_model_objects | get_sizing_zone_properties | L1 "What sizing parameters?" → explicit tool |
| check_loads_L1 | get_load_details | get_space_details | "What loads?" too vague without direction |
| export_measure_L1 | export_measure | list_custom_measures | Can't discover export without explicit name |
| export_measure_L2 | export_measure | list_custom_measures + list_files | Moderate prompt still insufficient |

## Known Flaky Tests

| Test | Root Cause |
|------|-----------|
| import_floorplan_L1 | No file path in prompt — agent correctly asks for one |
| list_dynamic_type_L1 | L1 "sizing parameters" too vague, agent uses explicit sizing tools |
| check_loads_L1 | "What loads?" too vague, agent inspects space instead |
| thermostat_L1 | Intermittent — "change thermostat settings" needs direction |
| save_model_L1 | Intermittent |
| schedule_details_L1 | Intermittent |
| create_loads_L1 | Intermittent |
| set_wwr_L1 | Intermittent |
| ideal_air_L1 | Intermittent |
| add_hvac_L1 | Intermittent — stable since docstring fix |
| export_measure_L1/L2 | Tool not discoverable without explicit name |
| floorspacejs_to_typical | Multi-step workflow chain stalls after step 1 |

## Key Lessons & Patterns

1. **System prompt is the biggest lever** — adding anti-loop guidance took pass rate from 44% → 83% in one run
2. **Tool descriptions drive L1 discovery** — adding "HVAC / heating and cooling" keywords to `add_baseline_system` fixed L1 discovery immediately
3. **L1 failures are mostly structural** — vague prompts missing required info (file paths, direction). Correct agent behavior is to ask.
4. **L2 → L3 gap is rare** — once moderate context is given, agents find tools. L3 is 100% across all 42 cases.
5. **Progressive tests are the best diagnostic** — L1/L2/L3 clearly separates tool description gaps from tool design gaps
6. **Multi-step workflows are fragile** — floorspacejs_to_typical consistently stalls. Single-tool discovery is robust.
7. **Retries help** — default retries=2 catches transient failures. retries=1 is useful for first-attempt signal.
8. **Generic access pattern works** — inspect_component/modify_component pass at all levels, validating Phase C's dynamic property access

## Running

```bash
# Full suite (~100 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v

# Quick smoke (~12 min, 12 tests)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m smoke -v

# Progressive only (~60 min, 102 tests)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m progressive -v

# Single case
LLM_TESTS_ENABLED=1 pytest tests/llm/test_06_progressive.py -k "thermostat_L1" -v
```

Reports written to `LLM_TESTS_RUNS_DIR/benchmark.md` and `benchmark.json`.
After running, copy to `docs/llm-test-benchmark.md`.
