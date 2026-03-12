# LLM Test Benchmark Report — 2026-03-12

## Run History

| Run | Tests | Passed | Rate  | Cost   | Changes |
|-----|-------|--------|-------|--------|---------|
| 1   | 50    | 22     | 44.0% | $9.31  | Baseline (no system prompt, wrong model path) |
| 2   | 90    | 75     | 83.3% | $11.55 | + system prompt, model path fix, pre-check |
| 3   | 90    | 82     | 91.1% | $11.39 | + test definition fixes, tool description improvements |
| 4   | 90    | 84     | 93.3% | $11.62 | No code changes (stability run) |
| 5   | 107   | 103    | 96.3% | $8.87  | + generic access tests, test cleanup |
| **6** | **159** | **153** | **96.2%** | **—** | **+ 16 progressive cases, 4 workflows, sim setup** |

*Cost is notional API pricing reported by Claude Code CLI, not actual charges.
On Claude Max (subscription), these tests run at no additional cost.*

## Run 6 Changes

- **+52 new tests:** 16 progressive cases (48 at L1/L2/L3) + 4 workflow cases
- **+1 setup test:** `test_run_baseline_simulation` (weather + sim + save run_id)
- **Net: 107 → 159 tests**
- New progressive categories: simulation, results extraction, envelope, loads, plant loops, schedules, space types, design conditions, model management, EV
- New workflow cases: envelope_retrofit, create_and_assign_loads, plant_loop_with_boiler, extract_results_chain
- `needs_run` pattern: results tests read saved run_id from test_01_setup
- 6 new flaky IDs added: save_model_L1, schedule_details_L1, create_loads_L1, set_wwr_L1, check_loads_L1, ideal_air_L1
- 3 new smoke IDs: get_eui_L3, set_wwr_L3, save_model_L3

### Per-Tier Comparison

| Tier        | Run 5 (107 tests) | Run 6 (159 tests) | Notes |
|-------------|--------------------|--------------------|-------|
| setup       | 5/5 100%           | 5/5 100%           | +1 sim setup (within existing 5) |
| tier1       | 4/4 100%           | 4/4 100%           | Unchanged |
| tier2       | 14/15 93%          | 17/19 89%          | +4 workflows, 1 flaky (floorspacejs_to_typical) |
| tier3       | 26/26 100%         | 24/26 92%          | 2 eval failures (energy-report, retrofit) |
| tier4       | 3/3 100%           | 3/3 100%           | Unchanged |
| progressive | 51/54 94%          | 99/102 97%         | +48 tests (16 new cases x 3 levels) |

### Progressive Prompt Comparison (Run 5 → Run 6)

| Case             | R5 L1 | R5 L2 | R5 L3 | R6 L1 | R6 L2 | R6 L3 |
|------------------|-------|-------|-------|-------|-------|-------|
| import_floorplan | FAIL  | PASS  | PASS  | FAIL  | PASS  | PASS  |
| add_hvac         | FAIL  | PASS  | PASS  | PASS  | PASS  | PASS  |
| view_model       | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| set_weather      | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| run_qaqc         | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| create_building  | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| add_pv           | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| thermostat       | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| list_spaces      | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| schedules        | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| inspect_component | PASS | PASS  | PASS  | PASS  | PASS  | PASS  |
| modify_component | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| list_dynamic_type | FAIL | PASS  | PASS  | FAIL  | PASS  | PASS  |
| floor_area       | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| materials        | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| thermal_zones    | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| subsurfaces      | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| surface_details  | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| **run_simulation** | — | — | — | **PASS** | **PASS** | **PASS** |
| **get_eui**      | —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **end_use_breakdown** | — | — | — | **PASS** | **PASS** | **PASS** |
| **hvac_sizing**  | —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **set_wwr**      | —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **replace_windows** | — | —     | —     | **PASS** | **PASS** | **PASS** |
| **construction_details** | — | — | — | **PASS** | **PASS** | **PASS** |
| **check_loads**  | —     | —     | —     | **FAIL** | **PASS** | **PASS** |
| **create_loads** | —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **create_plant_loop** | — | — | — | **PASS** | **PASS** | **PASS** |
| **schedule_details** | — | —  | —     | **PASS** | **PASS** | **PASS** |
| **space_type_info** | — | —   | —     | **PASS** | **PASS** | **PASS** |
| **set_run_period** | — | —    | —     | **PASS** | **PASS** | **PASS** |
| **ideal_air**    | —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **save_model**   | —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **add_ev**       | —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **Total**        | **15/18** | **18/18** | **18/18** | **31/34** | **34/34** | **34/34** |

