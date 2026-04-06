# Tool Discovery and LLM Testing at Scale

## Overview

This document consolidates research and findings on scaling MCP tool discovery for openstudio-mcp (142 tools, 22 skills). It covers the project timeline from 62 to 142 tools, an industry survey of 7 approaches to large tool sets, our hands-on ToolSearch implementation, a three-model benchmark (Sonnet/Haiku/Opus, 230 tests, zero retries), and distilled lessons. Primary conclusion: dynamic tool discovery via ToolSearch is sufficient at 142 tools; sub-agent routing is not justified.

## Timeline

### Tool Count and Pass Rate Evolution

| Date | Event | Tools | LLM Pass Rate | Key Change |
|------|-------|-------|---------------|------------|
| Feb 18 | Initial commit | 62 | -- | -- |
| Mar 2 | Input hardening + HVAC auto-wiring | 126 | -- | +64 tools |
| Mar 4 | Description compression (~30%) | 127 | -- | 100K -> 60K chars schema |
| Mar 5 | First LLM test suite | 127 | 44% (50 tests) | Baseline, no system prompt |
| Mar 6 | Server instructions (NEVER/ALWAYS) | 127 | 83% (90 tests) | +39pp from instructions alone |
| Mar 7 | Description fixes | 127 | 91% (90 tests) | +8pp |
| Mar 10 | Generic access tools | 130 | 96% (107 tests) | Phase C |
| Mar 12 | Remove 6 redundant typed list tools | 136 | 97.5% (159 tests) | Progressive L1/L2/L3 framework |
| Mar 19 | Tags + recommend_tools + ToolSearch | 142 | 96.5% (172 tests) | No regression from routing work |
| Mar 20 | Full regression with ToolSearch | 142 | 95.9% (171 tests) | Final pre-benchmark run |
| Mar 28 | Three-model sweep (0 retries) | 142 | 94.4% Sonnet / 88.9% Haiku / 94.4% Opus | 180 non-skipped tests |

### Schema Size Over Time

| Date | Tools | Schema Chars | Est. Tokens |
|------|-------|-------------|-------------|
| Feb 18 | 62 | ~30K | ~7.5K |
| Mar 2 | 126 | ~100K | ~25K |
| Mar 4 (post-compress) | 127 | ~60K | ~15K |
| Mar 19 | 142 | ~61K | ~15K |

## Industry Patterns

Ranked by evidence strength. Core finding: don't collapse N tools into 1 meta-tool -- LLMs are equally bad at selecting parameter values as selecting tools. Every winning approach keeps tools distinct but **filters to 5-15 per turn**.

### Accuracy vs Tool Count (Empirical)

| Tools Presented | Accuracy | Source |
|----------------|----------|--------|
| 5-7 | ~92% | Jenova.ai |
| 10-15 | sweet spot | Multiple |
| 30+ w/retrieval | >90% | RAG-MCP |
| 51 | 2-26% (flat) | Allen Chan / IBM |
| 100+ | 13.6% (flat) | RAG-MCP |
| 100+ w/semantic retrieval | 43% | RAG-MCP |
| 2,792 w/hybrid search | 94% | Stacklok ToolHive |
| 10K w/Anthropic Tool Search | 74-88% | Anthropic internal |

### 1. Deferred Loading + Search (Production-Proven)

Mark tools `defer_loading: true`. LLM sees only a search tool + pinned essentials. Full schemas load on-demand.

| Implementation | Mechanism | Results |
|---|---|---|
| Anthropic Tool Search | BM25/regex on name+description | Opus 4: 49%->74%, 85% token reduction, 10K tool cap |
| OpenAI defer_loading | Same pattern, gpt-5.4+ | Recommends <20 tools/turn |
| Claude Code ToolSearch | Auto at 10% context threshold | 3-5 tools returned per query |
| Stacklok ToolHive | Hybrid semantic+BM25 | 94% on 2,792 tools (vs BM25-only: 34%) |

### 2. Description Enrichment (Highest ROI, Lowest Risk)

