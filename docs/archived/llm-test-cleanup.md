# Plan: LLM Test Suite Cleanup + Generic Object Access Coverage

## Status: COMPLETE

## Context
Phase A+B of generic object access is done (get_object_fields, set_object_property, enhanced list_model_objects). Phase C tool removal now complete (6 tools removed in generic-object-access.md).

Current LLM tests have **zero coverage** of generic access tools. Additionally, the test suite (90 tests across 6 files) has grown organically and needs cleanup: redundant cases, inconsistent grouping, no easy way to run "just the new stuff."

## Current State

### Test files (6)
| File | Tests | Tier | What |
|------|-------|------|------|
| test_01_setup | 4 | tier1 | create/load models, run simulation |
| test_02_tool_selection | 14 | tier1 | single-tool discovery (10 with-model, 4 no-model) |
| test_03_eval_cases | ~50 | tier1 | auto-generated from 8 eval.md files |
| test_04_workflows | 14 | tier2 | multi-step tool chaining |
| test_05_guardrails | 2 | tier4 | MCP-not-scripts checks |
| test_06_progressive | 30 | tier1 | L1/L2/L3 discovery (10 cases x 3 levels) |

### Problems
1. **No generic access tests** — can't validate Phase C
2. **Tier numbering is confusing** — test_03 (eval_cases) is tier1, test_04 is tier2, test_06 is tier1 again
3. **Overlap** — test_02 and test_06 both test tool selection (test_02 is a subset of test_06's L3 level)
4. **test_03 eval_cases are fragile** — depend on eval.md files that may drift; many get extra_expected padding
5. **No "quick smoke" option** — running tier1 alone is 44+ tests (~50 min)
6. **Marker mismatch** — benchmark report maps file→tier, but test_06 is marked tier1 despite being progressive

## Plan

### 1. Add generic access tests to test_06_progressive.py

Add 3 new progressive cases (9 tests: 3 levels each):

```python
{
    "id": "inspect_component",
    "needs_model": True,  # needs baseline+HVAC
    "needs_hvac": True,
    "expected": ["get_object_fields", "get_component_properties"],
    "L1": "What are the properties of the hot water boiler?",
    "L2": "Show me all properties of the BoilerHotWater in the model.",
    "L3": "Use get_object_fields to read properties of the BoilerHotWater.",
},
{
    "id": "modify_component",
    "needs_model": True,
    "needs_hvac": True,
    "expected": ["set_object_property", "set_component_properties"],
    "L1": "Make the boiler more efficient.",
    "L2": "Set the boiler's nominal thermal efficiency to 0.92.",
    "L3": "Use set_object_property to set nominalThermalEfficiency to 0.92 on the BoilerHotWater.",
},
{
    "id": "list_dynamic_type",
    "needs_model": True,
    "needs_hvac": True,
    "expected": ["list_model_objects"],
    "L1": "What sizing parameters exist in the model?",
    "L2": "List all SizingSystem objects in the model.",
    "L3": "Use list_model_objects with object_type SizingSystem to list sizing objects.",
},
```

**Problem:** These need a baseline model WITH HVAC (System 7), but the current baseline from test_01_setup has no HVAC. Two options:
- A) Add a second setup step that creates baseline+HVAC
- B) Have the prompt itself add HVAC first (wastes turns)

**Decision:** Option A — add `test_create_baseline_with_hvac` to test_01_setup that creates a second model at `/runs/examples/llm-test-baseline-hvac/baseline_model.osm`. Cases with `needs_hvac=True` use this path.

### 2. Add generic access workflow to test_04_workflows.py

One new multi-step workflow:

```python
{
    "id": "inspect_and_modify_boiler",
    "prompt": LOAD_HVAC + (
        "List the BoilerHotWater objects using list_model_objects. "
        "Then read the properties of the first boiler using get_object_fields. "
        "Then set its nominalThermalEfficiency to 0.95 using set_object_property. "
        "Use MCP tools only."
    ),
    "required_tools": ["load_osm_model", "list_model_objects",
                        "get_object_fields", "set_object_property"],
    "timeout": 120,
},
```

### 3. Add guardrail test to test_05_guardrails.py

```python
def test_inspect_component_uses_mcp_not_script():
    """Agent must use get_object_fields, not write Python to parse the model."""
    # Prompt: "What are the cooling coil properties?"
    # Assert: get_object_fields or get_component_properties called
    # Assert: no "import openstudio" in response text
```

### 4. Remove redundant tests from test_02_tool_selection.py

test_02's 10 with-model cases are all covered by test_06_progressive L3:
| test_02 case | test_06 equivalent |
|---|---|
| "list all the spaces" | list_spaces_L3 |
| "tell me the building floor area" | (unique — keep or add to progressive) |
| "show me a 3D view" | view_model_L3 |
| "list HVAC baseline systems" | (unique — keep or add to progressive) |
| "list the materials" | (unique) |
| "list the thermal zones" | (unique) |
| "list the schedules" | schedules_L3 |
| "check model using run_qaqc_checks" | run_qaqc_L3 |
| "list subsurfaces" | (unique) |
| "show surface details" | (unique) |

