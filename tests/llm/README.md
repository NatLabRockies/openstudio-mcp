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

# Reduce retries for faster iteration (default: 2)
LLM_TESTS_ENABLED=1 LLM_TESTS_RETRIES=0 pytest tests/llm/ -v
```

## Prerequisites

- Docker image built: `docker build -f docker/Dockerfile -t openstudio-mcp:dev .`
- `claude` CLI in PATH
- Not running inside Claude Code (strips `CLAUDECODE` env var internally)

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_TESTS_ENABLED` | (unset) | Set to `1` to enable tests |
| `LLM_TESTS_RETRIES` | `2` | Retry count for flaky LLM tests |
| `LLM_TESTS_TIER` | `all` | Filter: `1`, `2`, `3`, `4`, or `all` |
| `LLM_TESTS_MODEL` | `sonnet` | Model: `sonnet`, `haiku`, `opus` |
| `LLM_TESTS_MAX_PROMPTS` | `100` | Hard cap on Claude invocations per run |
| `LLM_TESTS_RUNS_DIR` | `/tmp/llm-test-runs` | Host path mounted as `/runs` in Docker |

## Test Tiers

| Tier | File | Count | Time | Description |
|------|------|-------|------|-------------|
| setup | `test_01_setup.py` | 3 | ~1 min | Creates models for other tiers |
| 1 | `test_02_tool_selection.py` | 14 | ~5 min | Single tool selection |
| 2 | `test_04_workflows.py` | 14 | ~10 min | Multi-step tool chains |
| 3 | `test_03_eval_cases.py` | 27 | ~35 min | Skill eval prompts |
| 4 | `test_05_guardrails.py` | 2 | ~3 min | Safety/refusal tests |
| progressive | `test_06_progressive.py` | 30 | ~15 min | L1/L2/L3 specificity levels |

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
- Simulation chains: 600s

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
- `/test-assets` (read-only) — `tests/assets/` for FloorspaceJS files etc.
- EPW files at `/opt/comstock-measures/.../tests/*.epw` (baked into image)

### Retries
Default 2 retries handles ~80% pass-rate LLM non-determinism. Set `LLM_TESTS_RETRIES=0` when iterating on a single test to get fast feedback. Set to `1` for a quick check, `2-3` for CI-like confidence.

### Benchmark reports
After each run, benchmark data is written to `LLM_TESTS_RUNS_DIR`:
- `benchmark.json` — raw per-test data (tokens, cost, timing, tool calls)
- `benchmark.md` — aligned markdown tables grouped by tier + progressive analysis
- `benchmark_history.json` — summary per run (last 50 runs)

Cost figures are notional API pricing from the Claude CLI — free on Claude Max.

### System prompt
`runner.py` includes a default system prompt that tells the agent not to loop on `list_files` when `load_osm_model` fails. This was the single biggest reliability improvement (44% -> 83% pass rate). The prompt can be overridden per-test via `run_claude(system_prompt=...)`.

### Progressive tests
`test_06_progressive.py` tests 10 operations at 3 specificity levels:
- **L1 (vague):** "Add HVAC to the building" — tests tool description keywords
- **L2 (moderate):** "Add a VAV reheat system to all zones" — tests with context
- **L3 (explicit):** "Add System 7 VAV reheat using add_baseline_system" — tests with tool name

If L1 fails but L2/L3 pass, the tool description needs better keywords.
If all levels fail, there's a structural issue (tool API mismatch, missing args, etc.).