Descriptions are the **only** field ToolSearch/clients match against. Tags are inert (FastMCP server-side only, never sent on wire). Best practices: write descriptions like onboarding a new team member; include domain keywords matching how users describe tasks; namespace tool names by service/resource. Note: 97.1% of MCP tool descriptions have at least one "smell" (arxiv:2602.14878). Augmenting descriptions: +5.85pp success but +67% execution steps.

### 3. Server Split (Universal Cross-Client Fix)

Every client with hard caps forces this.

| Client | Limit | Discovery |
|--------|-------|-----------|
| Claude Code | Unlimited (ToolSearch) | Auto-defer at 10% context |
| Claude Desktop | ~100 | None (all in context) |
| Cursor | 40 hard cap | None |
| Windsurf | 100 | Per-tool toggle |
| OpenAI | 128 (recommends ~10) | defer_loading |
| Gemini CLI | 100 soft / 512 API | includeTools/excludeTools |
| TRAE | 40 | None |
| GitHub Copilot | 128 | None |

GitHub MCP Server approach: starts with 4 core tools, user enables toolsets via `--dynamic-toolsets`. Cut 23K tokens (50%).

### 4. Embedding-Based Retrieval (Best for 300+ Tools)

Key insight (Red Hat Tool2Vec): embed **example queries per tool**, not descriptions. Query embeddings discriminate better. Implementations: LangGraph BigTool, tool-gating-mcp (MiniLM-L6-v2), RAG-MCP (Qwen LLM retriever), Portkey mcp-tool-filter, openclaw-mcp-router (LanceDB).

### 5. Hierarchical Selection (~10% Gain)

Pick category first, then tool. ToolTree (ICLR 2026): MCTS + bidirectional pruning, ~10% over SOTA. ToolLLM/DFSDT: 16,464 APIs / 49 domains. MCP-Zero: agent-pull model, 98% token reduction, 3K tools / 308 servers.

### 6. Code Execution Pattern (Nuclear Option)

Agent writes code against tools-as-API. Cloudflare Code Mode: 2,500 endpoints -> 2 tools, 99.9% token reduction. Anthropic programmatic tool calling: 150K->2K tokens. High implementation cost (needs sandbox).

### 7. Meta-Tool / Composite Tools (Modest Gains)

AWO meta-tools: 5-12% fewer LLM calls, +4.2pp success. Works for fixed workflows only. Does NOT solve general tool discovery. Our own evidence: `list_spaces` (typed) passes L1; `list_model_objects("Space")` (generic) fails. Typed > generic.

### MCP Spec Status

Tools are a flat list: `name`, `title`, `description`, `inputSchema`, `outputSchema`, `annotations`. No categories, tags, filtering, or namespaces. Key proposals: SEP-1300 groups+tags (rejected), #1978 Lazy Hydration (`tools/list?minimal=true`), SEP-1576 JSON `$ref` (~24% token reduction). `notifications/tools/list_changed` is in spec but NOT supported by Claude Desktop or Claude Code.

## Our Implementation

### What We Built

1. **Tags on all 142 tools** -- `tags={"core"}`, `tags={"hvac"}`, etc. via FastMCP
2. **`recommend_tools` meta-tool** -- keyword routing to 9 groups
3. **Enriched descriptions** for `search_api` and `search_wiring_patterns`
4. **Docstring hardening** for bypass-prone tools

### Tags Are Inert

Tags are a FastMCP server-side feature, NOT part of the MCP wire protocol. Never sent in `tools/list` responses. No client reads or acts on them. ToolSearch does not use them. Only use: server-side `mcp.disable(tags=...)` / `mcp.enable()` -- which requires `tools/list_changed` support (unavailable in Claude Desktop/Code). Tags kept for future-proofing only.

### ToolSearch Root Cause: Docker Build-Time Indexing

New tools added via volume-mounted code were invisible to ToolSearch. Root cause: ToolSearch indexes tool schemas when the MCP server first connects from the installed package in the Docker image. Volume-mounted code registers tools at runtime but the index is stale.

**Before Docker rebuild:**

| ToolSearch Query | Found? | What it found instead |
|-----------------|--------|----------------------|
| "search_api" | NO | "No matching deferred tools found" |
| "SDK classes methods" | NO | LSP, create_measure, get_object_fields |
| "HVAC wiring recipe" | NO | list_zone_hvac_equipment, get_zone_hvac_details |

