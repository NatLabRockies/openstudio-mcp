# LLM Agent Tests

Behavioral tests that verify Claude picks the right MCP tools and chains them correctly. Each test spawns a fresh Docker container via `claude -p` with MCP config.

## Quick Start

```bash
# Run all LLM tests (~75 min with retries=1)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v

# Run ONLY flaky tests (~10 tests, ~10 min) — for iterating on reliability
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m flaky -v

# Run ONLY stable tests (~80 tests, ~60 min) — regression check
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m stable -v

# Run a single test by ID
LLM_TESTS_ENABLED=1 pytest "tests/llm/test_04_workflows.py::test_workflow[bar_then_typical]" -v

# Run only tier 1 (tool selection, fastest — ~5 min)
LLM_TESTS_ENABLED=1 LLM_TESTS_TIER=1 pytest tests/llm/ -v

# Add retries for CI-like confidence (default: 0)
LLM_TESTS_ENABLED=1 LLM_TESTS_RETRIES=2 pytest tests/llm/ -v
```

## Prerequisites

- Docker image built: `docker build -f docker/Dockerfile -t openstudio-mcp:dev .`
- `claude` CLI in PATH
- Not running inside Claude Code (strips `CLAUDECODE` env var internally)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_TESTS_ENABLED` | (unset) | Set to `1` to enable tests |
| `LLM_TESTS_RETRIES` | `0` | Retry count for flaky LLM tests |
| `LLM_TESTS_TIER` | `all` | Filter: `1`, `2`, `3`, `4`, or `all` |
| `LLM_TESTS_MODEL` | `sonnet` | Model: `sonnet`, `haiku`, `opus` |
| `LLM_TESTS_MAX_PROMPTS` | `300` | Hard cap on Claude invocations per run |
| `LLM_TESTS_RUNS_DIR` | `/tmp/llm-test-runs` | Host path mounted as `/runs` in Docker |
| `LLM_TESTS_MEASURES_DIR` | `/tmp/llm-test-measures` | Host path mounted as `/measures` (persists custom measures across the per-prompt containers) |
| `LLM_TESTS_PROVIDER` | `claude` | Agent backend: `claude` or `codex` (codex prepends the system prompt to the user prompt; no allowed-tools/max-turns equivalent) |
| `LLM_TESTS_CODEX_CMD` | (auto) | codex CLI path override (default: PATH, then the Windows install dir) |
| `LLM_TESTS_IMAGE` | `openstudio-mcp:dev` | MCP server image — sweeps pin the release tag |
| `LLM_TESTS_ARM` | `full` | Assistance-layer ablation (see below) |

### Assistance arms (`LLM_TESTS_ARM`)

| Arm | What it removes | Notes |
|-----|-----------------|-------|
| `full` | nothing | all assistance layers on |
| `noskills` | server-side knowledge tools (`list_skills`/`get_skill`/`recommend_tools`) | |
| `nodiscovery` | client-side deferred tool search (loads every schema up front) | claude only; matches codex's native schema loading |
| `nodiscovery-noskills` | both of the above | |
| `nohost` | host tools (Bash/Edit/Write/…) | claude only; codex sandbox cancels MCP calls if host tools are cut |
| `codegen` | the MCP server itself | Arm C: agent scripts the SDK in a bare container (`test_11_codegen_arm.py`); opt-in, outcome-only grading |

## Reproducing the paper benchmark

The Section 3.2 benchmark is a multi-leg sweep, not a single `pytest` run.
Each leg is one `(model, arm, repeat)` full run; `scripts/benchmark_sweep.py`
drives the matrix (retries forced to 0, provenance recorded per leg) and
`scripts/benchmark_aggregate.py` produces the pass-rate tables. The exact
commands, the pinned image/harness, and the 18-task selection are in the
archived dataset's `README.md` (deposited with the release DOI). In short:

```bash
git checkout v1.2.0 && docker build -f docker/Dockerfile -t openstudio-mcp:v1.2.0 .
python scripts/benchmark_sweep.py --sweep-id paper-v1.2.0 --image openstudio-mcp:v1.2.0 \
  --model claude-sonnet-4-6:claude --arms full,noskills,nodiscovery,nodiscovery-noskills,nohost \
  --repeats 3 --pytest-args "<18-task -k selection>"
