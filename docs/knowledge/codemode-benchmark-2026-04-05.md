# CodeMode Benchmark: 2026-04-05

FastMCP 3.2.0 CodeMode transform tested against openstudio-mcp's 142-tool server via Claude Code (Sonnet). Result: **massive regression across every metric**. Feature kept as opt-in toggle (`OSMCP_CODE_MODE=1`) but NOT recommended for Claude Code clients.

## TL;DR

CodeMode reduced pass rate from **95.3% to 24.0%** (71pp drop). Doubled output tokens, tripled ToolSearch calls, 143% longer runtime. Conclusion: Claude Code's built-in ToolSearch already solves the tool discovery problem — adding CodeMode creates a conflicting second discovery layer that degrades performance on every dimension.

## Setup

- **FastMCP:** 3.2.0 (upgraded from 3.0.2)
- **Tools:** 142 (no changes)
- **Model:** Claude Sonnet via Claude Code CLI
- **Test suite:** `tests/llm/test_06_progressive.py` (129 tests, 43 cases × L1/L2/L3)
- **Retries:** 0 (first-attempt signal)
- **Toggle:** `OSMCP_CODE_MODE=1` via env var, activates `mcp.add_transform(CodeMode())` after `register_all_skills()`
- **Test harness:** `runner.py` parses `call_tool("name", ...)` patterns from CodeMode execute blocks to preserve existing assertions

## Results

| Metric | CodeMode OFF | CodeMode ON | Delta |
|--------|-------------|-------------|-------|
| Pass rate | 123/129 (95.3%) | 31/129 (**24.0%**) | **-71.3pp** |
| L1 (vague) | 40/43 (93.0%) | 8/43 (18.6%) | -74.4pp |
| L2 (moderate) | 42/43 (97.7%) | 12/43 (27.9%) | -69.8pp |
| L3 (explicit) | 41/43 (95.3%) | 11/43 (25.6%) | -69.8pp |
| Input tokens | 1,260 | 1,646 | +30.6% |
| Output tokens | 127,859 | **300,118** | **+134.7%** |
| Cache tokens | 12.3M | 20.3M | +65.5% |
| Duration | 69 min | **168 min** | **+143%** |
| Cost (notional) | $9.29 | $22.35 | +140% |
| ToolSearch avg/test | 1.6 | **5.8** | +263% |
| code_executions | 0 | 2.0/test | — |

Raw data:
- `docs/sweeps/codemode-off-2026-04-05/benchmark.json`
- `docs/sweeps/codemode-on-2026-04-05/benchmark.json`

## Failure Mode Analysis (CodeMode ON)

| Mode | Count | Description |
|------|-------|-------------|
| wrong_tool | 67 | LLM wrote Python code calling wrong tool name or with wrong args |
| timeout | 30 | Exceeded 120s wall clock — CodeMode sandbox + meta-tool chain is slower |
| no_mcp_tool | 1 | LLM didn't call any MCP tool (gave up) |
| **Total failed** | **98** | |

L1/L2/L3 all regressed similarly (-70pp each) — CodeMode doesn't discriminate between vague and explicit prompts. The failure is structural, not prompt-sensitivity.

## Root Causes

### 1. Double discovery layer
Claude Code already implements deferred tool loading via its built-in ToolSearch when tool definitions exceed 10K tokens. Our 142 tools hit this threshold and get auto-deferred. Adding CodeMode on top creates a second discovery layer:

1. Claude Code calls ToolSearch to find relevant domain tools
2. Can't find them (CodeMode hid them behind 3 meta-tools)
3. Falls back to the CodeMode meta-tools (search, get_schema, execute)
4. Writes Python code to call the tools
5. Makes errors the LLM wouldn't make calling tools directly

Evidence: ToolSearch calls went UP from 1.6 to 5.8/test. They should have gone to zero if CodeMode had cleanly replaced discovery.

### 2. Sonnet struggles with 142-tool sandbox catalog
The FastMCP author explicitly warned: "Sonnet 4.6 class model was able to use code mode with a complex server, but Haiku 4.5 class model made a few errors." With 142 tools, even Sonnet makes frequent errors writing the `call_tool()` invocations correctly.

Community examples where CodeMode worked (Amazon Ads MCP, 98% reduction) had a few dozen tools, not 142. The complexity scales poorly.

