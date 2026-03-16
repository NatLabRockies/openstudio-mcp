# Plan: MCP Tool Routing — Prevent LLM Bypass of MCP Tools

**Date:** 2026-03-16
**Branch:** optimize
**Depends on:** plan-agent-guardrails.md (completed fixes)

## Problem

When Claude Desktop users upload files (e.g. eplusout.err), Analysis mode
activates. The LLM uses Analysis sandbox tools (`bash_tool`, `create_file`)
instead of MCP tools — even though 138 MCP tools are connected and the
server instructions explicitly say "NEVER write scripts."

**Confirmed:** MCP server connected, sent updated instructions with all
guardrails, listed 138 tools. LLM made ZERO `tools/call` requests. Used
Analysis mode exclusively. Server instructions were present and ignored.

This is not unique to Claude Desktop. ChatGPT has the same pattern with
Code Interpreter vs GPT Actions. It's a fundamental **tool routing** problem
that gets worse with more tools.

## Industry Research

### RAG-MCP (arxiv:2505.03275)
- With 100+ tools, tool schemas consume 50-80% of context
- Selection accuracy drops to 13.6% baseline
- Fix: semantic retrieval pre-filters tools before LLM sees them
- Result: 50% fewer prompt tokens, 3x accuracy (43% vs 13.6%)
- Key insight: decouple tool discovery from generation
- GitHub: github.com/memoverflow/rag-mcp, github.com/fintools-ai/rag-mcp

### MCP-Flow (OpenReview, 2026)
- Automated pipeline for large-scale MCP server discovery
- 1166 servers, 11536 tools benchmarked
- Drives superior tool selection via data synthesis

### Tool-to-Agent Retrieval (arxiv:2511.01854)
- Embeds tools + agents in shared vector space
- Enables granular tool-level retrieval by semantic similarity
- Query "create a measure" → retrieves `create_measure` directly

### Industry Consensus
- Fewer tools = more reliable selection (LlamaIndex, Elasticpath)
- Playbook agents with 5-10 tools outperform agents with 100+ tools
- Router Model pattern: pre-filter tool group, then present subset
- Over-subscription of tools is a scaling concern (The New Stack, 2026)

## Current State

### What we have
- 138 MCP tools exposed at init (all sent in `tools/list` response)
- Server instructions with explicit "NEVER write scripts" guardrails
- No tool annotations (all tools have `_meta.fastmcp.tags: []`)
- No tool grouping or lazy loading
- FastMCP 3.1.1 supports `annotations` parameter on `@mcp.tool()`

### FastMCP Annotation Support (confirmed)
```python
from mcp.types import ToolAnnotations

@mcp.tool(
    name="create_measure",
    annotations=ToolAnnotations(
        title="Create Custom Measure",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    tags={"measure_authoring", "creation"},
)
```

FastMCP `@mcp.tool()` accepts:
- `annotations: ToolAnnotations(...)` — MCP protocol hints
- `tags: set[str]` — categorization (already in protocol output as `_meta.fastmcp.tags`)
- `meta: dict` — custom metadata

**Note:** MCP spec defines `priority` as a field but ToolAnnotations may
not expose it directly. Need to verify if FastMCP passes custom fields
through `meta` or if we need to patch the tool list response.

## Proposed Solutions

### Option 1: Tool Annotations (low effort, uncertain impact)

Add `annotations` and `tags` to all 138 tools. Categorize by skill,
mark read-only vs destructive, add priority hints.

**Implementation:**
1. Define tag taxonomy matching skill names:
   `model_creation`, `model_management`, `hvac_systems`, `results`,
   `measure_authoring`, `geometry`, `simulation`, `common_measures`, etc.

2. Add annotations to high-value "creation" tools that compete with
   Analysis mode:
   ```python
   @mcp.tool(
       name="create_measure",
       tags={"measure_authoring", "creation"},
       annotations=ToolAnnotations(
           title="Create Custom OpenStudio Measure",
           readOnlyHint=False,
           destructiveHint=False,
           idempotentHint=True,
       ),
   )
   ```

