---
description: Test quality rules — loaded when writing or reviewing tests
globs:
  - tests/**
  - tests/llm/**
---

# Test Quality Rules

## What matters in this repo

MCP server giving AI agents control of building energy modeling via 150+ tools. Tests must protect:

1. **Simulation correctness** — EUI within tolerance, simulation completes, results extractable
2. **HVAC wiring integrity** — right components on right loops, correct node connections
3. **Model mutation correctness** — tools create/modify OpenStudio objects with correct properties
4. **MCP contract fidelity** — ok/error response shape, pagination, response sizes
5. **Error handling & security** — graceful failures, path traversal prevention, no-model-loaded guards
6. **LLM tool discovery** — Claude selects the right tool from 150+ options

## Test justification comment (mandatory)

Every test function must have a `# Regression:` or `# Validates:` comment. One line, states what breaks if this test is deleted. If you can't write this comment, the test probably shouldn't exist.

- `# Regression:` — test was written because something broke (bug fix, incident)
- `# Validates:` — test protects an invariant or contract proactively

```python
def test_system7_serves_all_zones():
    # Validates: System 7 VAV must serve all 10 baseline zones with chiller+boiler plant loops
    ...

def test_json_string_zone_names():
    # Regression: MCP clients sent zone names as JSON string, caused TypeError in add_air_loop
    ...
```

Bad examples (rewrite these):
- `# Validates: the function works`
- `# Regression: it was broken`
- `# Validates: returns correct result`

## Three test tiers

| Tier | Marker | Runner | Mocking |
|------|--------|--------|---------|
| Unit | `@pytest.mark.unit` | `pytest -m "not integration"` (what CI runs, in Docker; works locally without Docker too) | model_manager, filesystem only |
| Integration | `@pytest.mark.integration` | Docker + `RUN_OPENSTUDIO_INTEGRATION=1` | **Nothing** |
| LLM Agent | `@pytest.mark.llm` | `LLM_TESTS_ENABLED=1` + Claude CLI | **Nothing** |

Don't put tests in the wrong tier:
- If it needs `openstudio` import or real MCP server, it's **integration**
- If it mocks anything, it's **unit**
- If it tests Claude's tool selection, it's **LLM**

### What to mock

- **Mock:** `model_manager` state, filesystem paths, `RUN_ROOT` — only in unit tests
- **Never mock:** the function under test, OpenStudio SDK bindings, MCP tool dispatch, math/physics

Mocking the thing under test makes the test unfalsifiable.

## Assertion quality

**Exact values or `pytest.approx`** — never just existence:
```python
# Bad
assert "name" in air_loop                    # proves key exists, not value
assert isinstance(result, dict)              # redundant after unwrap()
assert result.get("osm_path") is not None    # check the actual value

# Good
assert loop["num_thermal_zones"] == 10
assert result["eui_MJ_m2"] == pytest.approx(1875.076, rel=0.02)
assert result["osm_path"].endswith(".osm")
```

**Error paths** — assert both status AND message:
```python
assert result["ok"] is False
assert "not found" in result["error"].lower()
```

**Domain context in assertion messages:**
```python
# Bad
assert count >= 2, f"Expected >= 2, got {count}"
# Good
assert count >= 2, f"System 7 needs HW + CHW loops, got {count}"
```

**`pytest.approx()`** for all float comparisons — never bare `==` on floats. Specify `rel=` or `abs=` explicitly.

**`pytest.mark.parametrize`** when testing the same logic across >2 inputs.

**No `isinstance(result, dict)` after `unwrap()`** — `unwrap()` already guarantees a dict.

## Anti-patterns (delete or rewrite)

1. **Existence-only checks** — `assert "name" in result` without checking the value
2. **Conditional test bodies that silently pass** — `if data: assert ...` `else: print("OK")`
3. **`print()` as only verification** — always pair with an assertion
4. **Tautological assertions** — asserting the tool echoes back your input, not computed values
5. **Deleting failing tests** — the implementation is the suspect, not the test
6. **Mocking the thing under test** — calling a mock proves nothing
7. **`assert x is not None`** without subsequent value check
8. **`try/except` around assertions** — pytest handles exceptions; wrapping silences failures
9. **Weakening assertions to pass** — changing `== 10` to `>= 1` masks real bugs

## Test priority (highest first)

When deciding what to test, prioritize by user impact:

1. **Would a user get wrong energy numbers?** — EUI, annual consumption, peak demand
2. **Would HVAC be miswired?** — wrong components on loops, missing connections, simulation failure
3. **Would a model object have wrong properties?** — capacity, efficiency, schedule assignment
4. **Would the MCP contract break?** — ok/error shape, missing fields, pagination
5. **Would an error be confusing or dangerous?** — path traversal, no-model guard, cryptic messages
6. **Would Claude pick the wrong tool?** — description ambiguity, tool discovery regression

## Arrange-Act-Assert structure

Every test follows explicit AAA:

```python
@pytest.mark.integration
def test_system7_creates_vav_with_reheat():
    # Validates: System 7 VAV serves all zones with reheat terminals
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # --- Arrange ---
                zones = await create_and_load(session, _unique("test_sys7"))

                # --- Act ---
                result = unwrap(await session.call_tool("add_baseline_system", {
                    "system_type": 7, "thermal_zone_names": zones,
                }))

                # --- Assert ---
                assert result["ok"] is True, f"add_baseline_system failed: {result.get('error')}"
                loops = unwrap(await session.call_tool("list_air_loops", {}))
                assert loops["air_loops"][0]["num_thermal_zones"] == 10

    asyncio.run(_run())
```

## AI-specific guard rules

1. **Never delete a failing test without user approval.** Investigate the implementation first.
2. **Never weaken an assertion to make a test pass.** If `== 10` fails, the code is wrong, not the test.
3. **Don't duplicate implementation logic in assertions.** Use known reference values, not re-derived ones.
4. **Every test must be falsifiable.** If no bug could make it fail, it's useless.
5. **No `try/except` around assertions.** Pytest handles exceptions.
6. **Fix hook/lint failures with a new commit.** Don't amend (may destroy unrelated changes).

## Linting

- Run `ruff check tests/` before committing test code
- `pytest --co -q` to verify test discovery without running
- No additional ruff config needed — project-level config applies

## Review checklist

Apply before committing test code:

```
[ ] Has `# Regression:` or `# Validates:` comment?
[ ] Would fail if the implementation had the stated bug?
[ ] Assertions check actual values, not just types or existence?
[ ] Floating-point comparisons use pytest.approx(val, rel=...)?
[ ] Error paths assert both ok is False AND error message content?
[ ] Integration tests mock nothing?
[ ] Unit tests don't import openstudio?
[ ] No isinstance(result, dict) after unwrap()?
[ ] No conditional test bodies that silently pass?
[ ] Test added to correct CI shard in .github/workflows/ci.yml?
[ ] pytest.parametrize used for >2 similar cases?
[ ] Domain context in assertion messages?
[ ] Unique model names use _unique_name() pattern?
[ ] /codex-review run on test PRs (separate reviewer catches tautological alignment)?
```
