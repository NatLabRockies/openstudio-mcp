# LLM-in-the-Loop CI Testing for openstudio-mcp

## Problem

openstudio-mcp exposes 127 tools to LLM agents, but CI only tests tools in isolation. No automated way to verify that an LLM agent, given a natural language prompt, uses the right tools in the right order and produces a valid model. We saw this failure firsthand: agent bypassed all MCP tools and wrote raw IDF by hand.

We need CI tests that send real prompts to Claude, connected to a real openstudio-mcp server, and verify the agent behaves correctly end-to-end.

---

## Architecture

```
┌───────────────────────────────────────────────────────┐
│  Test Harness (pytest)                                │
│                                                       │
│  ┌──────────────┐     ┌───────────────────────────┐   │
│  │ Claude API    │◀───▶│  Anthropic SDK (tool_use) │   │
│  │ (claude-sonnet│     │  agentic loop             │   │
│  │  -4-5, etc.)  │     └──────────┬────────────────┘   │
│  └──────────────┘                │                    │
│                                  │ tool calls         │
│                                  ▼                    │
│  ┌──────────────┐     ┌───────────────────────────┐   │
│  │ Assertions    │◀────│  openstudio-mcp server    │   │
│  │ (tool trace,  │     │  (Docker, stdio transport)│   │
│  │  model state) │     └───────────────────────────┘   │
│  └──────────────┘                                     │
└───────────────────────────────────────────────────────┘
```

**Key:** The test harness IS the agent. It:
1. Spawns openstudio-mcp in Docker via stdio (same as existing integration tests)
2. Fetches tool definitions from the MCP server
3. Converts them to Anthropic tool format
4. Sends the user prompt to Claude API
5. When Claude returns `tool_use`, executes the call against the MCP server
6. Feeds the result back to Claude
7. Repeats until Claude stops calling tools
8. Asserts on the tool call trace and model state

This reuses our existing test infrastructure (`server_params()`, `stdio_client`, `unwrap()`) — we just add Claude as the "brain" driving tool calls instead of hardcoded test logic.

---

## What We Already Have

| Asset | Status |
|---|---|
| `tests/eval_tool_selection.py` — keyword-based tool matching (60 cases) | Done, no LLM |
| 8 `eval.md` files — should/should-not trigger tables per skill | Done |
| Manual claude.ai tests — 2 sessions, all passing | Done |
| Agent guardrails — MCP instructions, tool descriptions, skill dedup | Done |
| Integration test infra — conftest helpers, Docker stdio transport | Done |

---

## Agent Loop Implementation

The core is a minimal agent loop that drives Claude through a multi-turn conversation with tool execution:

```python
# tests/llm/agent_loop.py
import anthropic
from mcp import ClientSession

async def run_agent(
    session: ClientSession,       # MCP connection to openstudio-mcp
    prompt: str,                  # User's natural language request
    model: str = "claude-sonnet-4-5-20250929",
    max_turns: int = 25,
) -> AgentResult:
    """Run Claude as an agent connected to openstudio-mcp.

    Returns AgentResult with full tool call trace and final response.
    """
    client = anthropic.Anthropic()

    # Get tool definitions from MCP server, convert to Anthropic format
    mcp_tools = await session.list_tools()
    tools = [mcp_tool_to_anthropic(t) for t in mcp_tools.tools]

    messages = [{"role": "user", "content": prompt}]
    tool_trace = []  # Record every tool call for assertions

    for turn in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            tools=tools,
            messages=messages,
        )

        # If no tool_use blocks, agent is done
        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        if not tool_use_blocks:
            break

        # Execute each tool call against the real MCP server
        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_use_blocks:
            mcp_result = await session.call_tool(block.name, block.input)
            result_text = unwrap_to_text(mcp_result)
            tool_trace.append({
                "tool": block.name,
                "input": block.input,
                "output": result_text,
                "turn": turn,
            })
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
            })
        messages.append({"role": "user", "content": tool_results})

    return AgentResult(
        tool_trace=tool_trace,
        final_response=response,
        messages=messages,
        turns=turn + 1,
    )
```

