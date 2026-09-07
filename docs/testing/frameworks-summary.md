# Testing Frameworks Summary

A side-by-side view of the three test tiers: what each covers, how it runs, where it is strong,
where it is weak, and what is still on the backlog. Counts and timings were measured on
2026-08-22; re-baseline this file when they drift.

## Overview

| Tier | Tests | Where it runs | Gate |
|---|---|---|---|
| Unit | 506 | any Python environment; CI build job | `pytest -m "not integration"` |
| Integration | 663 | Docker; CI 5 amd64 shards + 2 arm64 shards | `@pytest.mark.integration` + `RUN_OPENSTUDIO_INTEGRATION=1` |
| LLM agent | 259 in 11 files | local only (Claude Code CLI or Codex CLI) | `@pytest.mark.llm` + `LLM_TESTS_ENABLED=1` |

Unit and integration tests share the 114 files in `tests/`. CI is four jobs in
`.github/workflows/ci.yml` (build, test ×5, arm64-build, arm64-test ×2) plus a separate
`security.yml`; wall time is set by the slowest shard, 12-14 min.

---

## 1. Integration tests

### How they work

Each test spawns the MCP server as a subprocess over stdio (`stdio_client(server_params())`),
creates a model with a UUID-based unique name, calls tools exactly as an MCP client would, and
asserts on the `{"ok": ..., ...}` response dict. They run inside the Docker image with the full
OpenStudio SDK, EnergyPlus, and the bundled ComStock / common measures. Nothing is mocked.

Shared helpers in `tests/conftest.py`: `create_and_load()`, `create_baseline_and_load()`,
`unwrap()`, `poll_until_done()`. Every test carries a `# Regression:` or `# Validates:` comment.

### What they cover, by CI shard

| Shard | Focus |
|---|---|
| 1 | SEB4 full simulation + EUI pin, example workflows, component properties, ComStock, weather, loop operations, retrofit skill, load/save + file listing, merge-coplanar fixture regression |
| 2 | common measures, HVAC baseline systems 1-10, geometry, zone terminals, energy-report skill, HTTP transport / session isolation / token auth / session eviction, measure discovery + BCL + per-tenant measures isolation, python EMS, outcome grader ground truth, gbXML climate-zone (.stat) |
| 3 | controls, object management, generic access, loads, building, DOAS, air/plant loops, measures, measure authoring, QA/QC skill, HVAC supply wiring, gbXML climate-zone (WMO), paired-vertex sync, ground contact, import timeout, geometry write guards |
| 4 | VRF, radiant, query skills (spaces, space types, schedules, constructions, loads), creation tools, air terminals, results extraction, gbXML import (minus its three heaviest tests, split into shards 1-3 by node id), validate_osw / run_osw, add_layer_to_construction |
| 5 | HVAC supply simulation smoke, HVAC validation, bar building, concurrent tools, stdout-logger silence, simulation queue, per-user run-dir isolation, run retention, python EMS phase 2, comfort benchmark, weather fail-fast, hvac_only parity |
| arm64 1 / 2 | core real-simulation subset of amd64 shard 1 / the arch-sensitive set (SWIG memleak, stdout logger, measures, measure authoring, HVAC supply sim) |
| `security.yml` | `tests/test_sandbox.py` under `OSMCP_SANDBOX=auto` on amd64 and arm64 (dual-run: attack succeeds with the sandbox off, is blocked with it on) |

The `ci.yml` comments are the authoritative shard map; the table above is a summary.

### Strengths

- High fidelity: real SDK, real EnergyPlus, real MCP transport. Catches SWIG binding issues, model-state bugs, measure failures, and multi-tenant path leaks that unit tests cannot.
- Breadth: every MCP tool has at least one integration test (CLAUDE.md rule 2), plus security-specific suites (path safety, sandbox, session and measure isolation).
- Contract testing: `test_contract.py` (response JSON schema) and `test_response_sizes.py` (payload limits).
- Parallel CI with explicit provenance: one image built once, shared to every shard and pushed to Docker Hub.

### Weaknesses

- No code-coverage measurement; which code paths are exercised is inferred, not reported.
- Heavy Docker dependency (~2 GB image) slows the feedback loop for contributors.
- Each test builds its own model; little fixture sharing, so runtime grows linearly with test count.
- Shard balancing is manual (`FILES=` lists hand-edited), and the 12-14 min shards make a full CI run a coffee break.
- No parametric stress tests (very large models, long measure chains, concurrency limits beyond the sim-queue tests).

---

## 2. LLM agent tests

### How they work

`tests/llm/runner.py::run_agent()` launches a real agent CLI with the prompt and an MCP config
pointing at the Docker server: `claude -p ... --output-format stream-json --verbose` for Claude
models, `codex exec --json` for GPT models (`LLM_TESTS_PROVIDER`). The NDJSON stream is parsed into
an `AgentResult` (tool calls, tokens, cost, turns, final text). Each test runs in a fresh empty
working directory so the agent cannot read the repo or leave files that later tests could find.

