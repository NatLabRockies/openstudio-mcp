# LLM-in-the-Loop CI Testing for openstudio-mcp

## Problem

openstudio-mcp exposes 100+ tools to LLM agents, but today's CI only tests the tools in isolation (unit/integration tests). There's no automated way to verify that an LLM agent, given a natural language prompt, actually uses the right tools in the right order and produces a valid building energy model. We saw this failure firsthand: given "create a 10-zone office with DOAS + fan coils," the agent bypassed all MCP tools and started writing raw IDF by hand.

We need CI tests that send real prompts to real LLMs and verify the agent behaves correctly when connected to openstudio-mcp.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  GitHub Actions Runner                              │
│                                                     │
│  ┌──────────────┐    ┌───────────────────────────┐  │
│  │  Test Harness │───▶│  LLM Agent (Copilot CLI  │  │
│  │  (pytest)     │    │  or Copilot SDK)          │  │
│  └──────┬───────┘    └──────────┬────────────────┘  │
│         │                       │                    │
│         │ assertions            │ MCP tool calls     │
│         ▼                       ▼                    │
│  ┌──────────────┐    ┌───────────────────────────┐  │
│  │  Eval Logic   │◀──│  openstudio-mcp server    │  │
│  │  (tool trace, │    │  (Docker container)       │  │
│  │   model check)│    └───────────────────────────┘  │
│  └──────────────┘                                    │
└─────────────────────────────────────────────────────┘
```

---

## CI Kill Switch & Cost Controls

LLM tests consume real money (premium requests or API tokens). The test suite must be easy to disable at any level without code changes.

### Repository Variable: `LLM_TESTS_ENABLED`

A single GitHub Actions **repository variable** controls whether LLM tests run in CI. Default: `"true"`. Set to `"false"` to disable all LLM tests immediately — no PR required, no deploy, instant effect.

```yaml
jobs:
  llm-integration:
    # Kill switch: set LLM_TESTS_ENABLED to "false" in repo variables to disable
    if: vars.LLM_TESTS_ENABLED != 'false'
    runs-on: ubuntu-latest
    ...
```

### Granular Controls

Additional repository variables for finer control:

| Variable | Default | Effect |
|---|---|---|
| `LLM_TESTS_ENABLED` | `"true"` | Master kill switch. `"false"` skips all LLM jobs. |
| `LLM_TESTS_E2E_ENABLED` | `"true"` | `"false"` skips expensive E2E tests, runs only tool-selection tests. |
| `LLM_TESTS_MAX_PROMPTS` | `"20"` | Hard cap on prompts per CI run. Harness stops after this many. |
| `LLM_TESTS_MODELS` | `"claude-sonnet-4.5"` | Comma-separated model list. Reduce to 1 model to cut costs. |

### In the Test Harness

```python
# tests/llm/conftest.py
import os
import pytest

MAX_PROMPTS = int(os.environ.get("LLM_TESTS_MAX_PROMPTS", "20"))
_prompt_count = 0

def check_budget():
    global _prompt_count
    _prompt_count += 1
    if _prompt_count > MAX_PROMPTS:
        pytest.skip(f"LLM prompt budget exhausted ({MAX_PROMPTS} max)")

@pytest.fixture(autouse=True)
def llm_budget_guard():
    check_budget()

def skip_if_no_llm():
    """Decorator/marker for LLM tests"""
    return pytest.mark.skipif(
        os.environ.get("LLM_TESTS_ENABLED", "true").lower() == "false",
        reason="LLM tests disabled (LLM_TESTS_ENABLED=false)"
    )
```

### Emergency Shutoff

If premium requests are burning too fast mid-run:
1. **Cancel the workflow run** in the GitHub Actions UI (immediate)
2. **Set `LLM_TESTS_ENABLED` to `"false"`** in Settings → Variables → Actions (prevents future runs)
3. The `timeout-minutes: 30` on the job is a backstop — no run can exceed 30 min

---

## Running LLM Tests Locally

Developers should be able to run the same LLM test suite on their own machine without CI. This is essential for iterating on tool descriptions, skills, and prompts before pushing to the repo.

### Prerequisites

1. **openstudio-mcp running locally** (Docker or native):
   ```bash
   # Docker (matches CI)
   docker run -d -p 8000:8000 ghcr.io/natlabrokies/openstudio-mcp:latest

   # Or if developing locally
   cd /path/to/openstudio-mcp && python -m openstudio_mcp
   ```

2. **LLM backend** — at least one of:
   - **Copilot CLI** installed and authenticated (`npm install -g @github/copilot && copilot /login`)
   - **Anthropic API key** set as `ANTHROPIC_API_KEY` env var
   - **OpenAI API key** set as `OPENAI_API_KEY` env var

### Running Tests

```bash
# Run all LLM tests against default backend (auto-detects Copilot CLI → Anthropic → OpenAI)
pytest tests/llm/ -v

