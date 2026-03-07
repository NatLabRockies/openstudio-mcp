# LLM Agent Testing for openstudio-mcp

## Problem

openstudio-mcp exposes 127 tools to LLM agents, but CI only tests tools in isolation. No automated way to verify that an LLM agent, given a natural language prompt, uses the right tools in the right order and produces a valid model. We saw this failure firsthand: agent bypassed all MCP tools and wrote raw IDF by hand.

We need local tests that send real prompts to Claude, connected to a real openstudio-mcp server, and verify the agent behaves correctly end-to-end. These run locally only — no CI integration for now.

---

## Architecture

Uses **Claude Code CLI** (`claude -p`) instead of the Anthropic API. Claude Max subscription covers all usage — no per-token API charges.

```
┌──────────────────────────────────────────────────────────┐
│  Test Harness (pytest)                                    │
│                                                           │
│  ┌──────────────────┐     ┌────────────────────────────┐  │
│  │ subprocess:       │     │  openstudio-mcp server     │  │
│  │ claude -p          │◀──▶│  (Docker, stdio transport) │  │
│  │ --mcp-config ...  │     │  connected via mcp.json    │  │
│  │ --output-format   │     └────────────────────────────┘  │
│  │   json            │                                     │
│  └────────┬─────────┘                                     │
│           │ JSON output                                    │
│           ▼                                                │
│  ┌──────────────────┐                                     │
│  │ Assertions        │                                     │
│  │ (tool trace,      │                                     │
│  │  final text,      │                                     │
│  │  model state)     │                                     │
│  └──────────────────┘                                     │
└──────────────────────────────────────────────────────────┘
```

**Key:** Claude Code CLI IS the agent. The test harness:
1. Starts openstudio-mcp Docker container (or reuses a running one)
2. Writes an MCP config JSON pointing at the server
3. Runs `claude -p "prompt" --output-format json --mcp-config mcp.json`
4. Claude Code connects to the MCP server, discovers tools, and executes them autonomously
5. Test parses the JSON output for tool calls and final response
6. Asserts on tool names, parameters, and optionally queries model state afterward

**Why Claude Code CLI over Anthropic API?**
- No API charges — covered by Claude Max subscription
- No custom agent loop to maintain — Claude Code handles tool discovery, execution, retries
- Matches real-world usage (users run Claude Code with MCP servers)
- Built-in MCP protocol support (no manual tool format conversion)

---

## What We Already Have

| Asset | Status |
|---|---|
| `tests/eval_tool_selection.py` — keyword-based tool matching (60 cases) | Done, no LLM |
| 8 `eval.md` files — should/should-not trigger tables per skill | Done |
| Manual claude.ai tests — 2 sessions, all passing | Done |
| Agent guardrails — MCP instructions, tool descriptions, skill dedup | Done |
| Integration test infra — conftest helpers, Docker stdio transport | Done |
| Tool description gotcha hints (simulation, weather, HVAC) | Done |

---

## Claude Code CLI Flags

| Flag | Purpose |
|---|---|
| `-p "prompt"` | Non-interactive mode, single prompt |
| `--output-format stream-json` | NDJSON stream with tool_use blocks (json only returns final result) |
| `--mcp-config <file>` | MCP server configuration |
| `--model sonnet` | Model selection (sonnet, haiku, opus) |
| `--dangerously-skip-permissions` | No interactive permission prompts |
| `--no-session-persistence` | Don't save session state |
| `--allowedTools "mcp__openstudio__*"` | Restrict to MCP tools only |
| `--max-budget-usd <n>` | Cost safety cap per invocation |

---

## MCP Config

The test harness generates a temporary `mcp.json` pointing at the Docker server:

```json
{
  "mcpServers": {
    "openstudio": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/tmp/llm-test-runs:/runs",
        "-e", "OPENSTUDIO_MCP_MODE=prod",
        "openstudio-mcp:dev",
        "openstudio-mcp"
      ]
    }
  }
}
```

Claude Code spawns the Docker container via stdio transport, same as our integration tests.

---

## Test Runner

