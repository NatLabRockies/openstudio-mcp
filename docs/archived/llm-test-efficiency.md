# Plan: LLM Test Token Efficiency

## Problem

Full LLM test suite (90 tests) consumes ~9M cache read tokens per run.
Each test spawns a fresh `claude -p` process, which:
1. Connects to MCP server, receives 129-tool catalog
2. Calls ToolSearch 1-3 times to load relevant tool schemas (~27K tokens)
3. Executes 1-5 MCP tool calls
4. Process exits, context discarded

90 sessions × ~100K tokens/session = ~9M tokens. Four full runs in a single
dev session used ~37M cache tokens against weekly Claude Max quota.

In contrast, a real user session connects once, ToolSearch runs a few times
early, then tool schemas stay in context for the rest of the conversation.

## Current Architecture

```
pytest ──┬── test_1: claude -p → [init, ToolSearch, tool_call] → exit
         ├── test_2: claude -p → [init, ToolSearch, tool_call] → exit
         ├── ...
         └── test_90: claude -p → [init, ToolSearch, tool_call] → exit
```

- Isolation: perfect (each test is independent, no shared state)
- Token cost: high (re-reads tool catalog 90 times)
- Time: ~70 min (serial, no parallelism)

## Options

### Option A: Session reuse within tiers

Group tests into tiers that share a single `claude` session. Use
`--session-id` or a persistent subprocess with stdin/stdout piping.

```
pytest ──┬── tier1_session: claude (persistent)
         │     ├── prompt_1 → assert
         │     ├── prompt_2 → assert
         │     └── prompt_14 → assert
         ├── tier2_session: claude (persistent)
         │     ├── prompt_1 → assert
         │     └── ...
```

**Pros:** ToolSearch cached after first prompt; ~14x fewer inits for tier1
**Cons:** Conversation history accumulates (later prompts see prior tool calls),
test isolation lost (a failed tool call in test 3 may affect test 4 context),
hard to attribute failures to specific tests.

**Risk:** High. LLM sees growing context from prior prompts — may change
behavior. Test 10 in a session behaves differently than test 10 in isolation.
Defeats the purpose of independent testing.

**Feasibility:** Claude Code CLI `-p` is single-prompt. Would need
`--session-id` with `--resume` or a custom subprocess wrapper sending
multiple prompts. `--resume` exists but replays full history.

### Option B: Parallel test execution

Run N tests concurrently (separate processes). Total tokens unchanged but
wall time drops from ~70 min to ~70/N min.

```
pytest -n 4 ──┬── worker_1: tests 1-23
              ├── worker_2: tests 24-46
              ├── worker_3: tests 47-68
              └── worker_4: tests 69-90
```

**Pros:** Wall time drops ~4x, no isolation loss, simple with pytest-xdist
**Cons:** Same token cost, concurrent Docker containers need resources,
shared /runs dir needs per-worker subdirs to avoid model state conflicts.

**Feasibility:** Medium. pytest-xdist handles parallelism. Main challenge is
ensuring each worker's MCP Docker container has isolated /runs state. Could
use worker-id-based subdirs or unique run dirs per test (already happens for
simulations).

### Option C: Reduce tool catalog size

129 tools × ~210 tokens/tool = ~27K tokens per session. Options:
- **Deferred registration:** Only register tools relevant to the test tier
  (e.g., tier1 doesn't need simulation tools). Requires server config.
- **Shorter descriptions:** Trim verbose arg docs. Risk: LLM makes wrong
  tool choices. Current descriptions drive 100% tier1 pass rate.
- **Tool grouping:** Merge related tools (e.g., 5 extract_* → one
  extract_results with a `metric` param). Breaking API change.

**Pros:** Reduces per-session cost
**Cons:** Architectural changes, may regress tool selection accuracy
**Feasibility:** Low priority. 27K tokens/session is reasonable; the problem
is 90 sessions, not per-session size.

### Option D: Tiered test strategy (recommended)

Don't try to make the full suite cheap. Instead, structure dev workflow:

| Stage | Command | Tests | Tokens | Time |
|-------|---------|-------|--------|------|
| Dev iteration | `pytest -k "test_name"` | 1-3 | ~300K | 1-3 min |
| Tier check | `LLM_TESTS_TIER=1 pytest tests/llm/` | 14 | ~1.4M | 5 min |
| Pre-commit | `pytest -m stable tests/llm/` | ~87 | ~8.7M | 60 min |
| Full validation | `pytest tests/llm/` | 90 | ~9M | 70 min |

Full suite runs 1-2x per feature branch, not per change.

**Pros:** Zero code changes, immediate, already works
**Cons:** Requires discipline (no habitual full-suite runs)

### Option E: MCP config with tool filtering

Claude Code `--allowedTools` already filters. Could create per-tier MCP
configs that only expose relevant tools via a server-side feature flag:

```bash
# Tier 1 only needs tool discovery, not execution
OPENSTUDIO_MCP_TOOLS=query_only openstudio-mcp
```

**Pros:** Smaller tool catalog per test → fewer ToolSearch tokens
**Cons:** Complex server-side feature flag logic, test may not reflect
real-world tool selection behavior (defeats purpose of testing discoverability)

## Recommendation

**Option D now, Option B later.**

Option D is free — just workflow discipline. Already documented in CLAUDE.md
and tests/llm/README.md.

Option B (parallel execution) is the best engineering solution when test
suite grows beyond 90. Halves wall time without sacrificing isolation. Main
work: pytest-xdist setup + per-worker /runs isolation.

Options A/C/E are not worth the tradeoffs — isolation loss, accuracy regression,
or over-engineering for modest gains.

## Unresolved

1. Does `claude -p --session-id` allow appending prompts without replaying
   full history? If yes, Option A becomes more viable.
2. Can pytest-xdist workers get unique env vars for Docker mount paths?
3. Would Claude Code ever support batched tool testing natively?
