# Token Context & Performance Impact

This document covers the measurable cost of connecting openstudio-mcp to an LLM client: how many tokens the 142 tools consume, how different clients handle that load, and what strategies reduce the overhead.

All schema measurements are from the openstudio-mcp codebase as of March–April 2026. LLM accuracy figures are from the three-model benchmark sweep (180 tests, zero retries; see [`docs/knowledge/tool-discovery-and-llm-testing.md`](../knowledge/tool-discovery-and-llm-testing.md)).

---

## What Adds to Context

When an MCP client connects to openstudio-mcp, the following items may enter the model's context window:

| Item | Size | When loaded |
|------|------|-------------|
| Tool schemas (all 142) | ~61K chars / **~15K tokens** | On first tool call or session start |
| Server instructions (`NEVER`/`ALWAYS` rules) | ~2K tokens | Once per session |
| Skill guide content (`get_skill()` output) | 1–4K tokens per guide | When explicitly requested |
| MCP prompts / resources | ~0.5K tokens each | When explicitly invoked |
| Conversation history | Grows per turn | Accumulates throughout session |

**Total fixed overhead on first tool call: ~17–20K tokens.**

For comparison, a full simulation run (create building → simulate → extract results → compare) takes approximately **15K total tokens** in conversation — roughly equivalent to the schema overhead on the first call alone.

---

## Schema Size History

The schema size has been measured at multiple points in the project:

| Date | Tools | Schema Chars | Est. Tokens | Change |
|------|-------|-------------|-------------|--------|
| Feb 2026 | 62 | ~30K | ~7.5K | Initial |
| Mar 2026 | 126 | ~100K | ~25K | +64 tools |
| Mar 2026 (post-compress) | 127 | ~60K | ~15K | 30% description compression |
| Apr 2026 | 142 | ~61K | ~15K | +15 tools; size stable |

Key lesson: description compression reduced schema size but harmed ToolSearch accuracy (compressed descriptions had fewer keywords for BM25 matching). The current 15K token overhead is a deliberate balance between size and discoverability.

---

## Per-Client Context Budget

### Context windows

| Client / Model | Context Window | Schema Overhead | Overhead % |
|----------------|---------------|-----------------|-----------|
| Claude Desktop (Sonnet 4.5) | 200K tokens | ~15K tokens | ~7.5% |
| Claude Code (Sonnet 4.5) | 200K tokens | ~1–3K tokens* | ~1%* |
| VS Code Copilot (GPT-4.1) | 128K tokens | ~13–14K tokens† | ~11% |
| VS Code Copilot (Claude Sonnet) | 200K tokens | ~13–14K tokens† | ~7% |
| VS Code Copilot (Gemini Flash) | 1M tokens | ~13–14K tokens† | ~1.4% |
| Windsurf / 80-tool subset | Varies | ~9–11K tokens | — |
| Gemini CLI (Gemini 2.5 Pro) | 1M tokens | ~15K tokens | ~1.5% |

\* Claude Code ToolSearch defers all tools; only 3–5 schemas load per turn.  
† VS Code Copilot enforces a 128-tool cap; 14 tools are excluded, saving ~1.5K tokens.

### When Context Pressure Becomes a Problem

Claude Code triggers ToolSearch automatically when schemas exceed 10% of context. For other clients, the model itself must manage context. Signs of context pressure:

- Model begins truncating or paraphrasing earlier in the conversation
- Tool calls start failing to pass correct parameter values (model "forgets" schema details)
- Model stops using tools entirely and falls back to explaining what it would do
- Long simulation chains: after 20+ turns with large intermediate results, accuracy drops

**Practical guideline:** For Claude Desktop and VS Code Copilot, plan for 15–25 high-quality turns per conversation on complex workflows. Start a new conversation and reference `/runs/` output paths to continue.

---

## How Clients Handle 142 Tools

### Claude Code: ToolSearch (Deferred Loading)

ToolSearch indexes all 142 tools at image build time using BM25/regex on names and descriptions. When schemas exceed 10% of context, tools are deferred. Per turn:
- ~3–5 tool schemas load into context (~1K tokens)
- Schema overhead drops ~85% vs. loading all 142
- Works because the ToolSearch index holds the full schema catalog outside context

