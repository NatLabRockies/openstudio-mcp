# Testing — openstudio-mcp

How the server is tested, what each tier proves, and where to read more.
Counts and timings below were measured on 2026-08-22.

## Three tiers

| Tier | What it proves | Where it runs | Size |
|---|---|---|---|
| **Unit** | Tool registration, parsers, path/identity guards, the benchmark rubric and tooling. Never imports `openstudio`. | Anywhere with Python; the CI build job | 506 tests |
| **Integration** | Every MCP tool against the real OpenStudio SDK, driven over MCP stdio exactly as a client would. Mocks nothing. | The Docker image (`openstudio-mcp:dev`); CI = 5 amd64 shards + 2 arm64 shards | 663 tests |
| **LLM agent** | A real agent (Claude Code CLI or Codex CLI) reads a natural-language prompt, picks and calls tools, and the model it saves is graded. | Local only (`LLM_TESTS_ENABLED=1`); never in CI | 259 tests in 11 files |

Unit and integration tests share the 114 files in `tests/`; LLM tests live in `tests/llm/`. One Docker
image serves both the integration suite and the MCP server the LLM tests talk to.

## Where things stand

- **197 MCP tools** are registered. `EXPECTED_TOOLS` in `tests/test_skill_registration.py` is the
  single source of truth; prose elsewhere deliberately says "150+".
- **CI** (last green run on `develop`): build 9 min, each of the five test shards 12-14 min in
  parallel, arm64 shards 5-6 min. The subprocess-sandbox suite runs in its own `security.yml`
  workflow on amd64 and arm64.
- **LLM benchmark** (release v1.2.1, 600 s completion budget, two-gate grading, full
  configuration; outcome % / routing %): Opus 4.6 100 / 100, Opus 4.8 97.9 / 100, Sonnet 4.6
  91.7 / 100, Haiku 4.5 72.9 / 89.6, GPT-5.4 100 / 100, GPT-5.4-mini 93.8 / 93.8. Details and
  the ablations: [`llm-test-benchmark.md`](llm-test-benchmark.md).

## Running the tests

```bash
# Unit (no Docker)
pytest -m "not integration" tests/

# Integration (inside the Docker image; one file shown, use tests/test_*.py for all)
docker build -f docker/Dockerfile -t openstudio-mcp:dev .
docker run --rm -v "C:/projects/openstudio-mcp:/repo" -v "C:/projects/openstudio-mcp/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_building.py"

# LLM agent: smoke subset (~10 min), a single case, or a pinned benchmark sweep
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m smoke -v
LLM_TESTS_ENABLED=1 pytest tests/llm/test_06_progressive.py -k thermostat_L1 -v
python scripts/benchmark_sweep.py --sweep-id my-sweep --image openstudio-mcp:v1.2.1 \
    --model claude-sonnet-4-6:claude --arms full,noskills --repeats 3 \
    --pytest-args "tests/llm/test_01_setup.py tests/llm/test_06_progressive.py -k '<case filter>'"
```

New integration test files go in the lightest shard's `FILES=` list in `.github/workflows/ci.yml`,
and every test needs a `# Regression:` or `# Validates:` comment (CLAUDE.md rules 2-4).

## The docs in this folder

| Read this | When you want |
|---|---|
| [`testing.md`](testing.md) | to write or run unit/integration tests: conftest helpers, unique-name pattern, Docker setup, CI shard mechanics, annotated examples |
| [`llm-testing-methodology.md`](llm-testing-methodology.md) | the **canonical** description of the LLM suite: harness architecture, the L1/L2/L3 progressive pattern, the two grading gates, assistance arms, providers, and the sweep / check-leg / aggregate scripts |
| [`llm-test-benchmark.md`](llm-test-benchmark.md) | the current citable numbers (600 s merged dataset) and, below the epoch line, the routing-era run history (Runs 1-16) |
| [`frameworks-summary.md`](frameworks-summary.md) | a side-by-side view of the three tiers: coverage, strengths, weaknesses, improvement backlog |
| [`plots/`](plots/) | charts of the routing-era runs (Mar-Apr 2026); `python docs/testing/plots/generate_plots.py` regenerates them from the run-history table and `docs/sweeps/` |
| [`../benchmarks/pilot-archive-2026-08/`](../benchmarks/pilot-archive-2026-08/README.md) | aggregates from the 2026-08 benchmark pilots that preceded the paper matrix |

## A note on history

The LLM suite changed epochs on 2026-08-05: prompts stopped being lowercased, pass criteria
gained pinned arguments and outcome grading of the saved artifact, retries were fixed at 0, and a
second vendor (Codex) was added. Pass rates from before that date (the 44% → 95% climb in
`plots/run_history.png`) measured tool *routing* only and are not comparable with the
outcome-graded numbers above. This file used to be the routing-era technical report; that
material now lives in the historical sections of `llm-test-benchmark.md` and
`llm-testing-methodology.md`.
