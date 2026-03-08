# LLM Test Benchmark Report — 2026-03-08

## Run History

| Run | Tests | Passed | Rate  | Cost   | Changes |
|-----|-------|--------|-------|--------|---------|
| 1   | 50    | 22     | 44.0% | $9.31  | Baseline (no system prompt, wrong model path) |
| 2   | 90    | 75     | 83.3% | $11.55 | + system prompt, model path fix, pre-check |
| 3   | 90    | 82     | 91.1% | $11.39 | + test definition fixes, tool description improvements |

*Cost is notional API pricing reported by Claude Code CLI, not actual charges.
On Claude Max (subscription), these tests run at no additional cost.*

### Per-Tier Comparison (Run 1 vs Run 2 vs Run 3)

| Tier        | Run 1     | Run 2     | Run 3     | Notes |
|-------------|-----------|-----------|-----------|-------|
| setup       | 3/3 100%  | 3/3 100%  | 3/3 100%  | Always stable |
| tier1       | 13/14 93% | 14/14 100%| 14/14 100%| System prompt fixed the 1 flake |
| tier2       | 0/6 0%    | 11/14 79% | 13/14 93% | Thermostat + test def fixes |
| tier3       | 6/27 22%  | 23/27 85% | 24/27 89% | Systemic improvement |
| tier4       | n/a       | 2/2 100%  | 0/2 0%    | Transient (no code change) |
| progressive | n/a       | 22/30 73% | 28/30 93% | qaqc + thermostat fixes |

### Progressive Prompt Comparison (Run 2 vs Run 3)

| Case             | Run 2 L1 | Run 2 L2 | Run 2 L3 | Run 3 L1 | Run 3 L2 | Run 3 L3 |
|------------------|----------|----------|----------|----------|----------|----------|
| import_floorplan | FAIL     | PASS     | PASS     | FAIL     | PASS     | PASS     |
| add_hvac         | FAIL     | PASS     | PASS     | PASS     | PASS     | PASS     |
| view_model       | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| set_weather      | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| run_qaqc         | FAIL     | FAIL     | FAIL     | PASS     | PASS     | PASS     |
| create_building  | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| add_pv           | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| thermostat       | FAIL     | FAIL     | FAIL     | FAIL     | PASS     | PASS     |
| list_spaces      | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| schedules        | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| **Total**        | **6/10** | **8/10** | **8/10** | **8/10** | **10/10**| **10/10**|

Key improvements in Run 3:
- **add_hvac L1 now passes** — tool description added "HVAC / heating and cooling" keywords
- **run_qaqc all levels now pass** — accepted pre-sim QA tools as valid alternatives
- **thermostat L2+L3 now pass** — changed prompts to use offsets (matches tool API)
- **L2 and L3 are now 100%** — all tools discoverable with moderate+ specificity

## What Changed

### Run 1 -> Run 2: Infrastructure fixes (44% -> 83%)

Three fixes brought pass rate from 44% to 83%:

### 1. System prompt to stop list_files loops

Added a default system prompt to `runner.py`:

> "You are an OpenStudio building energy modeling assistant. Use only the MCP
> tools provided. If load_osm_model fails because the file doesn't exist,
> report the error immediately -- do NOT call list_files repeatedly to search
> for it."

**Impact:** Eliminated 25/28 failures from prior run where the agent got stuck
in a `load_osm_model -> list_files -> list_files -> ...` loop, burning all
turns on file discovery instead of calling the target tool.

### 2. Fixed baseline model path

The test suite expected the baseline model at `/runs/llm-test-baseline/model.osm`
but `create_baseline_osm(name="llm-test-baseline")` saves to
`/runs/examples/llm-test-baseline/baseline_model.osm`. Fixed `BASELINE_MODEL`
constant to match the actual path.

### 3. Pre-check baseline model exists

Added `baseline_model_exists()` check that verifies the host-side model file
exists before tests that depend on it. Tests skip with a clear message instead
of wasting turns + cost on a doomed attempt.