```python
# tests/llm/runner.py
import json
import subprocess
import tempfile
from pathlib import Path

def run_claude(
    prompt: str,
    model: str = "sonnet",
    timeout: int = 120,
    allowed_tools: str = "mcp__openstudio__*",
) -> dict:
    """Run Claude Code CLI with MCP and return parsed JSON output."""

    mcp_config = _write_mcp_config()

    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--mcp-config", str(mcp_config),
        "--model", model,
        "--dangerously-skip-permissions",
        "--no-session-persistence",
        "--allowedTools", allowed_tools,
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout,
    )

    if result.returncode != 0:
        raise RuntimeError(f"claude failed: {result.stderr}")

    return json.loads(result.stdout)


def extract_tool_calls(output: dict) -> list[dict]:
    """Extract tool call names and inputs from Claude Code JSON output."""
    # Claude Code JSON output format includes tool_use content blocks
    calls = []
    for msg in output.get("messages", []):
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append({
                        "tool": block["name"],
                        "input": block.get("input", {}),
                    })
    return calls


def _write_mcp_config() -> Path:
    """Write temporary MCP config for Docker stdio transport."""
    config = {
        "mcpServers": {
            "openstudio": {
                "command": "docker",
                "args": [
                    "run", "--rm", "-i",
                    "-v", "/tmp/llm-test-runs:/runs",
                    "-e", "OPENSTUDIO_MCP_MODE=prod",
                    "openstudio-mcp:dev",
                    "openstudio-mcp",
                ],
            }
        }
    }
    path = Path(tempfile.mkdtemp()) / "mcp.json"
    path.write_text(json.dumps(config))
    return path
```

### Test Structure

```python
# tests/llm/test_workflows.py
import pytest
from runner import run_claude, extract_tool_calls

def llm_enabled():
    return os.environ.get("LLM_TESTS_ENABLED", "").lower() in ("1", "true")

@pytest.mark.llm
def test_create_5zone_vav():
    """Agent should use MCP tools to create a 5-zone office with VAV."""
    if not llm_enabled():
        pytest.skip("Set LLM_TESTS_ENABLED=1")

    output = run_claude(
        "Create a 5-zone office building with VAV reheat. "
        "Use the MCP tools available to you.",
        timeout=180,
    )

    tools = extract_tool_calls(output)
    tool_names = [t["tool"] for t in tools]

    # Must use MCP tools, not write raw files
    assert any(t in tool_names for t in [
        "mcp__openstudio__create_baseline_osm",
        "mcp__openstudio__create_example_osm",
    ]), f"No creation tool called. Tools: {tool_names}"

    # Should use HVAC system tool
    assert "mcp__openstudio__add_baseline_system" in tool_names or \
           any("ashrae_sys_num" in str(t["input"]) for t in tools)

    # Should query skill first
    assert tool_names[0] in (
        "mcp__openstudio__get_skill",
        "mcp__openstudio__list_skills",
    )
```

---

## Test Categories

### Tier 1: Tool Selection (fast, no execution needed)

Single prompt, check which tool Claude picks. Claude Code still connects to the MCP server (needed for tool discovery), but we only care about the first tool call.

```python
TOOL_SELECTION_CASES = [
    ("Create a 10-zone office building", ["create_baseline_osm"]),
    ("Add DOAS with fan coils to all zones", ["add_doas_system"]),
    ("Run a simulation and show me the EUI", ["run_simulation"]),
    ("What's the building floor area?", ["get_building_info", "get_model_summary"]),
    ("Show me a 3D view of the model", ["view_model"]),
]

@pytest.mark.parametrize("prompt,expected", TOOL_SELECTION_CASES)
@pytest.mark.llm
def test_tool_selection(prompt, expected):
    if not llm_enabled():
        pytest.skip("Set LLM_TESTS_ENABLED=1")

    output = run_claude(prompt, timeout=60)
    tools = extract_tool_calls(output)

    # First tool call (after optional skill lookup) should match
    non_skill_tools = [
        t["tool"].replace("mcp__openstudio__", "")
        for t in tools
        if "skill" not in t["tool"]
    ]
    assert non_skill_tools[0] in expected, \
        f"Expected {expected}, got {non_skill_tools[0]}"
```

### Tier 2: Multi-Step Workflows (moderate, ~60-120s)

Full agentic workflow with tool execution. Verify tool sequence and optionally query model state afterward.

