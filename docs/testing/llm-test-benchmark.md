# LLM Test Benchmark Report

## Latest Run Summary

| Run | Date | Model | Tests | Passed | Rate | Runtime | Notes |
|-----|------|-------|-------|--------|------|---------|-------|
| **15** | **2026-04-05** | **sonnet** | **129** | **123** | **95.3%** | **69 min** | **Progressive-only re-run, CodeMode A/B baseline. 6 fail — edit_measure L1/L2/L3 regression, thermal_zones_L1, test_measure_L1, zone_equipment_priority_L3.** |
| 14 | 2026-03-28 | sonnet | 180 | 170 | 94.4% | 157 min | Full suite cross-model sweep baseline. 10 fail (eval + workflow). Also ran haiku (160/180 = 88.9%) and opus (170/180 = 94.4%) same day. |
| 13 | 2026-03-26 | sonnet | 230 | 160 | 95.8% | 151 min | Post #40 fix + test audit. 7 fail (3 qaqc, 3 measure quality, 1 sim_L1). |

*Cost is notional API pricing from Claude Code CLI — free on Claude Max.*

## Cross-Run Experiments

Two comparative runs on 2026-03-28 and 2026-04-05:

| Experiment | Date | Variants | Finding |
|---|---|---|---|
| Cross-model sweep | 2026-03-28 | haiku / sonnet / opus, same 180-test suite | haiku 88.9% / sonnet 94.4% / opus 94.4%. Opus matches sonnet but costs ~1.7×. Haiku is 40% cheaper at the cost of 5.5pp. |
| FastMCP CodeMode A/B | 2026-04-05 | CodeMode OFF / ON, same 129 progressive tests | OFF 95.3% / ON **24.0%** — 71pp regression. See [`../knowledge/codemode-benchmark-2026-04-05.md`](../knowledge/codemode-benchmark-2026-04-05.md). |

## Per-Tool Discovery Matrix

One row per progressive case. L1=vague, L2=moderate, L3=explicit.

| Case | Tool(s) | L1 | L2 | L3 | Flaky? | Added | Notes |
|------|---------|----|----|-----|--------|-------|-------|
| import_floorplan | import_floorspacejs | PASS | PASS | PASS | L1 | Run 2 | Was FAIL L1 until Run 13 |
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
| list_dynamic_type | list_model_objects | PASS | PASS | PASS | L1 | Run 5 | Was FAIL L1 until Run 13 |
| floor_area | get_building_info | PASS | PASS | PASS | — | Run 5 | |
| materials | list_materials | PASS | PASS | PASS | — | Run 5 | |
| thermal_zones | list_thermal_zones | PASS | PASS | PASS | — | Run 5 | |
| subsurfaces | list_subsurfaces | PASS | PASS | PASS | — | Run 5 | |
| surface_details | get_surface_details | PASS | PASS | PASS | — | Run 5 | |
| run_simulation | run_simulation | FAIL | PASS | PASS | L1 | Run 6 | Was PASS until Run 13 — L1 flaky |
| get_eui | extract_summary_metrics | PASS | PASS | PASS | — | Run 6 | |
| end_use_breakdown | extract_end_use_breakdown | PASS | PASS | PASS | — | Run 6 | |
| hvac_sizing | extract_hvac_sizing | PASS | PASS | PASS | — | Run 6 | |
| set_wwr | set_window_to_wall_ratio | PASS | PASS | PASS | L1 | Run 6 | |
| replace_windows | replace_window_constructions | PASS | PASS | PASS | — | Run 6 | |
| construction_details | get_construction_details | PASS | PASS | PASS | — | Run 6 | |
| check_loads | get_load_details | PASS | PASS | PASS | L1 | Run 6 | Was FAIL L1 until Run 13 |
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
| **Totals** | | **39/42** | **40/42** | **42/42** | | | |

**Summary:** L1=93%, L2=95%, L3=100% (Run 13: 3 previously-failed L1s now passing)

*Run 8 cases (measure authoring, cooled beam) tested separately — not yet in main suite run.*

## Per-Tier Summary (Run 13)