### Test Structure

```python
# tests/llm/test_workflows.py
@pytest.mark.llm
def test_create_5zone_vav():
    """Agent should use MCP tools to create a 5-zone office with VAV."""
    if not llm_enabled():
        pytest.skip("Set LLM_TESTS_ENABLED=1 and ANTHROPIC_API_KEY")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = await run_agent(
                    session,
                    "Create a 5-zone office building with VAV reheat",
                )

                tools_called = [t["tool"] for t in result.tool_trace]

                # Must use MCP tools, not write raw files
                assert "create_baseline_osm" in tools_called or \
                       "create_example_osm" in tools_called
                assert "add_baseline_system" in tools_called or \
                       any("ashrae_sys_num" in str(t["input"]) for t in result.tool_trace)

                # Should query skill first
                assert tools_called[0] in ("get_skill", "list_skills")

                # Model should have 5 zones
                summary = await session.call_tool("get_model_summary", {})
                s = unwrap(summary)
                assert s["summary"]["thermal_zones"] == 5

    asyncio.run(_run())
```

---

## Test Categories

### Tier 1: Tool Selection (fast, cheap — ~$0.01/test)

Send a single prompt, check which tool Claude picks first. No tool execution needed — just check the first `tool_use` block.

```python
TOOL_SELECTION_CASES = [
    ("Create a 10-zone office building", ["create_baseline_osm"]),
    ("Add DOAS with fan coils to all zones", ["add_doas_system"]),
    ("Run a simulation and show me the EUI", ["run_simulation"]),
    ("What's the building floor area?", ["get_building_info", "get_model_summary"]),
    ("Show me a 3D view of the model", ["view_model"]),
]
```

These can run WITHOUT the MCP server — just pass tool definitions to the API and check the response. Cheapest possible LLM test.

### Tier 2: Multi-Step Workflows (moderate — ~$0.10/test)

Full agent loop with tool execution. Verify the tool call sequence and final model state. No simulation (fast).

```python
WORKFLOW_CASES = [
    {
        "prompt": "Create a 5-zone office with VAV reheat",
        "required_tools": ["create_baseline_osm", "add_baseline_system"],
        "forbidden_tools": [],
        "model_checks": {"thermal_zones": 5, "air_loops": 1},
    },
    {
        "prompt": "Create a building and set the weather to Chicago",
        "required_tools": ["create_baseline_osm", "set_weather_file"],
        "model_checks": {},
    },
]
```

### Tier 3: End-to-End Simulation (expensive — ~$0.50/test, ~5min)

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
        "assertions": [
            simulation_succeeded(),
            eui_in_range(50, 300),  # kBtu/ft2 sanity check
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
            agent_wrote_raw_idf(),
            agent_wrote_raw_osm(),
            agent_used_bash_for_energyplus(),
        ],
    },
]
```

---

## eval.md Integration

The 8 existing `eval.md` files have should-trigger/should-not-trigger tables:

```markdown
## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Create a 5-zone office" | create_baseline_osm | ashrae_sys_num present |

## Should NOT trigger
| Query | Why |
|---|---|
| "What spaces are in the model?" | Query — use list_spaces |
```

These can be auto-parsed into Tier 1 test cases:

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

## Cost Controls

### Kill Switch

```python
# tests/llm/conftest.py
def llm_enabled() -> bool:
    return (
        os.environ.get("LLM_TESTS_ENABLED", "").lower() in ("1", "true")
        and os.environ.get("ANTHROPIC_API_KEY")
    )
