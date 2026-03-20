# Development Process Findings: MCP Tool Discovery at Scale

**Project:** openstudio-mcp — MCP server for building energy modeling (OpenStudio SDK)
**Period:** Feb 18 – Mar 20, 2026 (31 days)
**Tool count:** 62 → 142 tools across 22 skills

## Timeline of Key Decisions

| Date | Commit | Decision | Rationale | Outcome |
|------|--------|----------|-----------|---------|
| Feb 18 | `5ef23ad` | Initial commit | — | 62 tools |
| Mar 2 | `f59f354` | Input hardening, HVAC auto-wiring | Security + usability | +4 tools (126) |
| **Mar 4** | **`a78d308`** | **Compress all tool descriptions ~30%** | Reduce context consumption (tool schemas ~100K chars) | Descriptions stripped of field lists, examples, educational text |
| Mar 4 | `884d371` | Release v0.4.0 | — | 127 tools |
| Mar 6 | `8b253fc` | Server instructions: NEVER/ALWAYS guardrails | Agent bypassing MCP tools for scripts | 6-domain anti-bypass rules |
| Mar 6 | `e9ad087` | First LLM agent test suite | Need automated verification of tool selection | 50 tests, 44% pass rate |
| Mar 7-8 | `40c8534` | LLM test improvements | System prompt + description fixes | 44% → 91% pass rate |
| Mar 10-12 | `65bee92` | Generic object access tools | Reduce tool count via universal tools | +3 generic tools (list_model_objects, get_object_fields, set_object_property) |
| **Mar 12** | **`cbfba81`** | **Remove 6 redundant typed list tools** | Generic tools replace them | 142 → 136 tools |
| Mar 12 | `feab46e` | Expand LLM tests to 159 | Progressive L1/L2/L3 framework | 96.2% pass rate |
| Mar 13 | `7e79c7c` | Measure authoring guardrails | Agent writing raw measure.rb files | Quote escaping, syntax validation |
| Mar 16 | — | Debug session: WSHP measure authoring failure | Agent hallucinated API methods, ignored MCP tools | Triggered tool routing plan |
| **Mar 19** | **`39d7608`** | **Add tags to all 141 tools, build recommend_tools** | RAG-MCP paper: 13.6% accuracy at 100+ tools | Tags inert (not in MCP spec), recommend_tools works |
| Mar 19 | — | Discover ToolSearch exists in Claude Code | Testing ENABLE_TOOL_SEARCH | Already enabled since Jan 14 |
| **Mar 19** | **`c09d6ee`** | **Enrich search_api + search_wiring_patterns descriptions** | ToolSearch matches on keywords in descriptions | Both tools go from invisible → 1st result |
| Mar 20 | `cdf4243` | Full regression: 164/171 (95.9%) | Verify no regressions from all changes | All failures known flaky |
| Mar 20 | — | Research: tags do nothing, descriptions are everything | Tags not in MCP spec, never sent to clients | Plan pivot: enrich descriptions, not consolidate |

## Lesson 1: Description Compression Was Counterproductive

**What we did (Mar 4):** Compressed all 127 tool descriptions by ~30%.
Stripped field lists, examples, return value descriptions, educational text.

**Why:** Tool schemas consumed ~100K chars (~25K tokens). Believed this
was causing tool selection degradation.

**What we didn't know:** Claude Code's ToolSearch had been shipping since
**Jan 14, 2026** (v2.1.7) — 7 weeks before our compression. ToolSearch
auto-defers MCP tools when schemas exceed 10% of context, presenting only
tool names + descriptions for keyword matching. The full schemas are loaded
on-demand only when a tool is selected.

**The irony:** By compressing descriptions, we reduced the very keywords
ToolSearch uses to match tools. We optimized for a problem (context size)
that ToolSearch had already solved, while creating a new problem (discovery).

**Evidence:**
- `search_api` with short description: invisible to ToolSearch with any query
- `search_api` with enriched description (use cases, examples, keywords):
  found 1st for "search_api", "SDK methods", "verify method exists"
- Same tool, same functionality — only the description changed

**Quantified impact:**
- Pre-compression: ~100K chars tool descriptions
- Post-compression: ~60K chars (40% reduction)
- With ToolSearch: context impact is ~500 chars (just the search tool) +
  loaded-on-demand schemas. The 40% reduction saved nothing.

## Lesson 2: Tags Are Inert Metadata

**What we did (Mar 19):** Added `tags={"core"}`, `tags={"hvac"}`, etc. to
all 141 tools. Built `recommend_tools` meta-tool for keyword routing.

**What we discovered:**
- `tags` is a FastMCP server-side feature, NOT part of the MCP wire protocol
- Tags are never sent from server to client in `tools/list` responses
- No client (Claude Desktop, Claude Code, Cursor, Windsurf, Gemini CLI)
  reads or acts on tags
- ToolSearch does not use tags in its matching algorithm
- The only use is server-side `mcp.disable(tags=...)` / `mcp.enable()`
  which requires `tools/list_changed` notification support — not available
  in Claude Desktop or Claude Code

