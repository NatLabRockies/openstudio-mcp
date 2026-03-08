# Testing Guide

## Overview

**~468 tests across 60 files**, split into two categories:

| Category | Count | Requires Docker | Marker |
|----------|-------|-----------------|--------|
| Integration | 317 | Yes | `@pytest.mark.integration` |
| Unit | 151 | No | (none) |

CI runs 5 parallel shards, each ~200s. Total wall time ~6 min.

---

## Quick Start

### Unit tests (no Docker)

```bash
pytest tests/test_skill_registration.py tests/test_skill_tools.py tests/test_contract.py -v
```

### Integration tests (Docker)

Build the image, then run tests inside a single container:

```bash
docker build -f docker/Dockerfile -t openstudio-mcp:dev .

docker run --rm \
  -v "C:/projects/openstudio-mcp:/repo" \
  -v "C:/projects/openstudio-mcp/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 \
  -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_building.py"
```

Run all tests:

```bash
docker run --rm \
  -v "C:/projects/openstudio-mcp:/repo" \
  -v "C:/projects/openstudio-mcp/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 \
  -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_*.py"
```

---

## Test Architecture

### How tests talk to the MCP server

Every integration test spawns an MCP server subprocess via `stdio_client`, connects over stdin/stdout JSON-RPC, and calls tools through the MCP SDK:

```python
@pytest.mark.integration
def test_something():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resp = await session.call_tool("get_model_summary", {})
                result = unwrap(resp)
                assert result.get("ok") is True

    asyncio.run(_run())
```

This pattern appears in 376 tests. Key points:
- `server_params()` reads `MCP_SERVER_CMD` / `MCP_SERVER_ARGS` env vars to build the subprocess command
- `unwrap()` extracts JSON from the MCP `CallToolResult` envelope
- Each test gets its own server subprocess (isolated state)

### conftest.py helpers

| Helper | Purpose |
|--------|---------|
| `integration_enabled()` | Check `RUN_OPENSTUDIO_INTEGRATION` env var |
| `server_params()` | Build `StdioServerParameters` from env vars |
| `unwrap(res)` | Extract dict from MCP `CallToolResult` |
| `poll_until_done(session, run_id)` | Poll `get_run_status` until terminal state |
| `create_and_load(session, name)` | `create_example_osm` + `load_osm_model`, return zone names |
| `create_baseline_and_load(session, name)` | Same with 10-zone baseline model |
| `setup_example(session, name)` | Create + load in one call |

### Unique name generation

Tests generate unique model names to avoid collisions in parallel runs:

```python
def _unique_name(prefix: str = "pytest_building") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"
```

---

## Test Categories

### Integration tests

Require Docker with OpenStudio SDK. Each test:
1. Spawns an MCP server subprocess
2. Creates/loads a model via MCP tools
3. Calls the tool under test
4. Asserts on the JSON response

Marked with `@pytest.mark.integration` (individual) or module-level `pytestmark`.

**Examples:**
- `test_building.py` — `get_building_info`, `get_model_summary`, conditioned floor area
- `test_hvac_systems.py` — ASHRAE baseline systems 1-10
- `test_common_measures.py` — view_model, thermostat, envelope, PV measures
- `test_mcp_seb4.py` — Full simulation + results extraction

### Unit tests

Pure Python, no Docker or OpenStudio required.

**Examples:**
- `test_skill_registration.py` — Verify all skills register tools on a mock MCP
- `test_skill_tools.py` — SKILL.md frontmatter parsing
- `test_path_safety.py` — Path traversal guards (monkeypatched)
- `test_contract.py` — JSON schema validation
- `test_stdio_smoke.py` — Raw JSON-RPC protocol (no SWIG warnings on stdout)

### Simulation tests

Long-running tests that run full EnergyPlus simulations. Use polling:

```python
sim = unwrap(await session.call_tool("run_simulation", {
    "osm_path": osm_path, "epw_path": EPW_PATH,
}))
status = await poll_until_done(session, sim["run_id"])
assert status["run"]["status"] == "success"
```

**Timeouts:** Default 1200s (20 min), override via `MCP_SIM_TIMEOUT` env var.

---

## CI Pipeline

### Two-job strategy (`.github/workflows/ci.yml`)

**Job 1: Build**
- Builds Docker image with GHA buildx cache
- Runs unit tests (`pytest -m "not integration"`)
- Saves image as artifact for test shards

**Job 2: Test** (matrix: shard 1-5)
- Downloads Docker image artifact
- Runs assigned integration test files inside the container
- `fail-fast: false` — one shard failure doesn't cancel others

### Shard assignment

Each shard has a `FILES=` list in a `case` block. Tests are distributed to keep shards roughly balanced at ~200s each.

