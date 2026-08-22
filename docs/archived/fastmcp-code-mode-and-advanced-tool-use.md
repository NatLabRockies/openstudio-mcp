# FastMCP Code Mode & Anthropic Advanced Tool Use

Research compiled 2026-04-05. Covers FastMCP 3.1/3.2 releases, Anthropic's Advanced Tool Use blog, Code Execution with MCP blog, and community discussion.

---

## FastMCP 3.1 "Code to Joy" (2026-03-03)

### Code Mode (Experimental)

`CodeMode` transform replaces the full tool catalog with 3 meta-tools: **search** (BM25), **get_schemas**, **execute** (sandboxed Python). LLM discovers tools on-demand, writes Python chaining `call_tool()`, intermediate results never touch context.

```python
from fastmcp import FastMCP
from fastmcp.experimental.transforms.code_mode import CodeMode
mcp = FastMCP("Server", transforms=[CodeMode()])
```

- Existing tools unchanged -- CodeMode wraps them
- 3-stage default (search -> schemas -> execute), configurable to 2-stage or no-discovery
- Sandbox: Monty (Pydantic project), resource limits on time/memory/recursion
- No special client support needed -- meta-tools look like normal MCP tools
- Model requirement: Sonnet 4.6 works well, Haiku 4.5 makes errors

### Other 3.1 Features
- `SearchTools` transform available standalone (BM25 search without execution)
- `MultiAuth` for composing token verification sources
- Lazy-loaded heavy imports (faster startup)
- `search_result_serializer` hook for customizing search output

## FastMCP 3.2 "Show Don't Tool" (2026-03-30)

### FastMCPApp (Interactive UIs)
- `@app.ui()` renders charts/dashboards/forms inside conversations via Prefab (Python DSL -> React)
- Separates LLM-facing tools from backend tools
- Built-in providers: FileUpload, Approval, Choice, FormInput, GenerativeUI
- Dev server: `fastmcp dev apps` for browser preview

### Security Hardening
- SSRF/path traversal fixes, JWT algorithm restrictions, OAuth per-tool auth, CSRF protection
- `readOnlyHint=True` on ResourcesAsTools generated tools

### Notable for Us
- Fix: stale catalog in CodeMode execute
- `readOnlyHint=True` pattern — we should adopt for our read-only tools
- MCP conformance tests added to CI

---

## Anthropic Advanced Tool Use (API Features, Beta)

Three new API-level features (beta header: `advanced-tool-use-2025-11-20`):

### 1. Tool Search Tool
- `defer_loading: true` per tool — excluded from initial context, discovered via search
- Built-in regex + BM25 search, or custom embeddings
- Per-MCP-server config with per-tool overrides
- Doesn't break prompt caching
- **85% token reduction** (77K -> 8.7K for 50+ tools)
- Accuracy: Opus 4 49%->74%, Opus 4.5 79.5%->88.1%
- Threshold: use when >10 tools or >10K tokens in definitions

### 2. Programmatic Tool Calling (PTC)
- Claude writes Python orchestration; intermediate tool results stay in sandbox
- `allowed_callers: ["code_execution_20250825"]` opts tools in
- Only final `stdout` enters context
- **37% token reduction** on complex tasks
- Best for: large datasets needing aggregates, 3+ dependent tool calls, parallel operations
- `caller` field in tool requests identifies PTC calls vs direct

### 3. Tool Use Examples
- `input_examples` array in tool definitions
- **72%->90% accuracy** on complex parameter handling
- Shows format conventions, optional parameter correlations, nested structure patterns
- Best for: complex schemas, many optional params, domain-specific conventions

### Best Practices from Anthropic
- Layer features: context bloat -> Tool Search; large intermediate results -> PTC; parameter errors -> Examples
- Keep 3-5 most-used tools always loaded, defer rest
- Document return formats clearly for PTC (Claude writes parsing code)
- Realistic example data (not "string" or "value")

---

## Anthropic Code Execution with MCP (Nov 2025)