**After Docker rebuild + enriched descriptions:**

| Query | Found? | Position |
|-------|--------|----------|
| "search_api" | YES | 1st |
| "SDK methods" | YES | 1st |
| "wiring patterns" | YES | 1st |
| "four pipe beam wiring" | YES | 1st |
| "recommend tools" | YES | 1st |

**Rule: Always rebuild Docker image after adding new MCP tools.** CI does this automatically.

### Description Compression Was Counterproductive

Mar 4: compressed all 127 tool descriptions ~30% (100K -> 60K chars) to reduce context. But Claude Code ToolSearch had shipped Jan 14, 2026 (7 weeks earlier), auto-deferring tools when schemas exceed 10% of context. ToolSearch matches on keywords in descriptions. By compressing, we removed keywords ToolSearch uses to match -- optimized for a problem already solved while creating a new one.

## Model Comparison

### Test Structure

| Tier | Tests | What It Measures |
|------|-------|-----------------|
| setup | 6 | Baseline model creation, simulation setup |
| tier1 | 4 | Single tool selection |
| tier2 | 37 | Multi-step workflows (2-28 tool chains) |
| tier3 | 26 | Natural language eval prompts |
| tier4 | 3 | Guardrails (must use MCP, not scripts) |
| progressive | 104 | L1 vague / L2 moderate / L3 explicit (35 cases x 3 levels) |

Progressive levels: L1 = "Add HVAC to the building" (vague). L2 = "Add a VAV reheat system to all thermal zones" (moderate). L3 = "Add System 7 VAV reheat using add_baseline_system" (explicit tool name).

### Overall Results (Zero Retries)

| Metric | Sonnet | Haiku | Opus |
|--------|--------|-------|------|
| Total pass rate | 170/180 (94.4%) | 160/180 (88.9%) | 170/180 (94.4%) |
| Progressive pass rate | 103/104 (99.0%) | 97/104 (93.3%) | 104/104 (100%) |
| L1 pass rate (vague) | 34/35 (97%) | 32/35 (91%) | 35/35 (100%) |
| L2 pass rate (moderate) | 35/35 (100%) | 34/35 (97%) | 35/35 (100%) |
| L3 pass rate (explicit) | 34/34 (100%) | 31/34 (91%) | 34/34 (100%) |
| Total runtime | 2h38m | 1h20m | 3h05m |
| Avg turns/test | 6.8 | 7.4 | 7.0 |
| Avg ToolSearch calls/test | 1.9 | 0.0 | 2.0 |
| Timeouts | 1 | 0 | 2 |
| Cost (notional) | $18.96 | $11.21 | $32.23 |

### Per-Tier Breakdown

| Tier | Sonnet | Haiku | Opus |
|------|--------|-------|------|
| setup | 6/6 (100%) | 6/6 (100%) | 6/6 (100%) |
| tier1 | 4/4 (100%) | 4/4 (100%) | 4/4 (100%) |
| tier2 | 33/37 (89.2%) | 31/37 (83.8%) | 34/37 (91.9%) |
| tier3 | 21/26 (80.8%) | 19/26 (73.1%) | 19/26 (73.1%) |
| tier4 | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) |
| progressive | 103/104 (99.0%) | 97/104 (93.3%) | 104/104 (100%) |

Tier 3 weakest across all models (73-81%) -- complex eval/workflow tests with natural domain language. Shared failures suggest test expectations or tool descriptions need refinement, not a model gap.

### Progressive L1/L2/L3 Detail (Failures Only)

| Case | Son L1 | Son L2 | Son L3 | Hai L1 | Hai L2 | Hai L3 | Opus |
|------|--------|--------|--------|--------|--------|--------|------|
| create_building | P | P | P | P | **F** | P | all P |
| create_loads | P | P | P | P | P | **F** | all P |
| hvac_sizing | P | P | P | **F** | P | P | all P |
| import_floorplan | P | P | P | **F** | P | **F** | all P |
| replace_windows | P | P | P | P | P | **F** | all P |
| thermal_zones | **F** | P | P | **F** | P | P | all P |