### 3. Code generation adds tokens, not removes them
The promise: CodeMode reduces tokens by not shipping tool definitions.
The reality: The LLM writes Python orchestration code (`result = call_tool("create_baseline_osm", name="test"); print(result)`) that costs more tokens to generate than a direct tool call JSON.

Output tokens more than doubled (128K → 300K). Total token cost increased despite input tokens staying similar.

### 4. Meta-tool overhead
Each CodeMode workflow requires at minimum 3 meta-tool calls: search → get_schema → execute. Direct tool use is 1 call. Even when CodeMode succeeds, it takes 3x the turns for the same operation.

## Why CodeMode's Promise Doesn't Apply to Us

CodeMode is designed for API clients that ship all 142 tool definitions upfront (57K tokens of waste). Its value proposition:

> "Entire tool catalog loads into context upfront, every tool call is a round-trip burning tokens on intermediate results."

**We don't have this problem.** Claude Code already:
- Defers tool definitions at the 10K token threshold
- Only loads 3-5 relevant tools per turn via ToolSearch
- Keeps intermediate results out of context where possible

Our 1,260 input tokens / test (already near-zero due to prompt caching) shows the token waste CodeMode targets does not exist in our setup. Adding CodeMode can only add overhead.

## Recommendation

**Do not use CodeMode with Claude Code clients.**

### For Claude Code users
- Keep `OSMCP_CODE_MODE=0` (default)
- Claude Code's ToolSearch is already solving the discovery problem
- 95.3% pass rate at 1-2 ToolSearch calls per test is near-optimal

### For API users (hypothetical future use case)
CodeMode might still help if we expose openstudio-mcp to API clients that do NOT have deferred loading (raw Anthropic API clients, non-Claude models via OpenAI API, etc.). In that case:
- Set `OSMCP_CODE_MODE=1` at deployment
- Expect some accuracy cost in exchange for token savings
- Test thoroughly — our 24% result suggests even then it may not be worth it

### Toggle preservation
The toggle stays in place:
- `pyproject.toml`: `fastmcp>=3.1.0,<4.0`
- `mcp_server/config.py`: `ENABLE_CODE_MODE` env var
- `mcp_server/server.py`: conditional `mcp.add_transform(CodeMode())`
- `docker/Dockerfile`: `ENV OSMCP_CODE_MODE=0`
- `tests/llm/runner.py`: `LLM_TESTS_CODE_MODE` env var + `code_mode_tool_calls` parser
- `tests/llm/conftest.py`: benchmark tracks CodeMode active state

Future experiments (new FastMCP versions, different sandbox providers, configuration tweaks) can toggle it on without code changes.

## Open Questions for Future Testing

If revisiting CodeMode:

1. Does it work better with **fewer tools**? Test with a subset (e.g., 20 core tools) to see if the 142-tool scale is the problem.
2. Does **configuring fewer discovery stages** help? CodeMode supports collapsing the 3-stage flow to 2-stage. Worth trying.
3. Does **Opus** do better than Sonnet? Haiku was warned against by the FastMCP author; Opus was not tested.
4. Does **disabling Claude Code ToolSearch** (if possible) eliminate the double-discovery conflict?
5. Does **a custom search function** (embeddings instead of BM25) improve tool matching accuracy?
6. Does **CodeMode + `allowed_callers` PTC** work together in API mode, bypassing the Claude Code layer entirely?

## Related Research

- `docs/knowledge/fastmcp-code-mode-and-advanced-tool-use.md` — FastMCP 3.1/3.2 features, Anthropic advanced tool use
- `docs/knowledge/tool-discovery-and-llm-testing.md` — timeline of tool count growth, prior benchmark results
- `docs/knowledge/reddit-mcp-discovery-thread.md` — community approaches to tool discovery at scale

## Files Modified for This Experiment

The toggle code remains in place. No reversion needed.

| File | Purpose |
|------|---------|
| `pyproject.toml` | Pin `fastmcp>=3.1.0,<4.0` |
| `mcp_server/config.py` | `ENABLE_CODE_MODE` env var |
| `mcp_server/server.py` | Conditional `mcp.add_transform(CodeMode())` |
| `docker/Dockerfile` | `ENV OSMCP_CODE_MODE=0` default |
| `tests/llm/runner.py` | Pass env to Docker, parse `call_tool(...)` from execute code |
| `tests/llm/conftest.py` | Track code_mode_active/code_executions in benchmark |
