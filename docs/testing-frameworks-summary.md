# Testing Frameworks Summary

## Overview

~750+ tests across 71 files, split into three tiers:

| Category | Tests | Files | Requires Docker |
|----------|-------|-------|-----------------|
| Integration | ~326 | 63 | Yes |
| LLM agent | ~200 | 8 | Yes + Claude CLI |
| Unit | ~200 | ~10 | No |

CI runs 5 parallel shards (~200s each, ~6 min wall time). LLM tests run locally only.

---

## 1. Integration Tests

### Methodology

Each test spawns an MCP server via `stdio_client`, creates a temporary model with a UUID-based unique name, exercises one or more MCP tools, and asserts on the `{"ok": True/False, ...}` response dict. Tests run inside Docker containers with the full OpenStudio SDK + ComStock measures installed.

```
pytest → stdio_client(server_params()) → MCP server subprocess
  → session.call_tool("tool_name", {args})
  → unwrap(result) → assert result["ok"] is True
```

Key fixtures in `tests/conftest.py`: `create_and_load()`, `create_baseline_and_load()`, `unwrap()`, `poll_until_done()`.

### Categories

Integration tests are organized by domain, mapped to CI shards for parallel execution:

| Category | What it tests | Example files | CI Shard |
|----------|--------------|---------------|----------|
| **Simulation** | Full create→weather→HVAC→simulate→extract pipelines | `test_mcp_seb4`, `test_example_workflows` | 1 |
| **HVAC** | Baseline systems 1-10, DOAS, VRF, radiant, air loops, supply wiring | `test_hvac_systems`, `test_doas_system`, `test_vrf_system`, `test_hvac_supply_wiring` | 2, 3, 4, 5 |
| **Geometry** | Bar building, space creation, floor plans, surface matching | `test_geometry`, `test_bar_building`, `test_create_space` | 2, 4, 5 |
| **Envelope** | Materials, constructions, subsurfaces, WWR | `test_constructions`, `test_create_constructions` | 1, 4 |
| **Loads & Schedules** | Load definitions, schedules, infiltration, thermostats | `test_loads`, `test_schedules`, `test_create_loads` | 3, 4 |
| **Component access** | Get/set properties, setpoint managers, sizing, generic inspect/modify | `test_component_properties`, `test_component_controls`, `test_generic_access` | 1, 3 |
| **Measures** | Apply bundled measures, author custom measures, ComStock integration | `test_measures`, `test_measure_authoring`, `test_comstock` | 1, 3 |
| **Results** | Summary metrics, hourly extraction, error parsing, output variables | `test_results_extraction`, `test_add_output_variable` | 4 |
| **Model lifecycle** | Load/save, object management, validation, model summary | `test_load_save_model`, `test_object_management`, `test_validate_model` | 3, 4 |
| **Infrastructure** | SWIG cleanup, stdout suppression, JSON-RPC protocol, response sizes | `test_swig_memleak_cleanup`, `test_stdio_smoke`, `test_response_sizes` | 4 |
| **Skills** | Skill registration, SKILL.md validation, QA/QC, energy reports, retrofit | `test_skill_registration`, `test_skill_qaqc`, `test_skill_retrofit` | 1, 2, 3 |

No formal tier markers — all integration tests share the `@pytest.mark.integration` marker. The category split is implicit in file naming and CI shard assignment.

### Strengths

- **High fidelity**: tests hit the real OpenStudio SDK, no mocks. Catches SWIG binding issues, model state bugs, and measure failures that unit tests would miss.
- **Good coverage breadth**: 63 files cover all 138 registered tools — geometry, HVAC, loads, schedules, constructions, measures, results extraction, component properties, and full simulation workflows.
- **Parallelized CI**: 5 shards keep wall time under 6 min despite 326 tests.
- **Unique naming**: UUID + xdist worker ID prevents model collisions if tests ever run in parallel.
- **Response contract testing**: `test_contract.py` validates JSON schema of tool responses; `test_response_sizes.py` checks payload limits.

### Weaknesses

- **No code coverage tracking**: no `.coveragerc`, no coverage reports. Unknown which code paths are exercised vs dead.
- **Heavy Docker dependency**: can't run integration tests without building the full image (~2 GB). Slows feedback loop for contributors.
- **Sequential within each test**: most tests create a fresh model, load it, do work, assert — no shared fixtures across tests in the same file. Lots of redundant model creation.
- **Limited negative testing**: most tests verify the happy path (`ok: True`). Few tests assert specific error messages, edge cases, or malformed input handling.
- **Shard balancing is manual**: test files are hand-assigned to shards in `ci.yml`. No automation to detect imbalance.
- **No parametric stress testing**: e.g., no tests creating 100-zone models, applying 20 measures in sequence, or hitting concurrency limits.