Every trial is scored by two deterministic checks, no LLM judge:

1. **Routing**: a tool from the task's accept set was called and its first call succeeded (with
   pinned argument values where defined).
2. **Outcome**: `tests/llm/grading/` reloads the artifact the agent saved and grades physical
   facts (assembly R-values, HVAC loop membership, simulated setpoints, EnergyPlus results against
   pinned references) with a versioned rubric (`RUBRIC_VERSION`, currently 1.3). Facts are stored
   in every row, so a rubric change re-scores without re-running agents.

Assistance arms (`LLM_TESTS_ARM`): `full`, `noskills` (server hides the knowledge tools),
`nodiscovery` (Claude Code loads every schema up front instead of deferred ToolSearch),
`nodiscovery-noskills`, `nohost` (host tools disabled), `codegen` (no MCP server; the agent
scripts the SDK directly). Benchmark sweeps pin one image and one harness commit per sweep
(`scripts/benchmark_sweep.py`), screen legs for API-corrupted rows
(`scripts/benchmark_check_leg.py`), and aggregate per sweep (`scripts/benchmark_aggregate.py`).

### Files

| File | Tests | What it exercises |
|---|---|---|
| `test_01_setup.py` | 8 | Creates the baseline / HVAC / example models and seed fixtures every later test loads |
| `test_02_tool_selection.py` | 4 | Single-tool discovery with no model state |
| `test_03_eval_cases.py` | auto | Positive and negative action-routing cases auto-parsed from `.claude/skills/*/eval.md`, plus explicit served-guide routing cases |
| `test_04_workflows.py` | 37 | Multi-step chains: load → weather → HVAC → simulate → extract |
| `test_05_guardrails.py` | 3 | The agent must not bypass MCP with Bash / Edit / Write |
| `test_06_progressive.py` | 149 | **The core diagnostic**: operations posed at L1 (vague), L2 (moderate), L3 (tool named); the benchmark's 16-task hard set is a `-k` subset of this file |
| `test_07_fourpipe_e2e.py` | 1 | Natural-language retrofit of a 44-zone model, two simulations, ~5 min |
| `test_08_measure_authoring.py` | 4 | Custom measure create / edit / test regressions |
| `test_09_tool_routing.py` | 12 | A/B of the full roster vs `recommend_tools` routing (not in the benchmark) |
| `test_10_confusion_pairs.py` | 9 | Prompts that plausibly fit two similar tools |
| `test_11_codegen_arm.py` | 6 | Arm C: no MCP server, outcome-only grading |

Markers: `llm`, `tier1`-`tier4`, `progressive`, `smoke`, `stable`, `flaky`, `generic`,
`needs_baseline`, `needs_hvac`. `FLAKY_TESTS` in `conftest.py` (30 patterns) is the quarantine
list. Defaults: `LLM_TESTS_RETRIES=0` (repeats replace retries), `LLM_TESTS_MAX_PROMPTS=300`,
`LLM_TESTS_TIMEOUT_BASE=120` s per task, `LLM_TESTS_MODEL=sonnet`.

### What is measured

Per test: pass/fail, failure mode (`timeout`, `no_mcp_tool`, `wrong_tool`, `wrong_args`,
`tool_error`, `outcome_mismatch`; `recovered` tag), duration, turns, ordered tool calls, tokens,
CLI-reported cost, ToolSearch count, host-tool counts (escape detection), and the gate-2
`outcome` dict. Per sweep (`results/<sweep>/paper/`): outcome-vs-routing per model / arm / case,
pass rates, L1/L2/L3 discovery rates, failure modes, repeat stability, behavior means, $/test
(CLI-reported and token-derived). Current numbers: `llm-test-benchmark.md`.

Still not measured: time-to-first-tool, error-recovery rate as its own metric, and any Gemini
backend.

### Strengths