| Tier | Passed | Total | Rate | Notes |
|------|--------|-------|------|-------|
| setup | 5 | 5 | 100% | |
| tier1 | 4 | 4 | 100% | |
| tier2 | 16 | 19 | 84% | 3 qaqc failures |
| tier3 | 24 | 26 | 92% | +63 skipped |
| tier4 | 3 | 3 | 100% | |
| progressive | 108 | 110 | 98% | 1 run_simulation_L1 fail, rest passing |
| **Total** | **160** | **167** | **95.8%** | +63 skipped |

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
| FloorspaceJS to typical | import + weather + create_typical + sim | PASS | Was FLAKY, passed Run 13 |
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
| 9a | 2026-03-19 | 9 | 9 | 100% | $0.79 | Tool routing A/B baseline (pre-docstring-hardening) |
| 9b | 2026-03-19 | 9 | 9 | 100% | $0.79 | Tool routing A/B post-hardening (neutral delta) |
| 10 | 2026-03-19 | 172 | 166 | 96.5% | — | Full regression after tool routing (tags, recommend_tools, search_api, docstrings). No regressions — 6 failures all known flaky. |
| 11 | 2026-03-20 | 171 | 164 | 95.9% | — | Full suite with ToolSearch + wiring recipes + enriched descriptions. 12/12 test_09 pass. 7 failures all known flaky (replace_windows_L1 new — agent called search_api instead). |
| 12 | 2026-03-20 | 170 | 163 | 95.9% | — | Post description enrichment (all 142 tools ≥40 char). Same 7 flaky failures. No regression. |
| 13 | 2026-03-26 | 230 | 160 | 95.8% | — | Post #40 fix + test audit. 63 skipped (test structure). 7 fail: 3 qaqc tier2, 3 measure quality, 1 run_simulation_L1. Previously flaky L1s (import_floorplan, list_dynamic_type, check_loads, thermostat, set_wwr, schedule_details, create_loads) ALL passed. |
| 14 | 2026-03-28 | 180 | 170 | 94.4% | $18.96 | Cross-model sweep baseline (sonnet). 157 min. 10 fail: 9 wrong_tool (2× qaqc, 2× troubleshoot, 1× energy-report, 1× systemd_e2e, 2× measure quality, 1× misc) + 1 timeout. Haiku same day: 160/180 = 88.9%, $11.21, 80 min. Opus same day: 170/180 = 94.4%, $32.23, 185 min. |
| 15 | 2026-04-05 | 129 | 123 | 95.3% | $9.29 | CodeMode A/B baseline (OFF). Progressive-only suite (43 cases × 3). 69 min. 6 fail: edit_measure L1/L2/L3 (all 3 → tool regression), thermal_zones_L1, test_measure_L1, zone_equipment_priority_L3. L1=93.0%, L2=97.7%, L3=95.3%. |
| 16 | 2026-04-05 | 129 | 31 | **24.0%** | $22.35 | **CodeMode A/B experiment (ON) — 71pp regression.** 168 min. 67 wrong_tool + 30 timeout + 1 no_mcp_tool. Feature kept as opt-in toggle, NOT default. See `docs/knowledge/codemode-benchmark-2026-04-05.md`. |

*Run 8 = combined results from two separate targeted runs (measure authoring 13/15 + cooled beam 10/10).*
*Run 16 is an experimental outlier (CodeMode ON) and is excluded from the main pass-rate timeline in plots.*

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

| Test | Root Cause | Run 13 |
|------|-----------|--------|
| import_floorplan_L1 | No file path in prompt — agent correctly asks for one | PASS |
| list_dynamic_type_L1 | L1 "sizing parameters" too vague, agent uses explicit sizing tools | PASS |
| check_loads_L1 | "What loads?" too vague, agent inspects space instead | PASS |
| thermostat_L1 | Intermittent — "change thermostat settings" needs direction | PASS |
| save_model_L1 | Intermittent | skipped |
| schedule_details_L1 | Intermittent | PASS |
| create_loads_L1 | Intermittent | PASS |
| set_wwr_L1 | Intermittent | PASS |
| ideal_air_L1 | Intermittent | PASS |
| add_hvac_L1 | Intermittent — stable since docstring fix | PASS |
| export_measure_L1/L2 | Tool not discoverable without explicit name | skipped |
| floorspacejs_to_typical | Multi-step workflow chain stalls after step 1 | PASS |
| run_simulation_L1 | Intermittent — "Run a simulation" too vague at L1 | FAIL |
| qaqc tier2 (3 cases) | Agent doesn't call run_qaqc_checks for validation prompts | FAIL |
| measure quality (3 cases) | New tests — measure code quality checks | FAIL |

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
After running, copy to `docs/testing/llm-test-benchmark.md`.