---

## 2. LLM Agent Tests

### Methodology

Tests invoke `claude -p` CLI with a natural-language prompt, pointed at the MCP server via a generated config. The NDJSON stream is parsed to extract tool calls, token usage, and final text. Assertions check that the agent selected the correct tool(s).

```
run_claude(prompt, timeout=300)
  → claude -p "prompt" --output-format stream-json --verbose --mcp-config mcp.json
  → parse NDJSON → ClaudeResult(tool_calls, tool_names, final_text, cost_usd)
  → assert expected_tool in result.tool_names
```

Custom retry logic via `pytest_runtest_protocol()` retries flaky LLM tests up to N times (default 2), with prompt budget tracking (max 180 invocations per session).

### Tiers

| Tier | File | Tests | Purpose | Avg Duration |
|------|------|-------|---------|-------------|
| **Setup** | `test_01_setup.py` | 5 | Create baseline, HVAC, and example models. All downstream tests depend on these. | ~1 min |
| **Tier 1** | `test_02_tool_selection.py` | ~14 | Single-tool discovery — given a question, does the agent pick the right tool? No model state needed. | ~20s/test |
| **Tier 2** | `test_04_workflows.py` | ~26 | Multi-step workflows (3-4 tool chains). Verifies the agent can sequence create→configure→simulate→extract. | ~45s/test |
| **Tier 3** | `test_03_eval_cases.py` | ~27 | Auto-parsed from skill `eval.md` "Should trigger" tables. Tests with model state (needs baseline loaded). | ~30s/test |
| **Tier 4** | `test_05_guardrails.py` | 3 | Safety: agent must NOT use Bash/Edit/Write to bypass MCP tools. Regression gate for tool bypass bugs. | ~30s/test |
| **Progressive** | `test_06_progressive.py` | 102 | 34 operations × 3 specificity levels. The core diagnostic for tool description quality. | ~35s/test |
| **E2E** | `test_07_fourpipe_e2e.py` | 1 | Full retrofit on a 44-zone model with natural-language prompt. Realistic complexity test. | ~5 min |
| **Measure** | `test_08_measure_authoring.py` | ~8 | Custom measure creation, editing, testing, export. Domain-specific authoring workflows. | ~40s/test |

**Pytest markers** for selective execution: `smoke` (12), `stable` (~140), `flaky` (~18), `progressive` (102), `generic` (~10), `tier1`-`tier4`.

### Progressive Testing (L1/L2/L3)

The standout methodology. Each of 34 operations is tested at three prompt specificity levels:

| Level | Description | Example prompt | Latest pass rate |
|-------|-------------|---------------|-----------------|
| **L1 (vague)** | Minimal keywords, no tool names, missing context | "Add HVAC to the building" | 90% (38/42) |
| **L2 (moderate)** | Domain context + values, still no tool names | "Add a VAV reheat system to all 10 zones" | 95% (40/42) |
| **L3 (explicit)** | Tool name included in prompt | "Use add_baseline_system to add System 7" | 100% (42/42) |

The L1→L2→L3 gradient directly measures tool description quality. When L1 fails but L3 passes, the fix is in the tool's docstring or keywords — not the tool's code. This has driven multiple targeted docstring improvements (e.g., adding "HVAC / heating and cooling" keywords to `add_baseline_system` fixed L1 discovery immediately).

### Metrics Collected

Every `run_claude()` invocation produces a `ClaudeResult` with these metrics, aggregated into benchmark reports:

**Per-test metrics** (written to `benchmark.json`):

| Metric | Source | What it measures |
|--------|--------|-----------------|
| `passed` | pytest outcome | Binary pass/fail after retries |
| `attempt` | retry hook | Which attempt succeeded (1 = first try, 2+ = flaky) |
| `duration_s` | wall clock | Total time including Docker startup + LLM inference |
| `num_turns` | Claude CLI result | Conversation turns (tool call + response = 1 turn). High turn count signals looping. |
| `num_tool_calls` | NDJSON parsing | Total MCP tools invoked. Expected: 1-3 for single-tool, 3-8 for workflows. |
| `tool_calls` | NDJSON parsing | Ordered list of MCP tool names called. Primary assertion target. |
| `input_tokens` | Claude CLI usage | Tokens sent to model (system prompt + tool descriptions + conversation) |
| `output_tokens` | Claude CLI usage | Tokens generated by model |
| `cache_read_tokens` | Claude CLI usage | Tokens served from prompt cache (high = good, means tool descriptions cached) |
| `cost_usd` | Claude CLI result | Notional API cost (free on Claude Max, tracked for comparison only) |