| Shard | Focus | ~Duration |
|-------|-------|-----------|
| 1 | Simulation, component props, weather, ComStock | ~200s |
| 2 | Common measures, HVAC systems, geometry | ~200s |
| 3 | Controls, object mgmt, loads, building | ~200s |
| 4 | Query skills, creation tools, results | ~200s |
| 5 | HVAC supply wiring simulation (5 smoke tests) | ~200s |

### Adding new tests to CI

Append the new test file to the lightest shard's `FILES=` list in the `case` block. Keep shards roughly balanced.

---

## Docker Setup

### Base image

`nrel/openstudio:3.11.0` — includes OpenStudio SDK, EnergyPlus, Ruby.

### Bundled measures

| Measure set | Tag | Container path |
|-------------|-----|----------------|
| ComStock measures | `2025-3` | `/opt/comstock-measures` |
| Common measures gem | `v0.12.3` | `/opt/common-measures` |

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RUN_OPENSTUDIO_INTEGRATION` | (unset) | Set to `1` to enable integration tests |
| `MCP_SERVER_CMD` | (required) | Server command (`openstudio-mcp` or `docker`) |
| `MCP_SERVER_ARGS` | (optional) | Additional args for server command |
| `OSMCP_RUN_ROOT` | `/runs` | Where models and sim outputs are stored |
| `OSMCP_MAX_CONCURRENCY` | `1` | Max concurrent simulations |
| `MCP_SIM_TIMEOUT` | `1200` | Simulation poll timeout (seconds) |
| `MCP_POLL_SECONDS` | `3.0` | Poll interval for simulation status |

### Two execution modes

**1. In-container (CI default, fastest)**

Tests run inside the same Docker container as the MCP server. Server is spawned as a subprocess via `MCP_SERVER_CMD=openstudio-mcp`.

**2. Spawn-per-test (Windows dev fallback)**

Each test spawns a new Docker container for the MCP server:

```bash
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" \
  RUN_OPENSTUDIO_INTEGRATION=1 \
  MCP_SERVER_CMD=docker \
  MCP_SERVER_ARGS="run --rm -i -v /c/projects/openstudio-mcp/runs:/runs ..." \
  pytest -vv tests/test_building.py