# Run only tool-selection smoke tests (fast, cheap)
pytest tests/llm/ -v -m "tool_selection"

# Run against a specific backend
LLM_BACKEND=anthropic pytest tests/llm/ -v
LLM_BACKEND=copilot-cli pytest tests/llm/ -v
LLM_BACKEND=openai pytest tests/llm/ -v

# Run against a specific model
LLM_MODEL=claude-haiku-4.5 pytest tests/llm/ -v

# Limit prompt budget (useful for quick iteration)
LLM_TESTS_MAX_PROMPTS=3 pytest tests/llm/ -v

# Skip E2E tests (no simulation, just tool selection)
pytest tests/llm/ -v -m "not e2e"

# Disable LLM tests entirely (same flag as CI)
LLM_TESTS_ENABLED=false pytest tests/llm/ -v
```

### Backend Auto-Detection

The test harness auto-detects which LLM backend to use based on what's available, unless overridden:

```python
# tests/llm/backends.py
import shutil
import os

def detect_backend() -> str:
    """Auto-detect available LLM backend. Priority order:
    1. LLM_BACKEND env var (explicit override)
    2. Copilot CLI (if installed and authenticated)
    3. Anthropic API (if ANTHROPIC_API_KEY set)
    4. OpenAI API (if OPENAI_API_KEY set)
    """
    override = os.environ.get("LLM_BACKEND")
    if override:
        return override

    # Check Copilot CLI
    if shutil.which("copilot"):
        return "copilot-cli"

    # Check API keys
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"

    raise RuntimeError(
        "No LLM backend available. Install Copilot CLI, "
        "or set ANTHROPIC_API_KEY or OPENAI_API_KEY."
    )
```

### Local vs CI: Same Tests, Same Assertions

The test definitions (prompts, expected tools, assertions) are identical in both environments. Only the backend and MCP server URL differ:

| Setting | CI | Local |
|---|---|---|
| MCP server URL | `http://openstudio-mcp:8000/mcp` (service container) | `http://localhost:8000/mcp` (Docker or native) |
| LLM backend | Copilot CLI (PAT auth) | Auto-detected (Copilot CLI, Anthropic, or OpenAI) |
| Budget control | `vars.LLM_TESTS_MAX_PROMPTS` | `LLM_TESTS_MAX_PROMPTS` env var |
| Kill switch | `vars.LLM_TESTS_ENABLED` | `LLM_TESTS_ENABLED` env var |

```python
# tests/llm/conftest.py
import os

MCP_SERVER_URL = os.environ.get(
    "OPENSTUDIO_MCP_URL",
    "http://localhost:8000/mcp"
)
```

### Developer Workflow

Typical iteration loop when improving tool descriptions or skills:

```
1. Start openstudio-mcp locally
2. Edit a tool description or skill file
3. Run: LLM_TESTS_MAX_PROMPTS=1 pytest tests/llm/test_tool_selection.py::test_create_building -v -s
4. See if the LLM picks the right tool → if not, refine and re-run
5. Once passing locally, push and let CI validate
```

### Cost Awareness for Local Runs

The harness prints a summary after each run:

```
═══ LLM Test Summary ═══
Backend:         anthropic (claude-sonnet-4.5)
Prompts sent:    5 / 20 budget
Est. cost:       ~$0.03 (input) + ~$0.08 (output)
Pass:            4
Fail:            1 (test_create_building_guardrail)
Soft warnings:   1
═════════════════════════
```

---

## Option 1: GitHub Copilot CLI in GitHub Actions (Recommended Starting Point)

### How It Works

Copilot CLI has a **programmatic mode** (`copilot -p "PROMPT"`) designed for CI/CD. It runs non-interactively, prints output to stdout, and exits. GitHub officially documents this pattern for Actions automation.

### Authentication

- Create a **fine-grained PAT** with the "Copilot Requests" permission
- Store as `COPILOT_GITHUB_TOKEN` in repository secrets
- Each prompt consumes one premium request from the subscription