Opus: 100% across all 35 cases at all levels. Haiku L3 failures (import_floorplan, replace_windows, create_loads) are reasoning failures -- even with explicit tool names, haiku can't execute correctly.

### ToolSearch Overhead

| Metric | Sonnet | Haiku | Opus |
|--------|--------|-------|------|
| Avg ToolSearch calls/test | 1.9 | 0.0 | 2.0 |
| Max ToolSearch calls | 10 | 0 | 11 |
| Tests with 0 ToolSearch | 0/180 | 180/180 | 0/180 |

Haiku never calls ToolSearch -- attempts tools directly from initial list. Its failures are reasoning failures, not discovery failures.

### Failure Mode Analysis

| Mode | Sonnet | Haiku | Opus | Description |
|------|--------|-------|------|-------------|
| wrong_tool | 9 | 16 | 8 | Called MCP tool, not expected one |
| no_mcp_tool | 0 | 4 | 0 | No MCP tool called (stuck in builtins) |
| timeout | 1 | 0 | 2 | Exceeded time limit |

**Five root causes across all 40 failures:**

1. **qaqc tests (9 failures)**: all models map "check/validate" to `validate_model` instead of expected `run_qaqc_checks`. Test expectation issue.
2. **troubleshoot tests (5 failures)**: all models call `extract_simulation_errors` instead of expected `get_run_logs`. Test expectation issue.
3. **energy-report timeout (3 failures)**: simulation chain exceeds 120s timeout. Budget issue.
4. **Haiku reasoning failures (15 failures)**: no_mcp_tool (4), hallucination loops (2), L3 failures (3), incomplete chains (6). Model limitation.
5. **Measure code quality (3 failures)**: right tool called but generated code fails quality checks. Code gen issue, not discovery.

**Corrected pass rates** (fixing 3 structural test issues):

| Model | Current | Adjusted |
|-------|---------|----------|
| Sonnet | 94.4% | 97.2% |
| Haiku | 88.9% | 91.1% |
| Opus | 94.4% | 98.3% |

### Architecture Decision: Dynamic Discovery vs Sub-Agent Routing

| Signal | Dynamic OK | Need Sub-Agents | Sonnet | Haiku | Opus | Verdict |
|--------|-----------|-----------------|--------|-------|------|---------|
| L1 pass rate | > 85% | < 70% | 97% | 91% | 100% | OK |
| L2 pass rate | > 90% | < 75% | 100% | 97% | 100% | OK |
| Avg ToolSearch calls | <= 2 | > 4 | 1.9 | 0.0 | 2.0 | OK |
| wrong_tool rate | < 10% | > 25% | 5.0% | 8.9% | 4.4% | OK |

**Every signal falls in "Dynamic Discovery OK" range.** Sub-agent routing not justified.

### Comparison with BEM-AI (PNNL)

| Dimension | BEM-AI | openstudio-mcp |
|-----------|--------|----------------|
| Architecture | Multi-agent (planner + specialists) | Single agent, dynamic discovery |
| Tools | 6 | 142 |
| Models | 4B-70B local | Claude sonnet/haiku/opus (cloud) |
| Reliability | 10/10 at temp=0 | 94-100% first-attempt, 0 retries |
| Test scope | 3 scenarios (envelope only) | 180 tests across all BEM domains |

BEM-AI's multi-agent approach targets small local models that struggle with large tool surfaces. With Claude-class models, dynamic discovery handles 142 tools without routing overhead.

## Lessons and Recommendations

### Findings (Deduplicated)

1. **Server instructions are the biggest lever.** NEVER/ALWAYS guardrails for 6 domains gave +39pp (44% -> 83%) in one change. All subsequent description/tool changes combined added ~13pp.

2. **Description compression was counterproductive.** ToolSearch (shipped Jan 14, 2026) already solved context size. Compressing descriptions removed the keywords ToolSearch needs for matching. Rich descriptions with domain keywords are the mechanism.

3. **Tags are inert metadata.** Not in MCP wire protocol, never sent to clients, not used by ToolSearch. Only useful for server-side enable/disable (which requires `tools/list_changed` -- unsupported by Claude Desktop/Code).