**What actually works:** Tool names and descriptions. ToolSearch matches
against these. Rich descriptions with domain keywords are the mechanism.

**Tags are kept** for future-proofing — the MCP spec or clients may add
tag support. But today they provide zero discovery benefit.

## Lesson 3: Typed Tools Are More Discoverable Than Generic Tools

**What we did (Mar 12):** Built generic tools (`list_model_objects`,
`get_object_fields`, `set_object_property`) and removed 6 typed list tools
that were redundant (Phase C).

**What we learned:** The generic tools are powerful but less discoverable.
An energy modeler searching for "list spaces" will find `list_spaces` via
ToolSearch but may not find `list_model_objects("Space")` because the
generic tool's description doesn't mention specific type names.

**Evidence from LLM tests:**
- `list_spaces_L1` (typed): PASS — LLM finds it with vague prompt
- `list_dynamic_type_L1` (generic): FAIL — LLM uses sizing tools instead
  of `list_model_objects` when prompt says "What sizing parameters?"

**Implication:** Don't consolidate typed tools further. The remaining typed
tools serve as discoverable entry points for common operations. The generic
tools serve as fallbacks for uncommon types.

## Lesson 4: ToolSearch Indexes at Docker Build Time

**What we discovered (Mar 19):** New tools added via volume-mounted code
(not baked into the Docker image) were invisible to ToolSearch. After
`docker build`, the same tools became discoverable.

**Root cause:** ToolSearch indexes tool schemas when the MCP server first
connects. Tools registered at Python import time (from installed package
in Docker image) are indexed. Tools registered from volume-mounted code
are also registered at runtime but ToolSearch's index may cache from the
image's installed package.

**Practical impact:** After adding any new MCP tool, Docker image MUST be
rebuilt. CI does this automatically. Local development requires manual
`docker build`.

## Lesson 5: Server Instructions Are the Biggest Lever

**What we did (Mar 6):** Added server instructions with NEVER/ALWAYS rules
for 6 domains (measures, results, visualization, models, weather, HVAC).

**Impact:** LLM test pass rate jumped from 44% → 83% in one run.
Description improvements and tool-level fixes added another ~8% (to 91%).

**Evidence:**
| Run | Date | Tests | Pass Rate | Key Change |
|-----|------|-------|-----------|------------|
| 1 | Mar 5 | 50 | 44% | Baseline (no system prompt) |
| 2 | Mar 6 | 90 | 83% | + server instructions |
| 3 | Mar 7 | 90 | 91% | + description fixes |
| 5 | Mar 10 | 107 | 96% | + generic access tests |
| 7 | Mar 12 | 159 | 97.5% | Test consolidation |
| 10 | Mar 19 | 172 | 96.5% | + tool routing (no regression) |
| 11 | Mar 20 | 171 | 95.9% | + ToolSearch + wiring recipes |

The 44% → 83% jump from server instructions alone dwarfs all subsequent
improvements combined. Server-level guidance is more impactful than
tool-level description optimization.

## Lesson 6: Progressive Prompt Testing Reveals Structural Limits

**What we built (Mar 12):** Progressive test framework — each tool tested
at L1 (vague), L2 (moderate), L3 (explicit) prompt specificity.

**Key finding:** L3 is 100% across all 42 cases. L1 failures are structural
— the prompt is genuinely too vague to determine the right tool. These are
not fixable by tool count reduction, description enrichment, or any
server-side change.

**Examples of structural L1 failures:**
- "What sizing parameters?" → uses `get_sizing_zone_properties` (explicit)
  instead of `list_model_objects` (generic). Reasonable behavior.
- "What loads?" → uses `get_space_details` instead of `get_load_details`.
  The prompt doesn't specify what kind of loads.
- "Change thermostat settings" → multiple valid tools. LLM picks one.

**Implication:** ~90% L1 pass rate is likely the ceiling for 142 tools
with current MCP architecture. The remaining 10% are ambiguous prompts
where multiple tools are reasonable choices.

## Lesson 7: Cross-Client Compatibility Is the Real Constraint

**Discovery:**
| Client | Tool Limit | Discovery Mechanism |
|--------|-----------|-------------------|
| Claude Code | Unlimited (ToolSearch) | Auto-defer at 10% context |
| Claude Desktop | Unlimited | None (all tools in context) |
| Cursor | 40 hard cap | None |
| Windsurf | 100 | Per-tool toggle |
| OpenAI | 128 (recommends ~10) | defer_loading |
| Gemini CLI | 100 soft / 512 API | includeTools/excludeTools |

Our 142 tools work on Claude Code (ToolSearch) and Claude Desktop (brute
force). They're blocked on Cursor and marginal on Windsurf/Gemini.

**No cross-client standard exists.** Each client implements discovery
differently or not at all. The only universal approach is reducing tool
count or splitting into multiple servers.

## Key Metrics

