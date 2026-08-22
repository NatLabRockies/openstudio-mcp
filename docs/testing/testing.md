# Testing Guide

## Overview

**1,169 tests across 114 files** (measured 2026-08-22), split into two categories, plus the
LLM agent suite in `tests/llm/` (259 tests, local only; see the end of this guide):

| Category | Count | Requires Docker | Marker |
|----------|-------|-----------------|--------|
| Integration | 663 | Yes | `@pytest.mark.integration` |
| Unit | 506 | No | (none; select with `-m "not integration"`) |

CI runs the integration suite as 5 parallel amd64 shards (12-14 min each) plus 2 arm64 shards;
see "CI Pipeline" below.

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

This pattern appears in essentially every integration test (663 at last count). Key points:
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

### Multi-user isolation tests

Any per-user storage helper (`user_run_root`, `user_measures_root`, …) or path-scope
decision (`is_path_allowed`) needs an isolation test — this is a top-priority security
invariant (see [security-isolation.md](../security-isolation.md)). Drive two
identities by monkeypatching identity, and assert:

- two distinct `user_key`s yield **disjoint, non-nested** paths, and
- `is_path_allowed` **denies** a cross-tenant path (read AND write).

```python
monkeypatch.setattr("mcp_server.identity.user_key", lambda: "alice")
```

This is the test class that would have caught a per-user store silently collapsing to
a shared dir. Examples: `test_measure_isolation.py` (unit), and the two-HTTP-session
checks in `test_session_isolation.py` / `test_measure_discovery.py` (integration).

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

### Jobs (`.github/workflows/ci.yml`, plus `security.yml`)

| Job | What it does | Duration (last green `develop` run) |
|---|---|---|
| `build` | Docker image with GHA buildx cache, sanity checks, unit tests (`pytest -m "not integration"`), saves the image artifact, pushes to Docker Hub | ~9 min |
| `test` (matrix: shard 1-5) | loads the image, runs that shard's `FILES=` list with `RUN_OPENSTUDIO_INTEGRATION=1` and `OSMCP_SANDBOX=auto`; `fail-fast: false` so one shard failure doesn't cancel the others | 12-14 min each |
| `arm64-build` / `arm64-test` (shards 1-2) | arm64 image from `docker/Dockerfile.arm64`; shard 1 runs the core real-simulation subset of amd64 shard 1, while shard 2 is the arch-sensitive set (SWIG memleak, stdout logger, measures, measure authoring, HVAC supply sim) | ~3 min / 5-6 min |
| `security.yml` (separate workflow) | `tests/test_sandbox.py` under `OSMCP_SANDBOX=auto` on amd64 and arm64 | — |

### Shard assignment

Each amd64 shard has a `FILES=` list in a `case` block. Files are hand-assigned to keep the five
shards within about a minute of each other; a few very slow gbXML tests are split out by node id.
The comments above each `case` block in `ci.yml` are the authoritative map. In summary:

| Shard | Focus |
|-------|-------|
| 1 | SEB4 simulation + EUI pin, component properties, weather, ComStock, loop operations, retrofit skill, load/save + file listing |
| 2 | common measures, HVAC baseline systems, geometry, zone terminals, energy-report skill, HTTP transport / session isolation / auth, measure discovery + BCL, python EMS, outcome grader |
| 3 | controls, object management, generic access, loads, building, DOAS, air/plant loops, measures, measure authoring, QA/QC skill, HVAC supply wiring, geometry write guards |
| 4 | VRF, radiant, query and creation tools, air terminals, results extraction, gbXML import, validate_osw / run_osw |
| 5 | HVAC supply simulation smoke, HVAC validation, bar building, concurrency, stdout-logger silence, sim queue, per-user isolation, run retention, python EMS phase 2 |

### Adding new tests to CI

Append the new test file to the lightest shard's `FILES=` list (check recent shard durations in
the Actions tab; `pytest --durations=0` inside the container helps). New tests inside an existing
file ride along with that file.

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
| `OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS` | `1800` | Wall-clock cap on the gbXML measure workflow (`0` or negative = no cap) |

**Slow hosts and the gbXML fixtures.** `import_gbxml`'s runtime is almost entirely one measure's
single-threaded surface matching (`gbxml_import_advanced`), so it tracks per-core speed and core
count buys nothing. On the Austin apartment fixture that is ~300s on 2-core CI runners, ~160s on a
fast dev box, and ~8.5 min on a slower one — where the previous hardcoded 600s cap killed the
import mid-measure and failed
`test_gbxml_import.py::test_geometry_repair_pipeline_on_austin_apartment_fixture` with
`gbXML import exceeded the 600s wall-clock cap`.

Contention matters as much as the host: on that same machine the import took 622-687s run on its
own but **1228s** when the rest of `tests/test_gbxml_import.py` ran alongside it in one container.
CI does not hit this because the heavy gbXML tests are split across shards by node ID, but a local
whole-file run does. If you hit it, raise the cap rather than assuming the test is broken:

```bash
docker run --rm -v "C:/OS_MCP:/repo" -v "C:/OS_MCP/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 -e MCP_SERVER_CMD=openstudio-mcp \
  -e OSMCP_GBXML_IMPORT_TIMEOUT_SECONDS=2400 \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_gbxml_import.py"
```

A timeout error always names both the cap in force and this variable, so it can be acted on
without reading the source.

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

End-to-end tests in which a real agent CLI (Claude Code for Claude models, Codex for GPT models)
reads a natural-language prompt, connects to the openstudio-mcp Docker server over MCP, and has
to pick and call the right tools; for the benchmark's hard tasks the model it saves is also
graded. They run **locally only** (`LLM_TESTS_ENABLED=1`), never in CI, because they need an
authenticated agent CLI and the full suite takes hours.

Everything about this suite — harness architecture, the L1/L2/L3 progressive pattern, the two
grading gates, assistance arms, providers, environment knobs, benchmark sweeps — lives in
[`llm-testing-methodology.md`](llm-testing-methodology.md); current numbers are in
[`llm-test-benchmark.md`](llm-test-benchmark.md). The short version:

```bash
# Prerequisites: openstudio-mcp:dev built; `claude` (and `codex` for GPT legs) installed and logged in
LLM_TESTS_ENABLED=1 pytest tests/llm/ -m smoke -v                                  # 12 tests, ~10 min
LLM_TESTS_ENABLED=1 pytest tests/llm/test_06_progressive.py -k thermostat_L1 -v    # one case
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v                                           # all 259, hours
```

Defaults worth knowing: `LLM_TESTS_RETRIES=0` (benchmark runs use repeats, not retries),
`LLM_TESTS_MAX_PROMPTS=300` (hard cap on agent invocations per session),
`LLM_TESTS_MODEL=sonnet`, `LLM_TESTS_TIMEOUT_BASE=120` seconds per task. Per-run reports land in
`$LLM_TESTS_RUNS_DIR/benchmark.md` and `benchmark.json`.

Two gotchas that bite everyone once: Claude output must be requested as
`--output-format stream-json --verbose` (plain `json` drops the `tool_use` blocks), and the
harness strips the `CLAUDECODE` environment variable because a nested `claude -p` refuses to
start if it inherits it.