**Aggregated metrics** (written to `benchmark.md`):

| Metric | Granularity | Purpose |
|--------|-------------|---------|
| Pass rate by tier | per-tier | Are specific tiers degrading? |
| Pass rate by level (L1/L2/L3) | per-progressive-case | Which tools have weak descriptions? |
| Token profile by tier | per-tier avg | Detect prompt bloat or regression |
| Failed test detail | per-test | Tool sequence + turn count for debugging |
| Run history | per-run (last 50) | Track pass rate trends across code changes |

**What's NOT measured** (gaps):

| Missing metric | Why it matters |
|----------------|---------------|
| Parameter correctness | A test passes if the right tool is called, even with wrong args |
| First-attempt pass rate | Retries mask flakiness — only `attempt` field captures this |
| Time-to-first-tool | Slow tool discovery (many ToolSearch calls) isn't penalized |
| Cross-model comparison | All runs use one model (sonnet) — no data on model-agnostic tool quality |
| Error recovery rate | When a tool returns `ok: False`, does the agent retry or give up? |

### Benchmark Reports

Written at session end to `LLM_TESTS_RUNS_DIR/`:

| File | Format | Contents |
|------|--------|----------|
| `benchmark.json` | JSON | Full per-test data (all metrics above) |
| `benchmark.md` | Markdown | Tier summary tables + progressive analysis + failed test detail |
| `benchmark_history.json` | JSON array | Per-run summary (last 50 runs) for trend tracking |
| `ndjson_logs/<test>.ndjson` | NDJSON | Raw Claude CLI stream per test (for debugging tool call sequences) |

Latest results are copied to `docs/llm-test-benchmark.md` for version control.

### Strengths

- **Unique in the ecosystem**: very few open-source projects have automated LLM agent testing. The progressive L1/L2/L3 methodology systematically measures how well tool descriptions guide the model.
- **Eval case auto-discovery**: `eval_parser.py` scrapes "Should trigger" tables from skill `eval.md` files, keeping tests DRY and co-located with skill definitions.
- **Benchmark reporting**: per-test timing, token usage, cost, pass rates — written as JSON + markdown. Historical tracking via `benchmark_history.json`.
- **Guardrail regression tests**: dedicated tier 4 ensures the agent doesn't bypass MCP tools with raw scripts.
- **Flaky test management**: explicit `FLAKY_TESTS` set with promotion path (remove pattern when stable). Separate `-m flaky` and `-m stable` markers.
- **Budget-aware**: hard cap on prompt invocations prevents runaway costs during development.

### Weaknesses

- **Non-deterministic by nature**: LLM outputs vary run-to-run. Even with retries, ~4% of tests remain flaky (18 known patterns). Hard to distinguish "flaky prompt" from "broken tool description".
- **Slow**: full suite takes ~2-3 hours. Progressive tier alone is ~60 min. This discourages frequent runs.
- **No CI integration**: runs locally only (`LLM_TESTS_ENABLED=1`). No automated regression gate — regressions can ship.
- **Setup dependency chain**: `test_01_setup` must run first to create baseline models. If it fails, all downstream tests skip. No automatic re-creation.
- **Single-model testing**: all tests use Claude (sonnet default). No cross-model comparison (GPT-4, Gemini) to validate tool descriptions are model-agnostic.
- **Binary pass/fail**: a test that calls the right tool with wrong parameters passes if the tool name matches. Limited parameter-level assertion.
- **Cost opacity**: cost figures are "notional API pricing" (free on Claude Max). No real cost tracking for non-Max users.

---

## 3. Unit Tests

### Methodology

Pure Python tests that don't require Docker or OpenStudio. Cover tool registration, path safety, SWIG cleanup, error parsing, unit conversions, skill document validation, and JSON-RPC protocol compliance.

### Categories

| Category | Files | What it tests |
|----------|-------|--------------|
| **Registration** | `test_skill_registration.py` | All 138 tools register, no broken imports |
| **Skill docs** | `test_skill_docs.py`, `test_skill_tools.py` | SKILL.md format, skill discovery |
| **Protocol** | `test_stdio_smoke.py` | Raw JSON-RPC messages, no stdout contamination |
| **Security** | `test_path_safety.py` | Path traversal guards, OSError handling |
| **Parsing** | `test_err_parser.py`, `test_unit_conversions.py` | EnergyPlus .err parsing, unit math |
| **Contract** | `test_contract.py` | Response JSON schema compliance |

### Strengths

- **Fast**: run in seconds, no Docker overhead.
- **Registration completeness**: `test_skill_registration.py` verifies all 138 tools register correctly — catches broken imports and missing `register()` functions.
- **Protocol-level testing**: `test_stdio_smoke.py` validates raw JSON-RPC messages, ensuring no stdout contamination from SWIG bindings.
- **Security testing**: `test_path_safety.py` checks path traversal guards.