### Workflow Skeleton

```yaml
name: LLM Integration Tests
on:
  # Run on demand + weekly to catch regressions
  workflow_dispatch:
    inputs:
      max_prompts:
        description: 'Max prompts to send (cost control)'
        default: '20'
        type: string
      models:
        description: 'Comma-separated model list'
        default: 'claude-sonnet-4.5'
        type: string
  schedule:
    - cron: '0 6 * * 1'  # Monday 6am UTC
  # Optionally on PR to skills/ or tool descriptions
  pull_request:
    paths:
      - '.claude/skills/**'
      - 'src/openstudio_mcp/tools/**'

jobs:
  llm-integration:
    # Master kill switch — set to "false" in Settings → Variables → Actions
    if: vars.LLM_TESTS_ENABLED != 'false'
    runs-on: ubuntu-latest
    timeout-minutes: 30
    services:
      openstudio-mcp:
        image: ghcr.io/natlabrokies/openstudio-mcp:latest
        ports:
          - 8000:8000

    steps:
      - uses: actions/checkout@v5

      - name: Setup Node.js
        uses: actions/setup-node@v4

      - name: Install Copilot CLI
        run: npm install -g @github/copilot

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install test dependencies
        run: pip install -r tests/llm/requirements.txt

      - name: Run LLM prompt tests
        env:
          COPILOT_GITHUB_TOKEN: ${{ secrets.COPILOT_PAT }}
          LLM_BACKEND: copilot-cli
          LLM_TESTS_ENABLED: "true"
          LLM_TESTS_E2E_ENABLED: ${{ vars.LLM_TESTS_E2E_ENABLED || 'true' }}
          LLM_TESTS_MAX_PROMPTS: ${{ inputs.max_prompts || vars.LLM_TESTS_MAX_PROMPTS || '20' }}
          LLM_TESTS_MODELS: ${{ inputs.models || vars.LLM_TESTS_MODELS || 'claude-sonnet-4.5' }}
          OPENSTUDIO_MCP_URL: "http://localhost:8000/mcp"
        run: |
          pytest tests/llm/ -v --tb=short
```

### Key Considerations

- **Cost**: Each prompt = 1 premium request. Budget ~5-10 prompts per CI run.
- **Non-determinism**: LLMs are probabilistic. Tests must assert on *structural* outcomes (did it call the right tools?) not exact text.
- **Latency**: Each prompt takes 30-120s. Keep the test suite small and focused.
- **MCP connectivity**: Copilot CLI supports custom MCP servers. Configure `~/.copilot/mcp-config.json` to point at the local openstudio-mcp container.

### Copilot CLI + MCP Server Configuration

```json
{
  "servers": {
    "openstudio-mcp": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

Or use the `--mcp-config` flag with `copilot -p`.

---

## Option 2: GitHub Copilot SDK (Programmatic, More Control)

### How It Works

The **Copilot SDK** (`github/copilot-sdk`) is a programmatic interface to the Copilot agent runtime. Available in Python, TypeScript, Go, and .NET (currently in Technical Preview). It talks to Copilot CLI in server mode over JSON-RPC.

### Why This May Be Better for Testing

- **Structured output**: You get the full conversation history including tool calls, not just stdout text
- **MCP integration**: Native support for connecting MCP servers to sessions
- **Session control**: Create sessions, send prompts, inspect responses programmatically
- **Model selection**: Switch models per test (`claude-sonnet-4.5`, `gpt-5`, etc.)

### Python Example

```python
import asyncio
from copilot import CopilotClient

async def test_doas_fancoil_workflow():
    client = CopilotClient()
    await client.start()

    session = await client.create_session({
        "model": "claude-sonnet-4.5",
        "mcp_servers": {
            "openstudio-mcp": {
                "type": "http",
                "url": "http://localhost:8000/mcp",
                "tools": ["*"],
            }
        },
    })

    response = await session.send_and_wait({
        "prompt": (
            "Create a 10-zone office building with a DOAS + fan coil system. "
            "Set chilled water to 44F and hot water to 140F."
        )
    })

    # Extract tool calls from response
    content = response.data.content
    tool_calls = [
        block for block in content
        if block.get("type") == "mcp_tool_use"
    ]
    tool_names = [tc["name"] for tc in tool_calls]

    # Assertions: did the agent use the right tools?
    assert "create_baseline_osm" in tool_names, \
        "Agent should use create_baseline_osm, not write raw IDF"
    assert "add_doas_system" in tool_names, \
        "Agent should use add_doas_system for DOAS + fan coils"
    assert not any("write" in name for name in tool_names
                    if "idf" in str(tool_calls)), \
        "Agent should NOT write raw IDF files"

    await client.stop()