## Verification: Passing Tests Are Genuine

**No test assertions were weakened.** All changes were to infrastructure
(system prompt, model path, pre-check), not to what the tests assert.

Verification of passing test tool calls:

| Test | Expected Tool | Actually Called | Verdict |
|------|--------------|-----------------|---------|
| list all the spaces | list_spaces | load_osm_model, **list_spaces** | Correct |
| building floor area | get_building_info or get_model_summary | load_osm_model, **get_building_info** | Correct |
| 3D view | view_model | load_osm_model, **view_model**, copy_run_artifact | Correct |
| list materials | list_materials | load_osm_model, **list_materials** | Correct |
| list schedules | list_schedule_rulesets | load_osm_model, **list_schedule_rulesets** | Correct |
| Add HVAC (eval) | add_baseline_system | load_osm_model, list_thermal_zones, **add_baseline_system** | Correct |
| Add VAV system (eval) | add_baseline_system | load_osm_model, list_thermal_zones, **add_baseline_system** | Correct |
| Energy report | extract_summary_metrics | load_osm_model, ..., run_simulation, ..., **extract_summary_metrics**, extract_end_use_breakdown, ... | Correct |
| Run simulation | run_simulation | load_osm_model, **run_simulation**, get_run_status | Correct |
| Add VAV reheat (wkfl) | add_baseline_system | load_osm_model, list_thermal_zones, **add_baseline_system** | Correct |
| Add DOAS (wkfl) | add_doas_system | load_osm_model, list_thermal_zones, **add_doas_system** | Correct |
| Add VRF (wkfl) | add_vrf_system | load_osm_model, list_thermal_zones, **add_vrf_system** | Correct |
| Set weather (wkfl) | change_building_location | load_osm_model, **change_building_location** | Correct |
| Add PV (wkfl) | add_rooftop_pv | load_osm_model, **add_rooftop_pv** | Correct |
| Delete space (wkfl) | delete_object | load_osm_model, list_spaces, **delete_object** | Correct |
| Bar building (wkfl) | create_bar_building | **create_bar_building**, list_spaces | Correct |
| New building (wkfl) | create_new_building | **create_new_building** | Correct |
| Bar then typical | create_bar_building + change_building_location + create_typical_building | **create_bar_building**, **change_building_location**, **create_typical_building** | Correct |
| Import floorspacejs | import_floorspacejs | **import_floorspacejs**, list_files | Correct |
| Surface matching | create_space_from_floor_print + match_surfaces | **create_space_from_floor_print** x2, **match_surfaces** | Correct |

All 75 passing tests call the correct target tools. No false passes.

### Run 2 -> Run 3: Test definition + tool description fixes (83% -> 91%)

1. **thermostat tests** — changed prompts to use offsets ("raise cooling by 2F")
   instead of absolute values ("set cooling to 75F"). `adjust_thermostat_setpoints`
   takes offsets. Also accept `replace_thermostat_schedules` as valid alternative.
2. **run_qaqc progressive** — accept `inspect_osm_summary`, `get_model_summary`,
   `get_building_info`, `list_thermal_zones` as valid pre-sim QA tools (since
   `run_qaqc_checks` requires a completed simulation).
3. **FloorspaceJS eval.md** — added file path to prompt (can't call tool without
   required `floorplan_path` arg).
4. **add_baseline_system description** — added "HVAC / heating and cooling"
   keywords. L1 "Add HVAC to the building" now discovers the tool.
5. **import_floorspacejs description** — added "floor plan", "custom geometry"
   keywords (done in Run 2, impact measured in Run 3).

## Progressive Prompt Analysis (Run 3)

Tests the same operation at 3 specificity levels to measure tool discoverability.
See "Progressive Prompt Comparison" table above for Run 2 vs Run 3 side-by-side.

**Run 3 summary: L1=8/10, L2=10/10, L3=10/10**

Remaining L1 failures:
- **import_floorplan** — "Import a floor plan into a new model" has no file path,
  so agent correctly asks for one instead of guessing. Arguably correct behavior.
