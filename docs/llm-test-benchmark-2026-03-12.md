# LLM Test Benchmark Report — 2026-03-12

## Run History

| Run | Tests | Passed | Rate  | Cost   | Changes |
|-----|-------|--------|-------|--------|---------|
| 1   | 50    | 22     | 44.0% | $9.31  | Baseline (no system prompt, wrong model path) |
| 2   | 90    | 75     | 83.3% | $11.55 | + system prompt, model path fix, pre-check |
| 3   | 90    | 82     | 91.1% | $11.39 | + test definition fixes, tool description improvements |
| 4   | 90    | 84     | 93.3% | $11.62 | No code changes (stability run) |
| **5** | **107** | **103** | **96.3%** | **$8.87** | **+ generic access tests, test cleanup** |

*Cost is notional API pricing reported by Claude Code CLI, not actual charges.
On Claude Max (subscription), these tests run at no additional cost.*

## Run 5 Changes

- **+27 new tests:** 3 generic access progressive (9 at L1/L2/L3), 5 migrated-from-test_02 progressive (15 at L1/L2/L3), 1 generic workflow, 1 generic guardrail, 1 setup (baseline+HVAC)
- **-10 removed tests:** with-model cases from test_02 (redundant with test_06 progressive L3)
- **Net: 90 → 107 tests**
- New markers: `smoke` (9), `generic` (10), `progressive` (54)
- New model: baseline+HVAC (System 7) for component inspection tests

### Per-Tier Comparison

| Tier        | Run 4 (90 tests) | Run 5 (107 tests) | Notes |
|-------------|-------------------|---------------------|-------|
| setup       | 3/3 100%          | 5/5 100%            | +2 (baseline_with_hvac, recount) |
| tier1       | 14/14 100%        | 4/4 100%            | 10 with-model cases moved to progressive |
| tier2       | 13/14 93%         | 14/15 93%           | +1 (inspect_and_modify_boiler) |
| tier3       | 26/27 96%         | 26/26 100%          | Eval cases unchanged |
| tier4       | 0/2 0%            | 3/3 100%            | +1 guardrail, fixed prior tier4 failures |
| progressive | 28/30 93%         | 51/54 94%           | +24 tests (8 new cases x 3 levels) |

### Progressive Prompt Comparison (Run 4 → Run 5)

| Case             | R4 L1 | R4 L2 | R4 L3 | R5 L1 | R5 L2 | R5 L3 |
|------------------|-------|-------|-------|-------|-------|-------|
| import_floorplan | FAIL  | PASS  | PASS  | FAIL  | PASS  | PASS  |
| add_hvac         | PASS  | PASS  | PASS  | FAIL  | PASS  | PASS  |
| view_model       | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| set_weather      | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| run_qaqc         | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| create_building  | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| add_pv           | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| thermostat       | FAIL  | PASS  | PASS  | PASS  | PASS  | PASS  |
| list_spaces      | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| schedules        | PASS  | PASS  | PASS  | PASS  | PASS  | PASS  |
| **inspect_component** | — | — | — | **PASS** | **PASS** | **PASS** |
| **modify_component**  | — | — | — | **PASS** | **PASS** | **PASS** |
| **list_dynamic_type** | — | — | — | **FAIL** | **PASS** | **PASS** |
| **floor_area**   | —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **materials**    | —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **thermal_zones**| —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **subsurfaces**  | —     | —     | —     | **PASS** | **PASS** | **PASS** |
| **surface_details** | — | —     | —     | **PASS** | **PASS** | **PASS** |
| **Total**        | **8/10** | **10/10** | **10/10** | **15/18** | **18/18** | **18/18** |

Progressive summary: L1=15/18 (83%), L2=18/18 (100%), L3=18/18 (100%)

## Generic Object Access Results

**Key finding: generic tools are highly discoverable.** The LLM finds and uses
`get_object_fields` and `set_object_property` even from vague L1 prompts.

### Progressive (3 cases, 9 tests — 8/9 passed)

| Case | L1 | L2 | L3 | Notes |
|------|----|----|-----|-------|
| inspect_component | PASS | PASS | PASS | Found `get_object_fields` from "What are the properties of the hot water boiler?" |
| modify_component | PASS | PASS | PASS | Found `set_object_property` from "Make the boiler more efficient." |
| list_dynamic_type | FAIL | PASS | PASS | L1 "What sizing parameters?" → used `get_sizing_system_properties` (explicit tool) instead of `list_model_objects` |

### Workflow (1 test — passed)

`inspect_and_modify_boiler`: list_model_objects → get_object_fields → set_object_property chain passed.

### Guardrail (1 test — passed)

`test_inspect_component_uses_mcp_not_script`: Agent used `get_object_fields`, did not write Python.

### Implications for Phase C (removing explicit tools)

- `get_object_fields` / `set_object_property` are discovered at L1 — agents don't need explicit tools like `get_component_properties` or `set_component_properties`
- `list_model_objects` is discovered at L2+ but NOT at L1 for obscure types (SizingSystem). At L1, agents prefer the explicit tool (`get_sizing_system_properties`)
- **Recommendation:** Phase C can proceed for component inspection/modification. For list operations on less common types, keep explicit tools or improve `list_model_objects` discoverability.

## Run 5 Failed Tests (4 failures)

### L1 structural (3 failures — expected)

- **import_floorplan_L1** — "Import a floor plan into a new model." No file path, agent searches instead.
- **add_hvac_L1** — "Add HVAC to the building." Agent gathered info but didn't add. Intermittent (passed Run 4).
- **list_dynamic_type_L1** — "What sizing parameters exist?" Agent used explicit `get_sizing_system_properties` x10 instead of `list_model_objects`. Valid behavior, just not the generic tool.

### Transient (1 failure)

- **floorspacejs_to_typical** — Multi-step chain got stuck in `list_files` loop after step 1. Known flaky.

## Token Usage Comparison

| Run | Tests | Input | Output | Cache | Cost |
|-----|-------|-------|--------|-------|------|
| 4   | 90    | —     | —      | —     | $11.62 |
| 5   | 107   | 1.0k  | 89.0k  | 9.5M  | $8.87 |

Run 5 is cheaper despite 17 more tests — cache hit rate is high (tool definitions cached across tests).

## Running

```bash
# Full suite (~85 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v

# Quick smoke (~10 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m smoke -v

# Generic access only (~12 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m generic -v

# Progressive only (~30 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m progressive -v
```

Reports written to `LLM_TESTS_RUNS_DIR/benchmark.md` and `benchmark.json`.