```python
WORKFLOW_CASES = [
    {
        "prompt": "Create a 5-zone office with VAV reheat",
        "required_tools": ["create_baseline_osm", "add_baseline_system"],
        "forbidden_tools": [],
    },
    {
        "prompt": "Create a building and set the weather to Chicago",
        "required_tools": ["create_baseline_osm", "set_weather_file"],
    },
]
```

### Tier 3: End-to-End Simulation (expensive, ~5min)

Full workflow including simulation. Run sparingly.

```python
E2E_CASES = [
    {
        "prompt": (
            "Create a 5-zone office in Golden CO with System 7 VAV reheat. "
            "Run a simulation and report the EUI."
        ),
        "required_tools": [
            "create_baseline_osm", "add_baseline_system",
            "set_weather_file", "run_simulation", "extract_summary_metrics",
        ],
        "timeout": 600,
    },
]
```

### Tier 4: Guardrail Regression

Verify the agent does NOT bypass MCP tools.

```python
GUARDRAIL_CASES = [
    {
        "prompt": "Create a simple office building model",
        "forbidden_behaviors": [
            # Check final output text for signs of raw file writing
            lambda output: "idf" not in output.get("result", "").lower(),
            # Check no bash/write tool calls
            lambda tools: not any("Write" in t["tool"] for t in tools),
        ],
    },
]
```

---

## eval.md Integration

The 8 existing `eval.md` files have should-trigger/should-not-trigger tables. These can be auto-parsed into Tier 1 test cases:

```python
def load_eval_cases() -> list[dict]:
    """Parse eval.md files into test cases."""
    cases = []
    for eval_md in Path(".claude/skills").rglob("eval.md"):
        skill_name = eval_md.parent.name
        # parse should-trigger table rows into tool selection cases
        # parse should-not-trigger rows into guardrail cases
        ...
    return cases
```

---

## Cost & Resource Controls

### No API Charges

Claude Code CLI with Max subscription = no per-token charges. Only cost is Docker compute time (~$0 locally).

### Kill Switch

```python
def llm_enabled() -> bool:
    return os.environ.get("LLM_TESTS_ENABLED", "").lower() in ("1", "true")
```

### Budget Cap

Claude Code CLI supports `--max-budget-usd` as a safety valve, though Max subscription means no actual charges.

### Test Count Guard

```python
MAX_PROMPTS = int(os.environ.get("LLM_TESTS_MAX_PROMPTS", "20"))
_prompt_count = 0

@pytest.fixture(autouse=True)
def llm_budget_guard():
    global _prompt_count
    _prompt_count += 1
    if _prompt_count > MAX_PROMPTS:
        pytest.skip(f"Budget exhausted ({MAX_PROMPTS} max)")
```

### Running Locally

```bash
# Build Docker image first
docker build -f docker/Dockerfile -t openstudio-mcp:dev .

# Run all LLM tests
LLM_TESTS_ENABLED=1 pytest tests/llm/ -v -m llm

# Run specific tier
LLM_TESTS_ENABLED=1 LLM_TESTS_TIER=1 pytest tests/llm/ -v -m llm

# Use a different model
LLM_TESTS_ENABLED=1 LLM_TESTS_MODEL=haiku pytest tests/llm/ -v -m llm
```

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `LLM_TESTS_ENABLED` | (unset) | Set to `1` to enable LLM tests |
| `LLM_TESTS_MAX_PROMPTS` | `20` | Hard cap on Claude invocations per run |
| `LLM_TESTS_MODEL` | `sonnet` | Model to test with (sonnet/haiku/opus) |
| `LLM_TESTS_TIER` | `all` | `1`, `2`, `3`, or `all` |

### Estimated Times

| Run Type | Tests | Est. Time |
|---|---|---|
| Tier 1 only (tool selection) | 15-20 | ~5 min |
| Tier 1 + 2 (workflows) | 25-30 | ~15 min |
| Full suite (all tiers) | 35-40 | ~30 min |

---

## Handling Non-Determinism

LLM outputs vary between runs:

1. **Structural assertions** — check tool names and param ranges, not exact text or order
2. **Retry with budget** — run flaky tests up to N times (`LLM_TESTS_RETRIES` env, default 2)
3. **Soft vs hard failures** — tool selection = hard fail, parameter exact values = soft warning
4. **Required vs acceptable** — `required_tools` must all appear; order is flexible unless specified
5. **Multiple models** — same prompts against Sonnet + Haiku; if both fail, it's a tool description issue