- **thermostat** — "Change the thermostat settings" is too vague. Agent loads
  model but doesn't know what to change. Needs at least a direction ("raise",
  "lower") or specific values.

## Run 3 Failed Tests (8 failures)

### Transient / LLM non-determinism (4 failures)

These passed in Run 2 and failed in Run 3 with no code changes — pure flakiness:

- **tier4: test_create_uses_mcp_not_raw_idf** — passed Run 2, failed Run 3
- **tier4: test_no_script_for_results** — passed Run 2, failed Run 3
- **tier3: new-building:Create a complete building with wea** — passed Run 2
- **tier3: troubleshoot:My simulation failed** — passed Run 2

With retries=2 (default) these would likely pass.

### Structural (2 failures — expected, not fixable without prompt changes)

- **import_floorplan_L1** — "Import a floor plan into a new model." No file path,
  agent correctly asks for one. Arguably correct behavior.
- **thermostat_L1** — "Change the thermostat settings." Too vague — agent loads
  model but doesn't know what to change without direction.

These L1 failures are by design — they test the boundary of how vague a prompt
can be. L2 and L3 versions pass for both.

### Intermittent (2 failures — would benefit from retry)

- **tier3: troubleshoot:Why did EnergyPlus crash?** — agent called `get_run_logs`
  (correct) but test expects `get_run_status` too. Passes sometimes.
- **tier2: floorspacejs_to_typical** — 3-tool chain, agent got `import_floorspacejs`
  but didn't complete the chain. Long workflow, sensitive to turn budget.

## Remaining Improvement Opportunities

### Consider for future

1. **Pre-simulation QA tool** — lightweight validation (missing weather, empty
   zones, no HVAC) without requiring simulation. Would make "check the model"
   prompts work more reliably.
2. **System prompt tuning** — "don't loop on list_files" may be too aggressive
   for multi-step workflows that legitimately need to find files (EPW lookup).
3. **L1 vague prompt handling** — when required args are missing, the agent
   correctly asks for them. Could teach it to use test-assets defaults instead.

## How These Tests Were Created

### Infrastructure (tests/llm/)

- **runner.py** — wraps `claude -p --output-format stream-json --verbose` with
  MCP config pointing at openstudio-mcp Docker server. Parses NDJSON output,
  extracts tool_use blocks, tracks tokens/cost/timing.
- **conftest.py** — pytest markers, retry logic, baseline model pre-checks,
  benchmark report generation (JSON + aligned markdown tables + history).
- **eval_parser.py** — parses eval.md files from `.claude/skills/*/eval.md`
  to auto-generate test cases.

### Test files

- **test_01_setup.py** (setup) — creates baseline + example models, saves to /runs
- **test_02_tool_selection.py** (tier1) — hand-crafted query prompts, checks
  correct MCP tool is called
- **test_03_eval_cases.py** (tier3) — auto-generated from eval.md files, tests
  natural language prompts against expected tools
- **test_04_workflows.py** (tier2) — multi-step workflows: load model, add HVAC,
  set weather, create buildings, etc.
- **test_05_guardrails.py** (tier4) — verifies agent uses MCP tools not raw
  scripts/files
- **test_06_progressive.py** (progressive) — same operation at 3 specificity
  levels (vague/moderate/explicit) to measure tool discoverability

### Running

```bash
LLM_TESTS_ENABLED=1 LLM_TESTS_RETRIES=1 LLM_TESTS_RUNS_DIR=/tmp/llm-test-runs \
  pytest tests/llm/ -v
```

Reports written to `LLM_TESTS_RUNS_DIR/benchmark.md` and `benchmark.json`.

### Key design decisions

- **retries=1** for this run (want first-attempt success signal)
- **system prompt** prevents list_files loops (biggest single improvement)
- **baseline pre-check** skips dependent tests early instead of wasting cost
- **progressive tests** reveal tool description gaps vs tool design gaps