**Decision:** Merge the 5 unique test_02 cases into test_06 as new progressive cases, then delete test_02 entirely. This eliminates 14 tests of overlap and adds 15 (5 cases x 3 levels) progressive tests that are strictly more informative.

New progressive cases to add:
- `floor_area`: L1 "How big is the building?" / L3 "get_building_info"
- `materials`: L1 "What materials are used?" / L3 "list_materials"
- `thermal_zones`: L1 "How many zones?" / L3 "list_thermal_zones" (already exists as part of list_spaces? No — different tool)
- `subsurfaces`: L1 "What windows does it have?" / L3 "list_subsurfaces"
- `surface_details`: L1 "Tell me about the south wall" / L3 "get_surface_details"

Also keep test_02's 4 no-model cases — move them to test_06 as non-progressive single-level tests, or keep test_02 with only the 4 no-model cases.

**Decision:** Keep test_02 with ONLY the 4 no-model cases (server_status, list_skills, create_new_building, create_bar_building). Rename to make its scope clear.

### 5. Consolidate test_03_eval_cases

test_03 auto-generates ~50 cases from eval.md. Many overlap with test_06 progressive and test_04 workflows. The EXTRA_EXPECTED dict is a smell — it papers over eval.md prompts that are too vague.

**Decision:** Keep test_03 as-is for now. It's auto-generated and low-maintenance. Removing it would require auditing all 8 eval.md files. Flag for future cleanup.

### 6. Fix tier markers + add markers for easy filtering

Current markers: `tier1`, `tier2`, `tier4`, `stable`, `flaky`

**Add:**
- `progressive` marker on test_06 (already tagged tier1 — separate it)
- `generic` marker on all new generic access tests
- `smoke` marker on a fast subset (~10 tests, <10 min)

**Smoke subset:** test_01 setup (2 create tests) + 5 progressive L3 tests (most reliable) + 1 workflow + 1 guardrail = ~9 tests.

**New run commands:**
```bash
# Quick smoke (new tools + basics, ~10 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m smoke -v

# Generic access only (~5 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m generic -v

# Progressive only (~30 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m progressive -v

# Full suite (~75 min, unchanged)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v
```

### 7. Setup: baseline model with HVAC

In `test_01_setup.py`, add:

```python
BASELINE_HVAC_MODEL = "/runs/examples/llm-test-baseline-hvac/baseline_model.osm"

def test_create_baseline_with_hvac():
    """Create baseline + System 7 HVAC for component inspection tests."""
    result = run_claude(
        "Create a baseline building named 'llm-test-baseline-hvac' using "
        "create_baseline_osm with ashrae_sys_num '07'. Use MCP tools only.",
        timeout=120,
    )
    assert "create_baseline_osm" in result.tool_names
    assert not result.is_error
```

Add `BASELINE_HVAC_MODEL` to conftest.py, with `baseline_hvac_model_exists()` check.

## Summary of Changes

| File | Action |
|------|--------|
| `tests/llm/conftest.py` | Add BASELINE_HVAC_MODEL, markers (progressive, generic, smoke), baseline_hvac_model_exists() |
| `tests/llm/test_01_setup.py` | Add test_create_baseline_with_hvac |
| `tests/llm/test_02_tool_selection.py` | Remove 10 with-model cases, keep 4 no-model cases |
| `tests/llm/test_04_workflows.py` | Add inspect_and_modify_boiler workflow |
| `tests/llm/test_05_guardrails.py` | Add test_inspect_component_uses_mcp_not_script |
| `tests/llm/test_06_progressive.py` | Add 8 new cases (3 generic + 5 from test_02), handle needs_hvac |

### Net test count
- Remove: 10 (test_02 with-model cases)
- Add: 9 (3 generic progressive) + 15 (5 moved-from-test_02 progressive) + 1 (workflow) + 1 (guardrail) + 1 (setup) = 27
- **Run 5 total: 107 tests** (was 90)
- **Run 6 total: 159 tests** (+16 progressive cases x3 levels + 4 workflows + 1 sim setup)

### New markers summary
```
pytest -m smoke        # 12 tests, fast validation
pytest -m generic      # 10 tests, generic access tools only
pytest -m progressive  # 102 tests, all L1/L2/L3 (34 cases)
pytest -m stable       # ~145 tests, reliable
pytest -m flaky        # ~14 tests, intermittent
```

## Verification
1. `LLM_TESTS_ENABLED=1 pytest tests/llm/ -m generic -v` — all generic tests pass
2. `LLM_TESTS_ENABLED=1 pytest tests/llm/ -m smoke -v` — quick smoke passes
3. `LLM_TESTS_ENABLED=1 pytest tests/llm/ -v` — full suite maintains ~95%+ pass rate
4. Benchmark report shows progressive analysis for new cases

## Decisions
- test_03 eval_cases cleanup — deferred to separate PR
- smoke marker: no simulation test (keep it fast, ~10 min)