asyncio.run(test_doas_fancoil_workflow())
```

### Availability Note

The Copilot SDK is in **Technical Preview** as of Feb 2026. API surface may change. The CLI approach (Option 1) is GA and more stable for CI today.

---

## Option 3: Direct LLM API Calls (Model-Agnostic)

### How It Works

Skip Copilot entirely. Call the Anthropic or OpenAI API directly, providing openstudio-mcp tools as function/tool definitions in the API request. This gives maximum control but requires more setup.

### When to Use

- Testing specific models (Claude, GPT-4, etc.) head-to-head
- Testing tool descriptions in isolation (does the model pick the right tool given this description?)
- When Copilot's mediation layer adds unwanted complexity

### Sketch

```python
import anthropic

client = anthropic.Anthropic()

# Load tool definitions from openstudio-mcp
tools = load_mcp_tool_definitions("http://localhost:8000/mcp")

response = client.messages.create(
    model="claude-sonnet-4-5-20250929",
    max_tokens=4096,
    tools=tools,
    messages=[{
        "role": "user",
        "content": "Create a 10-zone office with DOAS + fan coils, 44F CHW, 140F HHW"
    }]
)

# Check which tools the model wanted to call
tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
```

### Trade-offs

| | Copilot CLI | Copilot SDK | Direct API |
|---|---|---|---|
| Setup effort | Low | Medium | Medium |
| MCP integration | Built-in | Built-in | Manual |
| Tool call visibility | Limited (stdout) | Full structured | Full structured |
| Model choice | Copilot-mediated | Copilot-mediated | Any model directly |
| Cost model | Premium requests | Premium requests | API tokens |
| Stability | GA | Tech Preview | Stable |
| NLR licensing | Covered by GH Enterprise | Covered by GH Enterprise | Separate API contract |

---

## Test Design Patterns

### Pattern 1: Tool Selection Tests (Fast, Cheap)

Verify the LLM picks the right tools given a prompt. Don't actually execute the tools.

```python
TOOL_SELECTION_TESTS = [
    {
        "prompt": "Create a 10-zone office building",
        "expected_tools": ["create_baseline_osm"],
        "forbidden_patterns": ["write.*idf", "create_file"],
        "description": "Agent should use MCP tools, not generate raw files"
    },
    {
        "prompt": "Add DOAS with fan coils to all zones",
        "expected_tools": ["add_doas_system"],
        "expected_params": {"zone_equipment_type": "FanCoil"},
    },
    {
        "prompt": "Set chilled water supply temp to 44F",
        "expected_tools": ["set_component_properties"],
        # 44F = 6.67C
        "param_check": lambda params: abs(float(params.get("value", 0)) - 6.67) < 0.5,
    },
    {
        "prompt": "Run a simulation and show me the EUI",
        "expected_tools": ["run_simulation", "extract_summary_metrics"],
    },
]
```

### Pattern 2: End-to-End Workflow Tests (Slower, Higher Value)

Send a complex prompt through the full stack: LLM → MCP server → OpenStudio → EnergyPlus.

```python
E2E_TESTS = [
    {
        "prompt": (
            "Create a 10-zone office building in Golden, CO with ASHRAE System 7 "
            "VAV with reheat. Run a simulation and report the EUI."
        ),
        "assertions": [
            tool_was_called("create_baseline_osm"),
            tool_was_called("change_building_location"),
            tool_was_called("run_simulation"),
            tool_was_called("extract_summary_metrics"),
            simulation_completed_successfully(),
            eui_in_range(50, 200),  # kBtu/ft2, sanity check
        ],
        "timeout": 600,  # 10 min for full sim
    },
]
```

### Pattern 3: Guardrail Regression Tests

Specifically test that the agent does NOT do the wrong thing.

```python
GUARDRAIL_TESTS = [
    {
        "prompt": "Create a simple office building model",
        "forbidden_behaviors": [
            writes_raw_idf_file(),
            writes_raw_osm_file(),
            uses_bash_to_run_energyplus(),
            ignores_mcp_tools(),
        ],
    },
]
```

---

## Handling Non-Determinism

LLM outputs vary between runs. Strategies:

1. **Structural assertions only**: Check tool names and parameter ranges, not exact text or order.
2. **Retry with budget**: Run each test up to 3 times. Pass if 2/3 succeed.
3. **Soft vs hard failures**: Tool selection = hard fail. Parameter exact values = soft warning.
4. **Snapshot baselining**: Record a "golden run" and flag significant deviations.
5. **Multiple models**: Run the same prompts against 2-3 models. If all fail the same test, it's likely a tool description issue, not model variance.

---

## CI Budget & Scheduling

| Run Type | Trigger | Prompts | Est. Cost | Est. Time |
|---|---|---|---|---|
| Smoke test | PR to skills/tools | 3-5 tool selection tests | 3-5 premium requests | ~5 min |
| Weekly regression | Scheduled (Monday) | 10-15 tool selection + 2-3 E2E | 15-20 premium requests | ~30 min |
| Full suite | Manual / release | All tests + multi-model | 30-50 premium requests | ~60 min |

---

## Implementation Roadmap

### Phase 1: Proof of Concept (1-2 weeks)
- [ ] Set up Copilot CLI in a GitHub Actions workflow with `if: vars.LLM_TESTS_ENABLED != 'false'` kill switch
- [ ] Create PAT with Copilot Requests permission, store in repo secrets
- [ ] Add `LLM_TESTS_ENABLED`, `LLM_TESTS_MAX_PROMPTS` as repo variables
- [ ] Write 3 tool-selection smoke tests (create building, add HVAC, run sim)
- [ ] Configure MCP server connection in CI
- [ ] Validate the guardrail test: "does the agent bypass MCP tools?"
- [ ] **Validate local dev workflow**: developer runs same tests with `ANTHROPIC_API_KEY` or Copilot CLI
- [ ] Document findings on non-determinism and latency

### Phase 2: Test Harness (2-3 weeks)
- [ ] Build `tests/llm/` framework with test definitions (YAML or Python)
- [ ] Implement assertion library (tool_was_called, param_in_range, etc.)
- [ ] Implement backend auto-detection (Copilot CLI → Anthropic → OpenAI)
- [ ] Implement prompt budget tracking with summary output
- [ ] Add retry logic and soft/hard failure classification
- [ ] Evaluate Copilot SDK (Python) as alternative to CLI stdout parsing
- [ ] Set up weekly scheduled run
- [ ] Add `workflow_dispatch` inputs for on-demand cost overrides (max_prompts, models)

### Phase 3: Expand Coverage (ongoing)
- [ ] Add E2E workflow tests (full create → simulate → report) gated by `LLM_TESTS_E2E_ENABLED`
- [ ] Add multi-model comparison tests (Claude Opus/Sonnet/Haiku + GPT on same prompts)
- [ ] Test skill effectiveness (does adding a skill change agent behavior?)
- [ ] Use `.claude/skills/<name>/eval.md` scenarios as test inputs — each has should-trigger / should-not-trigger tables with expected tools
- [ ] Build automated eval runner from eval.md files (extend `tests/eval_tool_selection.py` pattern)
- [ ] Add direct API tests (Anthropic API) for tool description optimization
- [ ] Integrate results into PR comments / dashboard
- [ ] Add contributor docs: "How to run LLM tests locally" in CONTRIBUTING.md

### Phase 4: Advanced (future)
- [ ] A/B test tool descriptions (which description leads to better tool selection?)
- [ ] Benchmark new openstudio-mcp releases against a fixed prompt suite
- [ ] Evaluate `recommend_workflow` tool by measuring if agents follow its suggestions
- [ ] Share framework with EnergyPlus-MCP and openstudio-standards-mcp teams

---

## Open Questions

1. **NLR Copilot licensing**: Does the NLR GitHub Enterprise plan include Copilot Business/Enterprise with CLI access? Need to confirm premium request budget.
2. **Docker-in-Docker**: The CI runner needs to run the openstudio-mcp Docker container. GitHub Actions `services:` should handle this, but need to test MCP HTTP connectivity between the runner and the service container.
3. **Copilot CLI + custom MCP**: The docs show MCP server configuration, but real-world testing with a local HTTP MCP server in CI needs validation. This is the highest-risk unknown.
4. **API key alternative**: If Copilot CLI + MCP is too brittle in CI, falling back to direct Anthropic API calls with tool definitions extracted from openstudio-mcp may be simpler and more reliable.
5. **Test result persistence**: Should we store golden-run tool traces in the repo for comparison, or regenerate baselines periodically?