### Findings from Local Runs

- **ToolSearch (deferred loading)** consumes 1-3 turns per test; don't set `--max-turns` too low
- **Context-gathering is normal** — agent often calls `get_model_summary`, `list_spaces`, etc. before the target tool. Assert "tool appears anywhere in sequence", not "tool is first call"
- **Action tools need model state** — prompts like "add VRF" fail if no model is loaded. Tier 1 tests should be query/info only; action tests belong in Tier 2 with model creation in the prompt
- **~15s per test** average (Sonnet); retries double this
- **`stream-json` requires `--verbose`** — `json` format only returns final result, no tool_use blocks
- **`CLAUDECODE` env var must be stripped** for nested `claude -p` subprocess calls

---

## Implementation Roadmap

### Phase 1: Runner + Smoke Tests

- [x] Create `tests/llm/` directory structure
- [x] Implement `runner.py` — `run_claude()`, `extract_tool_calls()`, MCP config generation
- [x] Implement `conftest.py` — `llm_enabled()`, test count guard, model selection
- [x] Write 15 Tier 1 tests (tool selection, parametrized)
- [x] Write 2 Tier 2 tests (create building + VAV, create + weather)
- [x] Write 3 guardrail tests (no raw IDF, no IDF in response, no Python scripts)
- [x] Run locally — 9/10 Tier 1 passing; ~15s/test; key findings below
- [x] Validate output format — `json` returns only final result; switched to `stream-json` for tool_use blocks

### Phase 2: eval.md Integration + Retry Logic

- [x] Build eval.md parser → 26 Tier 1 test cases from 8 skill evals (2 wildcard filtered)
- [x] Add retry logic — pytest hook retries failed LLM tests up to N times (LLM_TESTS_RETRIES env)

### Phase 2.5: JSON-String List Parameter Fix

Some MCP clients (including Claude Code) serialize array parameters as JSON
strings (`"[\"zone1\"]"`) instead of native JSON arrays (`["zone1"]`). Pydantic
rejects these at validation time before the tool function runs.

**Fix pattern:** Change `list[str]` → `Union[list[str], str]` in tool signature,
then call `_parse_str_list(value)` in the tool body to coerce strings to lists.

**Status:** Fixed for `add_baseline_system` only. 8 more tool params need the
same fix. Move `_parse_str_list` to a shared helper (e.g. `osm_helpers.py`).

| Tool | Param | Skill | Status |
|---|---|---|---|
| `add_baseline_system` | `thermal_zone_names` | hvac_systems | ✅ Fixed |
| `add_doas_system` | `thermal_zone_names` | hvac_systems | ✅ Fixed |
| `add_vrf_system` | `thermal_zone_names` | hvac_systems | ✅ Fixed |
| `add_radiant_system` | `thermal_zone_names` | hvac_systems | ✅ Fixed |
| `add_air_loop` | `thermal_zone_names` | hvac | ✅ Fixed |
| `create_construction` | `material_names` | constructions | ✅ Fixed |
| `create_thermal_zone` | `space_names` | spaces | ✅ Fixed |
| `view_simulation_data` | `variable_names` | common_measures | ✅ Fixed |
| `run_qaqc_checks` | `checks` | common_measures | ✅ Fixed |

All 9 tools fixed. `parse_str_list()` moved to `osm_helpers.py` as shared helper.
9 integration tests added (all passing), one per tool.

### Phase 3: E2E + Multi-Model

- [ ] Add Tier 3 E2E tests (simulate + extract results)
- [ ] Add multi-model comparison (Sonnet vs Haiku vs Opus on same prompts)
- [ ] A/B test tool descriptions (which wording leads to better selection?)

---

## Open Questions

1. ~~**`--output-format json` schema**~~ — RESOLVED: `json` only returns final result; use `stream-json --verbose` for tool_use blocks.
2. ~~**MCP tool name prefixing**~~ — RESOLVED: prefix is `mcp__openstudio__<tool>`, matching config key.
3. **Concurrent invocations** — can we run multiple `claude -p` in parallel? Each spawns its own Docker container via MCP config, so state isolation should work.
4. ~~**`--allowedTools` granularity**~~ — RESOLVED: `mcp__openstudio__*` wildcard works.
