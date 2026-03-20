# Tool Discovery & Lazy Loading Research

**Date:** 2026-03-19
**Context:** 142 MCP tools causing LLM tool selection degradation (FM1)

## Problem (Resolved)

RAG-MCP paper (arxiv:2505.03275) shows selection accuracy drops to 13.6%
at 100+ tools. Initially our LLM tests couldn't discover new tools —
root cause was stale Docker image (ToolSearch indexes at build time).
After Docker rebuild + enriched descriptions, all tools discoverable.
LLM tests 12/12 pass.

## Approaches Investigated

### 1. Anthropic Tool Search (`defer_loading`) — Most Promising

Mark tools with `defer_loading: true` — excluded from initial context.
Claude sees only a built-in "Tool Search Tool" (~500 tokens) + always-loaded
tools. When it needs a capability, it searches tool names/descriptions/arg
names and loads matched tools (typically 3-5) into context.

**Results from Anthropic benchmarks:**
- 85% context reduction
- Opus 4: 49% → 74% accuracy
- Opus 4.5: 79.5% → 88.1% accuracy

**MCP integration:**
```json
{
  "mcpServers": {
    "openstudio": {
      "command": "openstudio-mcp",
      "toolConfiguration": {
        "default_config": { "defer_loading": true },
        "configs": {
          "load_osm_model": { "defer_loading": false },
          "save_osm_model": { "defer_loading": false }
        }
      }
    }
  }
}
```

**Status:** Need to test if Claude Desktop/Code support `defer_loading`
for MCP servers. Works for direct API calls.

Sources:
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool
- https://www.anthropic.com/engineering/advanced-tool-use
- https://unified.to/blog/scaling_mcp_tools_with_anthropic_defer_loading

### 2. FastMCP Namespace Activation (v3.x)

Tags + `mcp.disable(tags={"hvac"})` at init hides tools from `tools/list`.
Agent calls activation tool → `ctx.enable_components(tags={"namespace:hvac"})`
→ tools appear. Sends `tools/list_changed` notification automatically.

```python
server = FastMCP("openstudio-mcp")

@server.tool(tags={"namespace:hvac"})
def add_baseline_system(...): ...

@server.tool
async def activate_hvac(ctx: Context) -> str:
    await ctx.enable_components(tags={"namespace:hvac"})
    return "HVAC tools activated"

server.disable(tags={"namespace:hvac"})  # hidden at init
```

**Problem:** Claude Desktop and Claude Code do NOT support
`tools/list_changed` notification. Hidden tools stay hidden forever.

**Client support for `tools/list_changed`:**
- Supported: Cursor, VS Code Copilot, Windsurf, Glama, Kilo Code
- NOT supported: Claude Desktop, Claude Code, Cline, Claude.ai

Source: github.com/apify/mcp-client-capabilities

### 3. LlamaIndex ObjectIndex + ToolRetriever

Embed tool descriptions into VectorStoreIndex. At query time, retrieve
top-k most relevant tools via cosine similarity. Only those signatures
get passed to the LLM.

```python
from llama_index.core.objects import ObjectIndex
obj_index = ObjectIndex.from_objects(all_tools, index_cls=VectorStoreIndex)
agent = FunctionAgent(
    tool_retriever=obj_index.as_retriever(similarity_top_k=5),
    llm=llm
)
```

Not applicable for MCP servers (no control over client-side tool injection).
Useful if building a custom agent that calls MCP tools programmatically.

### 4. Multi-Agent Routing (LangChain/CrewAI/AutoGen)

Router LLM classifies query into domain → sub-agent with 5-10 tools handles
it. Each sub-agent sees only its domain's tools.

High effort, requires architecture change. Not applicable to single MCP
server serving Claude Desktop.

### 5. Semantic Router MCP (openclaw-mcp-router)

Single MCP gateway that:
1. Indexes all tools from downstream MCP servers (embeddings in LanceDB)
2. Exposes `mcp_search(query)` returning top-K relevant tools
3. Exposes `mcp_call(tool_name, params)` to execute

Replaces tens of thousands of schema tokens with 5-tool search results.
Interesting but adds infrastructure complexity.

### 6. Tool Consolidation

Merge related tools to reduce count. e.g. all `extract_*` into one with
a `what` parameter. Reduces tool count but loses discoverability of
specific capabilities.

## RAG-MCP Paper Key Numbers

| Tool Pool Size | Selection Accuracy |
|---------------|-------------------|
| ≤30 tools | >90% |
| 31-70 tools | Degraded (semantic overlap) |
| 100+ tools | 13.6% (baseline), 43% (with retrieval) |

## What We Built (Phases 1-3)

- `recommend_tools` meta-tool: keyword routing to 9 groups
- Tags on all 142 tools
- Docstring hardening for bypass-prone tools
- `search_api` + `search_wiring_patterns` for HVAC measure authoring

**Result:** 96.5% pass rate on existing tests (no regression). New tools
are discoverable via ToolSearch after Docker rebuild. LLM tests 12/12 pass.

## Claude Code ToolSearch Testing (2026-03-19)

Claude Code has `ENABLE_TOOL_SEARCH` (default: auto at 10% context threshold).
When active, MCP tools are deferred and discovered via ToolSearch.

**Test results with `ENABLE_TOOL_SEARCH=true`:**

| ToolSearch Query | Found our tool? | What it found instead |
|-----------------|----------------|----------------------|
| "search_api" | NO | "No matching deferred tools found" |
| "search" | NO | WebSearch, ExitPlanMode, TodoWrite |
| "api reference" | NO | WebFetch, TodoWrite, WebSearch |
| "SDK classes methods" | NO | LSP, create_measure, get_object_fields |
| "search_wiring" | NO | (empty) |
| "HVAC wiring recipe" | NO | list_zone_hvac_equipment, get_zone_hvac_details |
| "wiring patterns" | NO | create_measure (docstring mentions wiring) |

**Conclusion:** ToolSearch cannot find `search_api` or `search_wiring_patterns`
with any query. The deferred tool mechanism works (ToolSearch runs, finds other
MCP tools like `create_measure` and `get_object_fields`) but our new tools are
invisible to it. Possible causes:
- Tool descriptions not matching ToolSearch's internal index/embedding
- Tool names with underscores may not tokenize well for matching
- ToolSearch may prioritize tools with longer/richer descriptions

**Root cause found:** ToolSearch indexes tools at Docker image build time.
Volume-mounted code registers new tools at runtime, but ToolSearch's index
is stale. **Docker rebuild fixes everything.**

After `docker build`:

| Query | Finds tool? | Position |
|-------|------------|----------|
| "search_api" | search_api | 1st |
| "SDK methods" | search_api | 1st |
| "wiring patterns" | search_wiring_patterns | 1st |
| "four pipe beam wiring" | search_wiring_patterns | 1st |
| "HVAC recipe" | search_wiring_patterns | 4th |
| "recommend tools" | recommend_tools | 1st |

Enriched descriptions also helped — added use cases, examples, and
keyword-rich text to match likely search queries.

## Recommendation

1. **ToolSearch works** — all tools discoverable after Docker rebuild
   with enriched descriptions
2. **Always rebuild Docker** after adding new tools (CI does this already)
3. **Enriched descriptions matter** — include use cases, examples, and
   keywords that match natural language queries
4. **LLM tests pass** — 12/12 after rebuild (including search_api + search_wiring_patterns discovery)
5. **Phase 4 (lazy loading) not needed** — ToolSearch handles the
   discovery problem when properly indexed