```

### Budget Tracking

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

### CI Configuration

```yaml
jobs:
  llm-tests:
    if: vars.LLM_TESTS_ENABLED != 'false'
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
      LLM_TESTS_ENABLED: "true"
      LLM_TESTS_MAX_PROMPTS: ${{ vars.LLM_TESTS_MAX_PROMPTS || '20' }}
      RUN_OPENSTUDIO_INTEGRATION: "1"
      MCP_SERVER_CMD: "openstudio-mcp"
```

### Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `LLM_TESTS_ENABLED` | (unset) | Set to `1` to enable LLM tests |
| `ANTHROPIC_API_KEY` | (required) | Claude API key |
| `LLM_TESTS_MAX_PROMPTS` | `20` | Hard cap on API calls per run |
| `LLM_TESTS_MODEL` | `claude-sonnet-4-5-20250929` | Model to test with |
| `LLM_TESTS_TIER` | `all` | `1`, `2`, `3`, or `all` |

### Estimated Costs

| Run Type | Tests | Est. Cost | Est. Time |
|---|---|---|---|
| Tier 1 only (tool selection) | 15-20 | ~$0.20 | ~2 min |
| Tier 1 + 2 (workflows) | 25-30 | ~$1.50 | ~10 min |
| Full suite (all tiers) | 35-40 | ~$5.00 | ~30 min |

---

## Handling Non-Determinism

LLM outputs vary between runs:

1. **Structural assertions** — check tool names and param ranges, not exact text or order
2. **Retry with budget** — run flaky tests up to 3 times, pass if 2/3 succeed
3. **Soft vs hard failures** — tool selection = hard fail, parameter exact values = soft warning
4. **Required vs acceptable** — `required_tools` must all appear; order is flexible unless specified
5. **Multiple models** — same prompts against Sonnet + Haiku; if both fail, it's a tool description issue

---

## Implementation Roadmap

### Phase 1: Agent Loop + Smoke Tests

- [ ] Create `tests/llm/` directory structure
- [ ] Implement `agent_loop.py` — MCP tool → Anthropic format converter, agentic loop
- [ ] Implement `conftest.py` — `llm_enabled()`, budget guard, model selection
- [ ] Write 3 Tier 1 tests (tool selection, no execution)
- [ ] Write 2 Tier 2 tests (create building, add HVAC — with execution)
- [ ] Write 1 guardrail test (agent must not write raw IDF)
- [ ] Run locally, document findings on latency and non-determinism

### Phase 2: eval.md Integration + CI

- [ ] Build eval.md parser → auto-generate Tier 1 test cases from 8 skill evals
- [ ] Add CI workflow (separate from main CI, `workflow_dispatch` + weekly schedule)
- [ ] Add budget tracking with summary output
- [ ] Add retry logic for flaky tests
- [ ] Store `ANTHROPIC_API_KEY` in repo secrets

### Phase 3: E2E + Multi-Model

- [ ] Add Tier 3 E2E tests (simulate + extract results)
- [ ] Add multi-model comparison (Sonnet vs Haiku vs Opus on same prompts)
- [ ] Integrate results into PR comments
- [ ] A/B test tool descriptions (which wording leads to better selection?)

### Phase 4: Advanced

- [ ] Benchmark new releases against fixed prompt suite
- [ ] Share framework with other MCP server projects
- [ ] Add OpenAI/Gemini backends for cross-model testing

---

## Open Questions

1. **MCP → Anthropic tool format conversion** — MCP uses JSON Schema `inputSchema`, Anthropic uses `input_schema`. Should be a straightforward mapping but needs validation for edge cases (nested objects, arrays, enums).
2. **System prompt** — should we include the MCP `instructions` field as a system prompt in the API call to match real-world behavior? Probably yes.
3. **Token limits** — 127 tools × ~200 tokens each = ~25K tokens of tool definitions per API call. Within limits but significant. May want to filter to relevant tools per test.
4. **Model selection for CI** — Sonnet is the best cost/quality tradeoff. Haiku for cheap smoke tests. Opus for high-fidelity E2E.