- Rare in the ecosystem: an automated, outcome-graded agent benchmark with L1/L2/L3 prompts that separates "wrong description" from "cannot discover" from "broken tool".
- Reproducible: pinned image + harness commit per sweep, per-leg provenance in every result file, an aggregator that refuses to pool mismatched legs, and a frozen dataset deposited with the release.
- Cross-vendor (Claude and GPT via Codex) and ablation-ready (arms) without changing tests.
- Eval cases auto-discovered from skill `eval.md` files stay co-located with the skills they test; the authoring contract is documented in [`tests/llm/README.md`](../../tests/llm/README.md#skill-eval-files).

### Weaknesses

- Non-deterministic: even at three repeats, single misses are at the resolution limit; the flaky list needs periodic pruning.
- Slow and manual: the full suite is hours, the benchmark matrix is a day, and nothing runs in CI, so agent-behavior regressions can ship.
- Setup chain: `test_01_setup` must succeed first or everything downstream skips.
- Agent-CLI versions are not recorded in `run_config` (the Docker image and harness commit are).

---

## 3. Unit tests

### Categories

| Category | Files | What it tests |
|---|---|---|
| Registration | `test_skill_registration.py` | every tool registers; `EXPECTED_TOOLS` is the roster of record |
| Skill docs | `test_skill_docs.py`, `test_skill_tools.py` | SKILL.md frontmatter, tool-name cross-references, skill discovery |
| Protocol | `test_stdio_smoke.py` | raw JSON-RPC on stdio, no stdout pollution |
| Security / isolation | `test_path_safety.py`, `test_measure_isolation.py` | path-traversal guards, per-user roots disjoint, cross-tenant denied |
| Parsing / units | `test_err_parser.py`, `test_unit_conversions.py` | EnergyPlus `.err` parsing, unit math |
| Contract | `test_contract.py` | response JSON schema |
| Benchmark tooling | `test_llm_outcome_rubric.py`, `test_benchmark_build_t600.py`, `test_benchmark_check_leg.py`, `test_benchmark_aggregate.py` | rubric verdicts on known facts, the 600 s merge builder, the contamination screen, aggregation |

### Strengths

- Fast (seconds) and Docker-free; runs in the CI build job before any image is shared.
- The security and benchmark-tooling suites are red-green tested: each was shown to fail on the unfixed code before the fix landed.

### Weaknesses

- Most business logic lives in `operations.py` files that need the SDK, so the unit surface is
  structurally small; there is no mock layer for `openstudio.model`.

---

## 4. CI/CD

| Job | What it does | Last green `develop` run |
|---|---|---|
| `build` | Docker image with buildx cache, sanity checks, unit tests, save image artifact, push to Docker Hub | 9 min |
| `test` (shards 1-5) | load the image, run that shard's `FILES=` list with `RUN_OPENSTUDIO_INTEGRATION=1` and `OSMCP_SANDBOX=auto` | 12-14 min each |
| `arm64-build` / `arm64-test` (1-2) | arm64 image from `Dockerfile.arm64`, real-sim and arch-sensitive shards | 3 min / 5-6 min |
| `security.yml` (separate workflow) | `tests/test_sandbox.py` plus `tests/test_security_*.py` on amd64 and arm64 | — |

Strengths: build-once / test-many, layer caching, `fail-fast: false` so one shard failure does
not hide others, arm64 parity. Weaknesses: no LLM gate, manual shard balancing, no coverage
gate, Linux only (Windows path handling is untested in CI despite Windows dev machines).

---

## 5. Backlog

1. Code coverage (`pytest-cov`) with a baseline threshold.
2. An LLM smoke subset (`-m smoke`, ~10 min) on PRs that touch tool descriptions or server instructions.
3. A script that rebalances `FILES=` lists from recorded durations.
4. Systematic negative tests: malformed inputs, missing parameters, invalid model state.
5. Record agent-CLI versions in benchmark `run_config`.
6. Rubric 2.0: grade four-pipe-beam coil-to-plant wiring (needs a re-run).
7. Flaky-rate tracking per LLM test with automatic quarantine.
8. Shared module-scoped model fixtures to cut redundant model creation.
9. A Windows CI shard for path-handling bugs; property-based tests for parameter validation.

---

## Quick reference

```bash
# Unit
pytest -m "not integration" tests/

# Integration (one file)
docker run --rm -v "C:/projects/openstudio-mcp:/repo" -v "C:/projects/openstudio-mcp/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_hvac_systems.py"

# LLM
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m smoke -v        # ~10 min
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m progressive -v  # the L1/L2/L3 diagnostic
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v                 # everything, hours
```

| File | Purpose |
|---|---|
| `tests/conftest.py` | integration fixtures, MCP helpers, polling |
| `tests/llm/conftest.py` | LLM markers, flaky list, budget, benchmark collection |
| `tests/llm/runner.py` | `run_agent()` / `run_claude()`, NDJSON parsing, `AgentResult` |
| `tests/llm/grading/` | gate-2 graders (`container_grader.py`, `host.py`, `rubric.py`) |
| `tests/llm/eval_parser.py` | turns skill `eval.md` positive and negative routing tables into tests; see the [authoring contract](../../tests/llm/README.md#skill-eval-files) |
| `scripts/benchmark_sweep.py`, `benchmark_check_leg.py`, `benchmark_aggregate.py`, `benchmark_build_t600_dataset.py` | sweep driver, contamination screen, aggregator, 600 s merge builder |
| `.github/workflows/ci.yml`, `security.yml` | CI shards and the sandbox workflow |
| `docs/testing/llm-test-benchmark.md` | current benchmark numbers and run history |