### Tool Schema Size Over Time
| Date | Tools | Schema Chars | Est. Tokens |
|------|-------|-------------|-------------|
| Feb 18 | 62 | ~30K | ~7.5K |
| Mar 2 | 126 | ~100K | ~25K |
| Mar 4 (pre-compress) | 127 | ~100K | ~25K |
| Mar 4 (post-compress) | 127 | ~60K | ~15K |
| Mar 12 | 136 | ~55K | ~14K |
| Mar 19 | 142 | ~61K | ~15K |

### LLM Test Pass Rate Over Time
| Run | Date | Tests | Pass Rate | Primary Change |
|-----|------|-------|-----------|---------------|
| 1 | Mar 5 | 50 | 44.0% | Baseline |
| 2 | Mar 6 | 90 | 83.3% | Server instructions |
| 3 | Mar 7 | 90 | 91.1% | Description fixes |
| 4 | Mar 7 | 90 | 93.3% | Stability run |
| 5 | Mar 10 | 107 | 96.3% | Generic access tests |
| 6 | Mar 11 | 159 | 96.2% | Progressive expansion |
| 7 | Mar 12 | 159 | 97.5% | Test consolidation |
| 8 | Mar 13 | 25 | 92.0% | Measure authoring (separate) |
| 9a | Mar 19 | 9 | 100% | Tool routing baseline |
| 9b | Mar 19 | 9 | 100% | Post-docstring hardening |
| 10 | Mar 19 | 172 | 96.5% | Full regression (tool routing) |
| 11 | Mar 20 | 171 | 95.9% | Full suite with ToolSearch |

### ToolSearch Discovery Rate
| Condition | Discoverable | Not Found |
|-----------|-------------|-----------|
| Short descriptions (pre-enrichment) | ~110/142 | ~32/142 |
| search_api (before enrichment) | 0 queries matched | All queries missed |
| search_api (after enrichment) | "search_api" → 1st, "SDK methods" → 1st | — |
| After Docker rebuild | All 142 tools indexed | 0 missing |

## Research Citations

See [research-tool-discovery-at-scale.md](research-tool-discovery-at-scale.md)
for comprehensive industry survey (13 papers, 30+ projects, empirical benchmarks).

### Tool Overload
- RAG-MCP (arxiv:2505.03275): 100+ tools → 13.6% accuracy, semantic
  retrieval → 43%. Sweet spot ≤30 tools (>90%).
- VS Code Copilot: embedding routing, 40→13 core tools, 94.5% coverage.
  https://github.blog/ai-and-ml/github-copilot/how-were-making-github-copilot-smarter-with-fewer-tools/
- MCP context overload analysis:
  https://eclipsesource.com/blogs/2026/01/22/mcp-context-overload/

### Anthropic Tool Search
- Advanced Tool Use blog (Nov 24, 2025):
  https://www.anthropic.com/engineering/advanced-tool-use
- Tool Search API docs:
  https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool
- Claude Code ToolSearch: shipped v2.1.7 (Jan 14, 2026), auto at 10% context
- ENABLE_TOOL_SEARCH env var: auto (default), true, false, auto:N%

### MCP Spec & Tags
- MCP Tool schema: name, description, inputSchema, annotations. No tags field.
- FastMCP tags: server-side only, enable/disable mechanism
- tools/list_changed: NOT supported by Claude Desktop or Claude Code
  https://github.com/apify/mcp-client-capabilities

### Client Limits
- Cursor 40-tool cap:
  https://forum.cursor.com/t/request-increase-mcp-tools-limit/108637
- Windsurf 100-tool limit:
  https://docs.windsurf.com/windsurf/cascade/mcp
- OpenAI 128 limit + defer_loading:
  https://developers.openai.com/api/docs/guides/tools-tool-search
- Gemini CLI 100/512:
  https://github.com/google-gemini/gemini-cli/issues/21823

### Proxy/Router Patterns
- Portkey mcp-tool-filter (embedding proxy):
  https://github.com/Portkey-AI/mcp-tool-filter
- openclaw-mcp-router: LanceDB embeddings + mcp_search/mcp_call gateway
- Redis solving MCP tool overload:
  https://redis.io/blog/from-reasoning-to-retrieval-solving-the-mcp-tool-overload-problem/

## PR History (Supporting Data)

| PR | Date | Title | Tools Before → After |
|----|------|-------|---------------------|
| #2 | Feb 19 | SWIG memory leak fix | 62 |
| #5 | Feb 22 | Claude Code skills | 62 → 64 |
| #8 | Mar 3 | Input hardening + HVAC auto-wiring | 64 → 126 |
| #18 | Mar 4 | Context reduction (description compression) | 126 → 127 |
| #33 | Mar 12 | Generic access + Phase C tool removal | 127 → 136 |
| #36 | Mar 13 | Measure authoring + cooled beam | 136 → 139 |
| #37 | Mar 14 | Test consolidation | 139 |
| #38 | Mar 16 | Merge develop | 139 |
| (optimize, not yet merged) | Mar 19-20 | Tool routing + wiring recipes | 139 → 142 |