```

Slower (~14 min vs ~9 min for full suite) but works on Windows without running pytest inside Docker.

---

## Example Tests (Annotated)

### Example 1: Simple query tool (`test_building.py`)

Tests `get_model_summary` — a read-only tool that returns object counts.

```python
@pytest.mark.integration                          # 1. Mark as integration test
def test_get_model_summary():
    if not integration_enabled():                  # 2. Skip if env var not set
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name()                          # 3. Unique name avoids collisions

    async def _run():                              # 4. Async wrapper (MCP SDK is async)
        # 5. Spawn MCP server subprocess, connect via stdin/stdout
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()         # 6. MCP handshake

                # 7. Setup: create a model to query
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)        # 8. Extract JSON from MCP envelope
                assert create_result.get("ok") is True

                # 9. Load model into server memory
                load_resp = await session.call_tool("load_osm_model",
                    {"osm_path": create_result["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                # 10. Call the tool under test
                summary_resp = await session.call_tool("get_model_summary", {})
                summary = unwrap(summary_resp)

                # 11. Assertions — always include result as context for failures
                assert summary.get("ok") is True, summary
                assert summary["summary"]["spaces"] == 4
                assert summary["summary"]["thermal_zones"] == 1

    asyncio.run(_run())                            # 12. Run the async function
```

**What's happening:** Each test spawns its own MCP server process via `stdio_client`.
The server lives for the duration of the `async with` block, so model state is
isolated per test. `unwrap()` handles the MCP protocol envelope — you get back
the same dict that the tool's `operations.py` function returned.

### Example 2: Tool that modifies the model (`test_hvac_systems.py`)

Tests `add_baseline_system` — creates HVAC equipment on the model.

```python
@pytest.mark.integration
def test_add_baseline_system_3():
    """System 3 (PSZ-AC) should create one air loop per zone."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_sys3")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Use conftest helper — creates 10-zone baseline, returns zone names
                zones = await create_baseline_and_load(session, name)

                # Add HVAC system to all zones
                resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": zones,
                })
                result = unwrap(resp)
                assert result.get("ok") is True, result

                # Verify: PSZ-AC creates one air loop per zone
                loops = unwrap(await session.call_tool("list_air_loops", {}))
                assert loops["count"] == len(zones)

    asyncio.run(_run())
```

**Key pattern:** Use `create_baseline_and_load()` from conftest when you need a
10-zone model with constructions and thermostats. Use `create_and_load()` for a
simpler 4-space example model.

### Example 3: Simulation + results extraction (`test_mcp_seb4.py`)

Tests a full simulate-then-extract workflow with polling.

```python
@pytest.mark.integration
def test_seb4_simulation():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Start simulation (returns immediately)
                sim = unwrap(await session.call_tool("run_simulation", {
                    "osm_path": "/inputs/SEB_model/SEB4_baseboard/SEB4.osm",
                    "epw_path": EPW_PATH,
                }))
                assert sim.get("ok") is True

                # Poll until done (timeout from MCP_SIM_TIMEOUT, default 20min)
                status = await poll_until_done(session, sim["run_id"])
                assert status["run"]["status"] == "success"

                # Extract results from completed run
                metrics = unwrap(await session.call_tool("extract_summary_metrics", {
                    "run_id": sim["run_id"],
                }))
                assert metrics.get("ok") is True
                assert metrics["eui_MJ_m2"] > 0

    asyncio.run(_run())
```

**Key pattern:** `run_simulation` is non-blocking — it returns a `run_id`
immediately. Use `poll_until_done()` from conftest to wait for completion.
The poller checks `get_run_status` every 3 seconds.

### Example 4: Error handling test (`test_building.py`)

Tests that tools fail gracefully when no model is loaded.

```python
@pytest.mark.integration
def test_building_tools_without_loaded_model():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Call tool WITHOUT loading a model first
                resp = await session.call_tool("get_building_info", {})
                result = unwrap(resp)

                # Should fail gracefully, not crash
                assert result.get("ok") is False
                assert "error" in result
                assert "no model loaded" in result["error"].lower()

    asyncio.run(_run())
```

**Key pattern:** Every tool must return `{"ok": False, "error": "..."}` on
failure — never raise exceptions through MCP. Test both happy path and error
cases.

### Example 5: Unit test — no Docker (`test_skill_tools.py`)

Tests SKILL.md frontmatter parsing. Pure Python, runs anywhere.

```python
def test_list_skills_returns_all():
    """list_skills should find all SKILL.md files."""
    from mcp_server.skills.skill_discovery.operations import list_skills_op

    result = list_skills_op()
    assert result["ok"] is True
    assert result["count"] > 0
    # Every skill should have name and description
    for skill in result["skills"]:
        assert "name" in skill
        assert "description" in skill
```

**Key pattern:** No `@pytest.mark.integration`, no `integration_enabled()` check,
no `stdio_client`. Import the operation function directly and call it. These
tests run in CI's build job before Docker image is shared to shards.

---

## Writing New Tests

### Step-by-step

1. **Create test file** in `tests/` named `test_<feature>.py`
2. **Copy the boilerplate** — imports, `_unique_name()`, `@pytest.mark.integration`
3. **Choose a setup helper:**
   - `create_and_load(session, name)` — simple 4-space model
   - `create_baseline_and_load(session, name)` — 10-zone model with constructions/thermostats
   - Or call `create_baseline_osm` / `create_example_osm` directly for custom args
4. **Call your tool** via `session.call_tool("tool_name", {args})`
5. **Assert on the result** — always include the result dict as assert context
6. **Add to CI** — append the file to the lightest shard in `.github/workflows/ci.yml`

### Template

```python
import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_myfeature") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_my_tool_happy_path():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                cr = await session.call_tool("create_example_osm", {"name": name})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd

                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr).get("ok") is True

                resp = await session.call_tool("my_tool", {"param": "value"})
                result = unwrap(resp)
                print("my_tool:", result)

                assert result.get("ok") is True, result
                assert result["expected_key"] == "expected_value"

    asyncio.run(_run())
```

### Conventions

- One `_unique_name()` per test file with a descriptive prefix
- Always assert `ok is True` with the full result as context: `assert ok, data`
- Print results for debugging: `print("my_tool:", result)`
- Use conftest helpers (`create_and_load`, `create_baseline_and_load`) for common setup
- Test both happy path AND error cases (no model loaded, invalid args)
- Add the test file to the lightest CI shard in `ci.yml`

---

## LLM Agent Tests (`tests/llm/`)

End-to-end tests that send natural language prompts to a real LLM (via Claude Code CLI), connected to a real openstudio-mcp server, and verify the agent uses the right tools. These run **locally only** — not in CI.

### Why

Integration tests verify tools work in isolation. LLM tests verify an agent, given a natural language prompt, discovers and uses the correct tools in the correct order. This catches failures like the agent bypassing MCP tools to write raw IDF files by hand.

### Architecture

```
pytest  -->  claude -p "prompt" --mcp-config mcp.json
                  |
                  v
             Claude Code CLI (the agent)
                  |
                  v
             openstudio-mcp Docker container (stdio)
```

The test harness:
1. Writes a temporary MCP config pointing at the Docker server
2. Runs `claude -p "prompt" --output-format stream-json --verbose --mcp-config mcp.json`
3. Parses the NDJSON stream for tool_use blocks
4. Asserts on tool names, parameters, and optionally final response text

### Prerequisites

- **Claude Code CLI** (`claude`) installed and authenticated (Claude Max subscription — no API charges)
- **Docker** with `openstudio-mcp:dev` image built
- **`LLM_TESTS_ENABLED=1`** environment variable

### Running

```bash
# All LLM tests (~46 tests, ~15 min)
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v

# Specific tier only
LLM_TESTS_ENABLED=1 LLM_TESTS_TIER=1 pytest tests/llm/ -v

# Different model
LLM_TESTS_ENABLED=1 LLM_TESTS_MODEL=haiku pytest tests/llm/ -v
```

### Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_TESTS_ENABLED` | (unset) | Set to `1` to enable LLM tests |
| `LLM_TESTS_MAX_PROMPTS` | `50` | Hard cap on Claude invocations per run |
| `LLM_TESTS_MODEL` | `sonnet` | Model: `sonnet`, `haiku`, or `opus` |
| `LLM_TESTS_TIER` | `all` | `1`, `2`, `3`, `4`, or `all` |
| `LLM_TESTS_RETRIES` | `2` | Retry count for non-deterministic failures |
| `LLM_TESTS_RUNS_DIR` | `/tmp/llm-test-runs` | Host path for Docker `/runs` mount |

### Test Tiers

| Tier | Tests | Description | ~Time |
|------|-------|-------------|-------|
| **1: Tool Selection** | ~41 | Single prompt, check which tool is called first | ~10 min |
| **2: Workflows** | 2 | Multi-step (create building + add HVAC, create + weather) | ~4 min |
| **3: E2E** | — | Full simulate + extract results (future) | — |
| **4: Guardrails** | 3 | Agent must NOT bypass MCP (no raw IDF, no scripts) | ~2 min |

### Test Structure

**Tier 1** tests are parametrized from two sources:
- `TOOL_SELECTION_CASES` in `test_tool_selection.py` — hand-curated prompts
- `eval.md` files in `.claude/skills/*/eval.md` — auto-parsed via `test_eval_tool_selection.py`

```python
TOOL_SELECTION_CASES = [
    ("Create a 10-zone office building", ["create_baseline_osm"]),
    ("Add DOAS with fan coils", ["add_doas_system"]),
    ("Show me a 3D view", ["view_model"]),
]

@pytest.mark.parametrize("prompt,expected", TOOL_SELECTION_CASES)
def test_tool_selection(prompt, expected):
    output = run_claude(prompt, timeout=90)
    tool_names = extract_tool_names(output)
    first = _first_non_skill_tool(tool_names)
    assert first in expected
```

**Tier 4** (guardrail) tests verify the agent doesn't use `Write`, `Bash`, or `Edit` tools when asked to create a building — it must use MCP tools.

### Retry Logic

LLM outputs are non-deterministic. The conftest implements a custom `pytest_runtest_protocol` hook that retries failed LLM tests up to `LLM_TESTS_RETRIES` times. If any attempt passes, the test is reported as passed. Each retry consumes a prompt from the budget.

### Key Files

| File | Purpose |
|------|---------|
| `tests/llm/runner.py` | `run_claude()`, `extract_tool_calls()`, MCP config generation |
| `tests/llm/conftest.py` | Guards, budget, retry hook, shared model paths |
| `tests/llm/test_tool_selection.py` | Tier 1 — hand-curated tool selection cases |
| `tests/llm/test_eval_tool_selection.py` | Tier 1 — auto-parsed from eval.md files |
| `tests/llm/test_workflows.py` | Tier 2 — multi-step workflows |
| `tests/llm/test_guardrails.py` | Tier 4 — agent must not bypass MCP |

### Known Behaviors

- **ToolSearch consumes 1-3 turns** — Claude Code uses deferred tool loading, so the agent spends turns discovering MCP tools before calling them. Don't set `--max-turns` too low.
- **Context-gathering is normal** — the agent often calls `get_model_summary`, `list_spaces`, etc. before the target tool. Assert "tool appears anywhere", not "tool is first call".
- **Action tools need model state** — prompts like "add VRF" fail if no model exists. Tier 1 tests should target query/info tools; action tests belong in Tier 2 with model creation in the prompt.
- **`stream-json` + `--verbose` required** — `--output-format json` only returns the final text result; `stream-json --verbose` includes tool_use blocks.
- **`CLAUDECODE` env var must be stripped** — nested `claude -p` subprocess calls fail if the parent session's `CLAUDECODE` env var is inherited.
