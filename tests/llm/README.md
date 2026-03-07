# LLM Agent Tests

Behavioral tests that verify Claude picks the right MCP tools and chains them correctly. Each test spawns a fresh Docker container via `claude -p` with MCP config.

## Quick Start

```bash
# Run all LLM tests (slow — ~30-45 min for full suite with retries)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v

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
| `LLM_TESTS_MAX_PROMPTS` | `50` | Hard cap on Claude invocations per run |
| `LLM_TESTS_RUNS_DIR` | `/tmp/llm-test-runs` | Host path mounted as `/runs` in Docker |

## Test Tiers

| Tier | File | Count | Time | Description |
|------|------|-------|------|-------------|
| 1 | `test_02_tool_selection.py` | ~14 | ~5 min | Single tool selection |
| 2 | `test_04_workflows.py` | ~14 | ~20 min | Multi-step tool chains |
| 3 | `test_03_eval_cases.py` | ~30 | ~15 min | Skill eval prompts |
| 4 | `test_05_guardrails.py` | ~2 | ~3 min | Safety/refusal tests |
| setup | `test_01_setup.py` | ~5 | ~5 min | Creates models for other tiers |

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
`change_building_location` sets EPW + design days (from DDY) + climate zone in one call. `set_weather_file` was removed — always use `change_building_location`.

### Debugging failures
Check the tool call sequence in assertion errors — it reveals agent behavior:
- Repeated tool calls = tool is failing, agent retrying
- `list_skills`, `list_comstock_measures` = agent exploring, lost
- Missing expected tool = ran out of turns or stopped early

### Docker mounts
- `/runs` — model save/load (from `LLM_TESTS_RUNS_DIR`)
- `/test-assets` (read-only) — `tests/assets/` for FloorspaceJS files etc.
- EPW files at `/opt/comstock-measures/.../tests/*.epw` (baked into image)

### Retries
Default 2 retries handles ~80% pass-rate LLM non-determinism. Set `LLM_TESTS_RETRIES=0` when iterating on a single test to get fast feedback. Set to `1` for a quick check, `2-3` for CI-like confidence.