**Benchmark result:** 94.4% pass rate (Sonnet/Opus, 180 tests, zero retries). ToolSearch calls: avg 1.9/test.

### Claude Desktop / VS Code Copilot: Brute-Force Load

All enabled tool schemas load into context on the first tool call. No deferred loading, no filtering. Performance effect:
- First response in a new session has ~7.5–11% context already consumed
- Accuracy stays high for shorter sessions (5–10 turns)
- Long sessions may show degradation as conversation history + schema + results approach the context limit

### Windsurf: Per-Tool Toggle (Manual Curation)

Cascade enforces 100 tools hard. User selects which tools are enabled. With a curated 80-tool set (~9–11K tokens), the overhead is ~40% lower than loading all 142. Manual curation adds setup friction but produces the most focused tool surface.

### Gemini CLI: Large Context Buffer

1M token context window means schema overhead (~15K tokens = 1.5%) is negligible for initial load. The practical concern is accuracy per turn, not context exhaustion — presenting all 142 tools at once can confuse the model. Use `includeTools` to keep per-turn tool count under ~40.

---

## Strategies to Reduce Context Overhead

### 1. Use `list_skills` + `get_skill` First (Universal)

Instead of letting the model search all 142 tools, ask it to follow a skill guide. The guide gives explicit tool names and order, bypassing tool discovery entirely:

```
"Use the new-building skill to create a medium office building in Boston."
```

vs.

```
"Create a medium office building in Boston."  ← model must select from 142 tools
```

Both work, but the first produces fewer ToolSearch calls and more predictable tool sequences.

### 2. Enable `defer_loading` (OpenAI-Compatible Clients)

For clients that support the OpenAI `defer_loading` flag, set it on the server config. This exposes only a search tool by default and loads schemas on demand. Reduces first-call overhead by ~85%.

### 3. Use `includeTools` / Per-Tool Toggles (Windsurf, Gemini CLI)

Configure a focused tool subset matching your current workflow phase. A 30-tool simulation workflow subset (~4–5K tokens) is well within any client's context budget and produces cleaner responses than exposing all 142.

### 4. Reference `/runs/` Paths, Not Inline Results

Instead of asking the model to read and summarize large simulation outputs inline, reference them by path:

```
"The simulation output is at /runs/run-20260415/. Extract the EUI."
```

This lets `extract_summary_metrics` and `extract_end_use_breakdown` do targeted extraction rather than streaming the full HTML report into context.

### 5. Split Long Workflows Across Conversations (Claude Desktop)

Save model state at key checkpoints with `save_osm_model`. Start a fresh conversation for the next phase. Reference saved files by path. This resets conversation history overhead while preserving all model changes.

---

## LLM Accuracy vs. Tool Count

From internal benchmarks and published research:

| Tools Presented Per Turn | Accuracy | Source |
|--------------------------|----------|--------|
| 5–7 | ~92% | Jenova.ai |
| 10–15 | sweet spot | Multiple |
| 3–5 (ToolSearch output) | 94.4% | openstudio-mcp sweep |
| 40+ (all visible, no deferral) | Degraded | Allen Chan / IBM |
| 100+ (no retrieval) | ~13–14% | RAG-MCP |
| 100+ (with semantic retrieval) | ~43% | RAG-MCP |

The openstudio-mcp benchmark shows 94.4% at 142 tools **because ToolSearch reduces the per-turn visible set to 3–5**. Without ToolSearch (e.g., Claude Desktop), the effective tool count visible to the model per turn is still all 142, but Claude's reasoning capability keeps accuracy high for sessions under ~20 turns.

---

## Evaluation Checklist

When comparing client performance against openstudio-mcp, measure:

- [ ] **First tool call latency** — time from prompt to first tool invocation
- [ ] **Schema token overhead** — check via model's token counter if available
- [ ] **ToolSearch calls per workflow** — how often the model searches before acting
- [ ] **Accuracy at turn 5 vs. turn 20** — does accuracy degrade in long sessions?
- [ ] **Failure mode when context is full** — does the model warn, truncate, or silently fail?
- [ ] **`list_skills` adherence** — does the model follow the skill guide or guess tool params?

See [`docs/testing/advanced-evaluation-template.md`](../testing/advanced-evaluation-template.md) for a full structured evaluation form.