Progressive summary: L1=31/34 (91%), L2=34/34 (100%), L3=34/34 (100%)

## New Coverage: Discoverability Gap Cases

All 16 new progressive cases passed at L2+L3. 15/16 passed at L1.

| Category | Case | L1 | L2 | L3 | Notes |
|----------|------|----|----|-----|-------|
| Simulation | run_simulation | PASS | PASS | PASS | "Simulate the building" → run_simulation |
| Results | get_eui | PASS | PASS | PASS | "What's the building's energy use?" → extract_summary_metrics |
| Results | end_use_breakdown | PASS | PASS | PASS | "How much energy goes to heating vs cooling?" found |
| Results | hvac_sizing | PASS | PASS | PASS | "Are HVAC systems properly sized?" found |
| Envelope | set_wwr | PASS | PASS | PASS | "Add windows to the building" → set_window_to_wall_ratio |
| Envelope | replace_windows | PASS | PASS | PASS | "Upgrade windows to double-pane low-e" found |
| Envelope | construction_details | PASS | PASS | PASS | "What layers make up the exterior wall?" found |
| Loads | check_loads | FAIL | PASS | PASS | "What loads are assigned?" — L1 too vague |
| Loads | create_loads | PASS | PASS | PASS | "Add people and lighting" found |
| Plant loops | create_plant_loop | PASS | PASS | PASS | "Create a hot water heating loop" found |
| Schedules | schedule_details | PASS | PASS | PASS | "What hours is the HVAC running?" found |
| Space types | space_type_info | PASS | PASS | PASS | "What type of space is this?" found |
| Design | set_run_period | PASS | PASS | PASS | "Set simulation to run for a full year" found |
| Design | ideal_air | PASS | PASS | PASS | "Use ideal air loads for quick sizing" found |
| Misc | save_model | PASS | PASS | PASS | "Save my changes" → save_osm_model |
| Misc | add_ev | PASS | PASS | PASS | "Add electric vehicle charging" found |

### Workflow Cases (4 new, 3/4 passed)

| Case | Required Tools | Result | Notes |
|------|---------------|--------|-------|
| envelope_retrofit | load + set_wwr + replace_windows | PASS | |
| create_and_assign_loads | load + create_people + create_lights | PASS | |
| plant_loop_with_boiler | load + create_plant_loop + add_supply_equipment | PASS | |
| extract_results_chain | extract_summary_metrics + extract_end_use_breakdown | PASS | Uses saved run_id |

## Run 6 Failed Tests (6 failures)

### Known flaky L1 (3 failures)
- **import_floorplan_L1** — no file path in prompt, agent asks for one
- **list_dynamic_type_L1** — "What sizing parameters?" → used explicit tool instead of list_model_objects
- **check_loads_L1** — "What loads are assigned to the first space?" too vague

### Eval cases (2 failures)
- **energy-report** — multi-step chain, intermittent
- **retrofit** — multi-step comparison, intermittent

### Workflow (1 failure)
- **floorspacejs_to_typical** — multi-step chain got stuck after step 1. Known flaky.

## Running

```bash
# Full suite (~100 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v

# Quick smoke (~12 min, 12 tests)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m smoke -v

# Generic access only (~12 min, 10 tests)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m generic -v

# Progressive only (~60 min, 102 tests)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m progressive -v
```

Reports written to `LLM_TESTS_RUNS_DIR/benchmark.md` and `benchmark.json`.