Earlier blog establishing the code-as-API pattern:
- Tools as filesystem: `./servers/google-drive/getDocument.ts` — agent browses filesystem to discover
- **98.7% token reduction** (150K -> 2K)
- Progressive disclosure: `search_tools` with detail level parameter (name-only, name+description, full schema)
- Context-efficient results: filter/aggregate in code before returning to model
- Privacy-preserving: intermediate data never enters model context
- State persistence: agents save code as reusable skills (`SKILL.md` pattern = our skills system)

---

## Community Token Economics (Reddit r/mcp)

| Setup | Before Code Mode | After Code Mode | Reduction |
|-------|-----------------|-----------------|-----------|
| Amazon Ads MCP (top 5 tools) | 34K tokens upfront | ~600 tokens/workflow | 98.2% |
| Generic 50K setup (u/No_More_Fail) | 50K tokens | 2-3K tokens | 95% |
| 5-server setup (Anthropic) | 55K tokens | 8.7K tokens | 85% |
| Cloudflare (1000 endpoints) | ~1M tokens | ~1K tokens | 99.9% |
| openstudio-mcp (142 tools) | ~57K tokens | ~600-3K est. | ~95% est. |

Key community insights:
- Code mode reduces "half-plans" where model commits to wrong tool too early
- Multi-server: compose servers in FastMCP, then wrap outer with CodeMode
- Legacy backends: use API gateway (Kong, Tyk) to flatten surface before MCP
- Client-side code mode requested but not yet available

---

## Impact on openstudio-mcp

### Current State
- FastMCP 3.0.2 installed (`fastmcp>=0.4.0` in pyproject.toml)
- 142 tools, ~57K tokens of definitions
- Claude Code ToolSearch already defers our tools (>10K threshold)
- Skills system = hand-crafted progressive disclosure

### Upgrade Path: FastMCP 3.1+ Code Mode

**What it gives us:**
- One-line addition: `transforms=[CodeMode()]` wraps all 142 tools
- 3 meta-tools replace 142 tool definitions in context (~95% token reduction)
- Sandboxed execution: agent writes Python to chain our tools, intermediate results (timeseries data, zone lists, component properties) stay out of context
- No tool code changes needed

**Concerns:**
- Experimental status
- Haiku-class models struggle with it (we sometimes target haiku)
- Sandbox security for code execution on MCP server side
- Our tools already work well with ToolSearch — incremental benefit unclear
- Breaking change in 3.2: app tool calls route via `___`-prefixed names

### API-Level Features (for API users, not Claude Code)

| Feature | Effort | Impact | Notes |
|---------|--------|--------|-------|
| `input_examples` on complex tools | Low | High | Add to ~15 tools with complex params |
| `defer_loading` per-tool config | None (client-side) | High | API users can defer our 142 tools |
| PTC `allowed_callers` | Low | High | Mark read-only data tools as PTC-compatible |
| Description quality for search | Already done | Maintained | Our descriptions are keyword-rich |

### Recommended Actions

1. **Now:** Add `input_examples` to top 15 complex tools (works with current FastMCP)
2. **Soon:** Upgrade to FastMCP 3.1+, test CodeMode with our integration tests
3. **Soon:** Mark data-heavy read tools as PTC `allowed_callers` compatible
4. **Watch:** FastMCP 3.2 Apps — potential for simulation result visualization
5. **Watch:** Client-side code mode — would help Claude Desktop users with our server

---

## Sources

- [Anthropic: Advanced Tool Use](https://www.anthropic.com/engineering/advanced-tool-use)
- [Anthropic: Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
- [FastMCP 3.1.0 Release](https://github.com/PrefectHQ/fastmcp/releases/tag/v3.1.0)
- [FastMCP 3.2.0 Release](https://github.com/PrefectHQ/fastmcp/releases/tag/v3.2.0)
- [Reddit: Stop Calling Tools, Start Writing Code Mode](https://www.reddit.com/r/mcp/comments/1rkx4pa/)
- [FastMCP Code Mode Blog](https://www.jlowin.dev/blog/fastmcp-3-1-code-mode)
- [FastMCP Code Mode Docs](https://gofastmcp.com/servers/transforms/code-mode)
- [Cloudflare Code Mode Blog](https://blog.cloudflare.com/code-mode/)