python scripts/benchmark_check_leg.py results/paper-v1.2.0     # contamination gate
python scripts/benchmark_aggregate.py results/paper-v1.2.0     # Wilson-CI tables
```

Frozen numbers and provenance: [`../../docs/testing/llm-test-benchmark.md`](../../docs/testing/llm-test-benchmark.md).

## Test Files (259 tests total, counts from `pytest tests/llm --co`)

| File | Count | Description |
|------|-------|-------------|
| `test_01_setup.py` | 8 | Creates models, seeds `my_measure` + EMS plugin model, runs baseline+retrofit sims |
| `test_02_tool_selection.py` | 4 | Single tool selection |
| `test_03_eval_cases.py` | 26 | Skill eval prompts |
| `test_04_workflows.py` | 37 | Multi-step tool chains (full chains assert pinned EUI) |
| `test_05_guardrails.py` | 3 | Safety/refusal tests |
| `test_06_progressive.py` | 149 | 60 operations; L1/L2 all, L3 only for `L3_KEEP` (29) |
| `test_07_fourpipe_e2e.py` | 1 | SystemD e2e with pinned EUI refs |
| `test_08_measure_authoring.py` | 4 | Measure authoring regressions |
| `test_09_tool_routing.py` | 12 | Routing A/B cases |
| `test_10_confusion_pairs.py` | 9 | Ambiguous-prompt tool choice |
| `test_11_codegen_arm.py` | 6 | Arm C codegen baseline — no MCP server, agent scripts the SDK (opt-in: `LLM_TESTS_ARM=codegen`) |

**Comparability epoch (2026-08-05):** phases 0-3 of the realism rework
(prompt casing preserved, arg/ok/EUI asserts, L3 trim, +16 coverage cases)
break strict comparability with Runs <= 16.

## Stable vs Flaky Classification

Tests are auto-tagged `stable` or `flaky` by `conftest.py` based on pass history across Runs 2-4. The `FLAKY_TESTS` set in `conftest.py` lists substring patterns matched against test nodeids.

**Flaky tests (~11):** tier4 guardrails (2), troubleshoot evals (4), multi-step workflows (3), structural L1 progressive (2).

**Stable tests (~79):** setup (3), all tier1 (14), most tier2 (11/14), most tier3 (23/27), all progressive L2+L3 (20), most progressive L1 (8/10).

To promote a flaky test to stable: remove its pattern from `FLAKY_TESTS` in `conftest.py`.

## Lessons Learned

### Output capture
`pytest` output is swallowed when the custom retry hook in `conftest.py` intercepts test protocol. Use `tee` to a file:
```bash
LLM_TESTS_ENABLED=1 pytest ... 2>&1 | tee /tmp/llm_test_out.txt
```

### ToolSearch consumes turns
Claude Code's deferred tool loading (`ToolSearch`) uses 1-3 agent turns before any MCP tool is called. Multi-step workflows (3+ MCP calls) need `max_turns=25` or higher. Without it, the agent runs out of turns mid-chain.

### Prompt style matters
- Explicit tool names in prompts (`"using create_bar_building"`) are essential
- Natural language chaining works better than numbered steps
- Bad: `"1. create_bar_building with building_type SmallOffice, num_stories_above_grade 2"`
- Good: `"Create a SmallOffice bar building using create_bar_building with 2 stories and 20000 sqft"`

### Timeouts
- Single-tool tests: 90-120s
- 2-tool chains: 120s
- 3-tool chains: 300-420s (ToolSearch + measure execution)
- Single simulation chains: 300-420s
- Two-sim comparison chains: 600-720s

### Use `change_building_location` for weather
`change_building_location` sets EPW + design days (from DDY) + climate zone in one call. `set_weather_file` was removed — always use `change_building_location`. The EPW must have companion `.stat` and `.ddy` files in the same directory with the same base filename.

### Debugging failures
Check the tool call sequence in assertion errors — it reveals agent behavior:
- Repeated `list_files` = agent searching for model file (check baseline path)
- `list_skills`, `list_comstock_measures` = agent exploring, lost
- Missing expected tool = ran out of turns or stopped early
- Wrong tool called = agent found a valid alternative (check test assertions)
- Tool called but assertion fails = test definition may be too strict

### Docker mounts
- `/runs` — model save/load (from `LLM_TESTS_RUNS_DIR`)
- `/measures` — persistent custom-measure root (from `LLM_TESTS_MEASURES_DIR`).
  Every `run_claude` spawns a fresh `--rm` container; without this mount,
  measures created in one test would vanish before the next
- `/test-assets` and `/inputs` (read-only) — `tests/assets/` for FloorspaceJS
  files, SystemD models, the set_building_name measure, Boston EPW set
- EPW files at `/opt/comstock-measures/.../tests/*.epw` (baked into image)

### Minimizing Claude Max usage
Each test invocation loads ~27K tokens of tool definitions (150+ tools). Full suite
uses ~9M+ cache read tokens per run. To conserve weekly quota:
- **Iterate on specific tests:** `pytest tests/llm/test_06_progressive.py -k "thermostat_L1" -v`
- **Use tier filters:** `LLM_TESTS_TIER=1` for tier 1 only (14 tests, ~5 min)
- **Full suite only for final validation** — not per-change
- **`haiku` model** uses less quota: `LLM_TESTS_MODEL=haiku` (lower pass rate)

### Retries
Default 0 retries (single attempt) gives first-attempt signal for model comparison. Set `LLM_TESTS_RETRIES=2` for CI-like confidence with non-deterministic tests.

### Benchmark reports
After each run, benchmark data is written to `LLM_TESTS_RUNS_DIR`:
- `benchmark.json` — raw per-test data (tokens, cost, timing, tool calls)
- `benchmark.md` — aligned markdown tables grouped by tier + progressive analysis
- `benchmark_history.json` — summary per run (last 50 runs)
- `ndjson_logs/<test_name>.ndjson` — raw NDJSON output from each test (cleared per run)

Cost figures are notional API pricing from the Claude CLI — free on Claude Max.

### NDJSON output capture
Every test run persists the full NDJSON stream from `claude -p` to `ndjson_logs/`. Use these to debug:
- Why a tool call failed (inspect `tool_result` content blocks)
- What arguments the agent passed to each tool
- Why the agent called a tool twice (see error response from first call)
- Full conversation flow including assistant reasoning

Logs are named by test ID (e.g. `measure_set_lights_full_chain.ndjson`). Retried tests get `_attempt2` suffix. The directory is cleared at session start so only the latest run is kept.

### Before/after comparison tests
The 4 `measure_*_full_chain` workflow tests run two simulations: one baseline (unmodified model) and one after applying the custom measure. Prompts set Boston weather explicitly — without it the sim exits failed in ~1s while `extract_summary_metrics` still returns `ok:true` with null metrics. The tests assert `run_simulation` called at least twice AND the baseline EUI from actual tool results is within 5% of the pinned 57.41 kBtu/ft2 reference (re-pin on OpenStudio version bumps).

The `systemd_fourpipebeam_e2e` test is the most realistic — it uses natural language (no tool names) with the 44-zone SystemD model, matching an actual Claude Desktop user session. Expected results: baseline EUI ~28.21, retrofit ~28.44 kBtu/ft2, unmet hours drop from ~58.5 to ~34.5.

### Anti-loop guardrails
The MCP server's `instructions` field (server.py) and `list_files` tool description prevent the agent from looping on `list_files` calls. This was the single biggest reliability improvement (44% -> 83% pass rate). The guardrails are native to the server so all MCP clients benefit. `runner.py` has a minimal system prompt that can be overridden per-test via `run_claude(system_prompt=...)`.

### Progressive tests
`test_06_progressive.py` tests 60 operations at up to 3 specificity levels:
- **L1 (vague):** "Add HVAC to the building" — tests tool description keywords
- **L2 (moderate):** "Add a VAV reheat system to all zones" — tests with context
- **L3 (explicit):** "Add System 7 VAV reheat using add_baseline_system" — tests with tool name

L3 is emitted only for `L3_KEEP` members (historical failures, complex-arg
tools, confusion pairs, and new cases for their first 3 runs) — for everything
else it was a near-tautology and is trimmed.

Pass now requires: an accepted tool called, its first call not `ok:false`,
and (where `expected_args` pins them) argument values matching the prompt.

If L1 fails but L2/L3 pass, the tool description needs better keywords.
If all levels fail, there's a structural issue (tool API mismatch, missing args, etc.).