### Weaknesses

- **Small surface area**: ~10 files, ~200 tests. Most logic lives in `operations.py` files that require OpenStudio SDK to test.
- **No mocking strategy**: the project doesn't mock OpenStudio bindings for faster testing of business logic. Everything that touches the SDK requires the full Docker container.

---

## 4. CI/CD Pipeline

### Methodology

Two-job GitHub Actions workflow:
1. **Build**: Docker image with GHA buildx cache + unit tests
2. **Test**: 5 parallel shards pull the image artifact, run integration tests

### Shard Breakdown

| Shard | Focus | ~Duration |
|-------|-------|-----------|
| 1 | Simulation pipelines, component properties, weather, ComStock, loop ops, retrofit skill | ~200s |
| 2 | Common measures, HVAC baseline systems, geometry, zone terminals, energy reports | ~200s |
| 3 | Controls, object mgmt, loads, building info, DOAS, HVAC wiring, measures, validation | ~200s |
| 4 | VRF, radiant, query tools, creation tools, results extraction, protocol tests | ~200s |
| 5 | HVAC supply simulation, HVAC validation, bar building | ~200s |

### Strengths

- **Efficient caching**: Docker buildx layer cache minimizes rebuild time.
- **Parallel shards**: 5-way split keeps CI under 6 min wall time.
- **Artifact sharing**: build-once, test-many pattern avoids redundant builds.

### Weaknesses

- **No LLM test gate**: agent behavior regressions aren't caught in CI.
- **Manual shard balancing**: files hand-assigned; no script to detect drift.
- **No coverage gates**: no minimum coverage thresholds or trend tracking.
- **No flaky test detection**: no automatic quarantine for tests that pass on retry.
- **Single OS**: tests only run on Linux (Docker). No Windows/macOS validation despite Windows dev environment.

---

## 5. Areas for Improvement

### High Impact

1. **Add code coverage**: integrate `pytest-cov` + coverage report. Set a baseline threshold. Low effort, high visibility into gaps.
2. **LLM tests in CI**: run a smoke subset (`-m smoke`, 12 tests, ~10 min) on PRs that touch tool descriptions or server instructions. Gate on stable tests only.
3. **Automated shard balancing**: script that reads test durations from CI logs and rebalances `FILES=` lists in `ci.yml`.
4. **Negative/edge-case tests**: systematically test malformed inputs, missing parameters, invalid model state, concurrent access.

### Medium Impact

5. **Mock OpenStudio for unit tests**: create a lightweight mock layer for `openstudio.model` to enable fast testing of business logic in `operations.py` without Docker.
6. **Parameter-level LLM assertions**: beyond "right tool called", assert that key parameters (e.g., system type, zone name) are correct.
7. **Cross-model LLM testing**: run progressive suite against multiple models to validate tool descriptions are model-agnostic.
8. **Flaky test dashboard**: track flaky rate per test over time, auto-quarantine tests that fail >20% of runs.

### Lower Priority

9. **Windows CI shard**: add a Windows runner to catch path-handling bugs (forward vs back slashes, temp dir differences).
10. **Performance benchmarks**: track test duration trends per shard. Alert on >20% regression.
11. **Property-based testing**: use Hypothesis for fuzz-testing tool parameter validation (str lists, numeric ranges, enum values).
12. **Shared model fixtures**: reduce redundant model creation across integration tests by sharing loaded models within test modules via module-scoped fixtures.

---

## Appendix: Quick Reference

### Run Commands

```bash
# Unit tests (no Docker)
pytest tests/test_skill_registration.py -v

# Integration tests (Docker)
docker run --rm -v "C:/projects/openstudio-mcp:/repo" -v "C:/projects/openstudio-mcp/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_hvac_systems.py"

# LLM tests
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m smoke -v       # quick (~12 tests, 10 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m progressive -v  # tool descriptions (~102 tests, 60 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v                 # full (~160 tests, 2-3 hrs)
```

### Key Files

| File | Purpose |
|------|---------|
| `tests/conftest.py` | Integration fixtures, MCP helpers, polling |
| `tests/llm/conftest.py` | LLM markers, retry logic, benchmark collection |
| `tests/llm/runner.py` | `run_claude()`, NDJSON parsing, `ClaudeResult` |
| `tests/llm/eval_parser.py` | Auto-parse skill eval.md into test cases |
| `.github/workflows/ci.yml` | CI pipeline, shard definitions |
| `docs/llm-test-benchmark.md` | Latest benchmark results + run history |