3. Add `readOnlyHint=True` to all query/list/extract tools.

**Pros:** Simple to implement, follows MCP spec, no architecture change.
**Cons:** Claude Desktop may not use annotations for routing decisions.
Annotations are "hints" — advisory, not enforced. May have zero impact
on Analysis mode bypass.

**Effort:** ~2 hours (mechanical changes across 23 tools.py files)
**Files:** all `mcp_server/skills/*/tools.py`

### Option 2: Tool Grouping / Lazy Loading (high effort, high impact)

Instead of listing all 138 tools at init, expose a small set of
"router" tools that discover and load specific tool groups on demand.

**Architecture:**
```
Init: expose ~10 meta-tools only
  discover_tools(task: str) → returns relevant tool subset
  list_tool_groups() → returns skill categories
  load_tool_group(group: str) → dynamically registers tools

User: "Create a measure to fix OA warnings"
  LLM calls discover_tools("create measure fix warnings")
  Server returns: create_measure, test_measure, edit_measure, apply_measure
  LLM calls create_measure(...)
```

**Implementation approaches:**

A. **RAG-based discovery** — embed all 138 tool descriptions in a vector
   index. `discover_tools(query)` does semantic search, returns top-k
   tools. Requires embedding model (local or API).

B. **Keyword/tag-based discovery** — `discover_tools(query)` does
   keyword matching against tool names, descriptions, and tags. No
   embedding model needed. Less accurate but zero dependencies.

C. **FastMCP dynamic tool registration** — use `mcp.tool()` at runtime
   to register/unregister tools. Requires FastMCP `tools/list_changed`
   notification support (already in capabilities).

D. **Tool group presets** — hardcode ~10 tool groups matching skills.
   `load_tool_group("measure_authoring")` registers those 4 tools.
   Simple, deterministic, no ML.

**Pros:** Directly addresses the 138-tool problem. Proven by RAG-MCP
research (3x accuracy improvement). Reduces context consumption.
**Cons:** Significant architecture change. Adds a discovery step to
every conversation. May break existing workflows that assume all tools
are available. Needs careful testing.

**Effort:** 1-3 days depending on approach
**Files:** `mcp_server/server.py`, `mcp_server/skills/__init__.py`,
new `mcp_server/tool_router.py`

### Option 3: Hybrid (recommended)

Combine both: add annotations now (quick win), then implement tool
grouping as a follow-up.

**Phase 1 (now):** Add annotations + tags to all tools. Test whether
Claude Desktop respects them for routing.

**Phase 2 (if Phase 1 insufficient):** Implement Option 2D (tool group
presets) as simplest lazy-loading approach. Keep all tools registered
but add a `recommend_tools(task)` meta-tool that returns the relevant
subset with descriptions. The LLM can still call any tool directly,
but the recommendation narrows its focus.

**Phase 3 (if Phase 2 insufficient):** Implement Option 2A (RAG-based
discovery) for semantic matching. This is the nuclear option — highest
accuracy but most complex.

## Analysis Mode Gap (not fixable from MCP side)

The file upload → Analysis sandbox → bash_tool momentum pattern cannot
be fixed by MCP server changes alone. Even with perfect tool routing,
if the LLM starts in Analysis mode it may never check MCP tools.

**Mitigations (user-side):**
1. Place files in `/inputs` mount (host: `tests/assets/`) instead of
   uploading — MCP tools can read them via `read_file`
2. Paste file content as text in chat instead of uploading
3. After Analysis reads a file, explicitly prompt: "Now use the
   openstudio-mcp create_measure tool"
4. For large files, use host mount. For small content, paste directly.

**Mitigations (requires Claude Desktop changes):**
- Analysis mode should check for relevant MCP tools before using
  built-in tools for creation/authoring tasks
- MCP servers should declare "claim" over task categories
- File uploads should be mountable into MCP containers

## Decision Needed
- Start with Option 1 (annotations) alone, or go straight to Option 3 hybrid?
- For Option 2, which approach (A/B/C/D)?
- Should `recommend_tools` be a required first step or optional hint?