4. **Typed tools > generic tools for discovery.** `list_spaces` passes L1; `list_model_objects("Space")` fails. Don't consolidate typed tools further -- they serve as discoverable entry points. Generic tools are fallbacks for uncommon types.

5. **ToolSearch indexes at Docker build time.** Volume-mounted code is invisible until `docker build`. CI handles this automatically. Local dev requires manual rebuild after adding tools.

6. **~90% L1 is the ceiling for 142 tools.** Remaining failures are genuinely ambiguous prompts where multiple tools are reasonable. Not fixable by description enrichment or tool count reduction.

7. **ToolSearch overhead is minimal.** 1.9-2.0 avg calls for Sonnet/Opus. Well under the "need sub-agents" threshold of >4.

8. **Haiku's failures are reasoning, not discovery.** Zero ToolSearch calls + L3 failures (explicit tool name in prompt) confirm the bottleneck is model capability, not tool surface.

9. **No cross-client discovery standard exists.** 142 tools works on Claude Code (ToolSearch) and Claude Desktop (brute force). Blocked on Cursor (40 cap), marginal on Windsurf/Gemini. Server split is the only universal fix.

10. **Don't collapse tools into meta-tools.** Shifts "which tool?" to "which parameter?" -- LLMs are equally bad at both when option count is high. Every winning approach filters tools per turn, not reduces catalog.

### Action Items

| Priority | Action | Status |
|----------|--------|--------|
| Done | Description enrichment for bypass-prone tools | Shipped Mar 19 |
| Done | Docker rebuild after new tools | CI handles; documented |
| Do | Fix 3 structural test issues (qaqc, troubleshoot, energy-report) | Lifts all models to 97-98% |
| Do | Stronger Haiku system prompt ("always use MCP tools") | Addresses 4 no_mcp_tool failures |
| Do if needed | Profile-based server split for Cursor/Windsurf/OpenAI | Only for cross-client support |
| Watch | MCP Lazy Hydration (#1978), MCP-Zero pull model, `tools/list_changed` | Spec evolution |
| Don't | Sub-agent routing | All signals in "dynamic discovery OK" range |
| Don't | Further tool consolidation | Typed > generic, proven by L1 tests |

## Citations

### Academic
- RAG-MCP: arxiv:2505.03275 -- semantic retrieval for MCP tools
- MCP-Zero: arxiv:2506.01056 -- agent-pull model, hierarchical routing
- MCP Tool Descriptions Are Smelly: arxiv:2602.14878 -- 97.1% smell rate
- ToolTree: arxiv:2603.12740 (ICLR 2026) -- MCTS hierarchical planning
- AWO Meta-Tools: arxiv:2601.22037 -- composite tool bundling

### Industry
- Anthropic Advanced Tool Use: anthropic.com/engineering/advanced-tool-use
- Anthropic Tool Search docs: platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool
- GitHub Copilot fewer tools: github.blog/ai-and-ml/github-copilot/how-were-making-github-copilot-smarter-with-fewer-tools/
- Stacklok vs Tool Search: stacklok.com/blog/stackloks-mcp-optimizer-vs-anthropics-tool-search-tool
- Red Hat Tool2Vec: next.redhat.com/2025/12/05/a-practical-approach-to-smart-tool-retrieval
- Allen Chan tool count: achan2013.medium.com/how-many-tools-functions-can-an-ai-agent-has

### MCP Spec
- MCP Tools spec: modelcontextprotocol.io/specification/2025-06-18/server/tools
- SEP-1300 groups+tags (rejected): github.com/modelcontextprotocol/modelcontextprotocol/issues/1300
- #1978 Lazy Hydration: github.com/modelcontextprotocol/modelcontextprotocol/issues/1978
- Client capabilities: github.com/apify/mcp-client-capabilities

### Raw Data
- Sonnet sweep: `docs/sweeps/sonnet-2026-03-28/`
- Haiku sweep: `docs/sweeps/haiku-2026-03-28/`
- Opus sweep: `docs/sweeps/opus-2026-03-28/`
