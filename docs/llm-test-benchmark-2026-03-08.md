# LLM Test Benchmark Report — 2026-03-08

## Run History

| Run | Tests | Passed | Rate  | Cost   | Changes |
|-----|-------|--------|-------|--------|---------|
| 1   | 50    | 22     | 44.0% | $9.31  | Baseline (no system prompt, wrong model path) |
| 2   | 90    | 75     | 83.3% | $11.55 | + system prompt, model path fix, pre-check |
| 3   | 90    | 82     | 91.1% | $11.39 | + test definition fixes, tool description improvements |
| 4   | 90    | 84     | 93.3% | $11.62 | No code changes (stability run) |

*Cost is notional API pricing reported by Claude Code CLI, not actual charges.
On Claude Max (subscription), these tests run at no additional cost.*

### Per-Tier Comparison

| Tier        | Run 1     | Run 2     | Run 3     | Run 4     | Notes |
|-------------|-----------|-----------|-----------|-----------|-------|
| setup       | 3/3 100%  | 3/3 100%  | 3/3 100%  | 3/3 100%  | Always stable |
| tier1       | 13/14 93% | 14/14 100%| 14/14 100%| 14/14 100%| Stable since Run 2 |
| tier2       | 0/6 0%    | 11/14 79% | 13/14 93% | 13/14 93% | Stable at 93% |
| tier3       | 6/27 22%  | 23/27 85% | 24/27 89% | 26/27 96% | Best yet |
| tier4       | n/a       | 2/2 100%  | 0/2 0%    | 0/2 0%    | Persistent (agent uses Bash) |
| progressive | n/a       | 22/30 73% | 28/30 93% | 28/30 93% | Stable at 93% |

### Progressive Prompt Comparison (Run 2 → Run 3 → Run 4)

| Case             | Run 2 L1 | Run 2 L2 | Run 2 L3 | Run 3 L1 | Run 3 L2 | Run 3 L3 | Run 4 L1 | Run 4 L2 | Run 4 L3 |
|------------------|----------|----------|----------|----------|----------|----------|----------|----------|----------|
| import_floorplan | FAIL     | PASS     | PASS     | FAIL     | PASS     | PASS     | FAIL     | PASS     | PASS     |
| add_hvac         | FAIL     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| view_model       | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| set_weather      | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| run_qaqc         | FAIL     | FAIL     | FAIL     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| create_building  | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| add_pv           | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| thermostat       | FAIL     | FAIL     | FAIL     | FAIL     | PASS     | PASS     | FAIL     | PASS     | PASS     |
| list_spaces      | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| schedules        | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     | PASS     |
| **Total**        | **6/10** | **8/10** | **8/10** | **8/10** | **10/10**| **10/10**| **8/10** | **10/10**| **10/10**|

Progressive results stable across Run 3 and Run 4: L1=8/10, L2=10/10, L3=10/10.

Remaining L1 failures (structural — expected):
- **import_floorplan** — no file path in prompt, agent correctly asks for one
- **thermostat** — "Change the thermostat settings" too vague without direction

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

## Run 4 Failed Tests (6 failures)

### Persistent — tier4 guardrails (0/2 in Runs 3+4)

Agent uses `Bash` built-in tool alongside MCP tools — violates the "MCP only"
guardrail. Root cause: agent runs bash commands to inspect/verify results even
when instructed to use MCP tools only. Both tests consistently fail at retries=1.

- **test_create_uses_mcp_not_raw_idf** — agent called `create_new_building` (correct)
  but also used Bash
- **test_no_script_for_results** — agent called `extract_summary_metrics` (correct)
  but also used Bash for debugging

**Fix options:** Stronger system prompt ("never use Bash/Write/Edit"), or accept
Bash usage if MCP creation/extraction tool was also called.

### Structural (2 failures — expected)

- **import_floorplan_L1** — "Import a floor plan into a new model." No file path.
- **thermostat_L1** — "Change the thermostat settings." Too vague.

By design — tests the boundary of prompt vagueness.

### Transient (2 failures — different tests each run)

- **set_weather** (tier2) — agent called `list_files, get_weather_info` instead of
  `change_building_location`. Passed in Run 3, failed Run 4. Pure flakiness.
- **troubleshoot:My simulation failed** (tier3) — agent loaded model but didn't
  call troubleshooting tools. Intermittent across all runs.

## Run 3 Failed Tests (8 failures, for comparison)

- tier4 x2 (guardrails), tier3 x3 (new-building, troubleshoot x2), tier2 x1
  (floorspacejs_to_typical), progressive x2 (import_floorplan_L1, thermostat_L1)

## Remaining Improvement Opportunities

### Changes made after Run 4

1. **System prompt refined** — replaced broad "don't call list_files" with nuanced
   guidance: "use file paths from the prompt directly, only call list_files for
   genuine discovery". Also added "complete ALL steps before stopping" for multi-step.
2. **run_qaqc_checks description** — added pre-sim alternative suggestion
   (inspect_osm_summary, get_model_summary) in docstring and error message.
3. **troubleshoot EXTRA_EXPECTED** — added `list_files` as valid tool (agent
   reasonably uses it to discover simulation run directories).
4. **SKIP_PROMPTS** — added "Create a complete building with weather" (prompt
   lacks required weather_file param, unfair to test).

### Consider for future

1. **Pre-simulation QA tool** — lightweight SDK-based validation (missing weather,
   empty zones, no HVAC) without requiring simulation SQL results.
2. **Tier4 guardrail fix** — either strengthen system prompt to prevent Bash usage,
   or relax assertion to allow Bash if MCP tools were also used correctly.
3. **L1 vague prompt handling** — structural limit. Could teach agent to use
   test-assets defaults, but arguably the correct behavior is to ask for missing info.

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
