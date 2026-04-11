# MCP Best Practices: Research & Gap Analysis

*March 2026 — based on MCP spec 2025-11-25, industry survey, codebase audit*

---

## Executive Summary

openstudio-mcp is the largest simulation-engine MCP server in production (142 tools, 26 skills). It leads peers in testing rigor (480+ integration tests, LLM agent tests, 5-shard CI) and HVAC mutation depth. Key gaps: no tool annotations, no async tasks for simulation, no structured output, and all 142 tool schemas ship to every client on connect (~60K tokens). The highest-value changes are tool annotations (low effort, immediate UX gains) and progressive tool discovery (high effort, 90%+ token reduction).

---

## 1. Comparable MCP Servers

### Building Energy Modeling

| Project | Tools | Transport | State | Testing | MCP Features |
|---------|-------|-----------|-------|---------|-------------|
| **openstudio-mcp** | 142 | stdio | global in-memory singleton | 480+ integration, LLM agent, 5-shard CI | tools, 6 prompts, 4 resources |
| **EnergyPlus-MCP** (LBNL) | 35 | stdio | file-based (IDF path) | MCP Inspector only | tools only |
| **BEM-AI** (PNNL) | ~6 per server | SSE (A2A) | shared blackboard | TBD | A2A + MCP hybrid |

**Key takeaway**: We have 4x the tools of EnergyPlus-MCP, the only HVAC mutation tools in the BEM space, and dramatically better test coverage. BEM-AI wraps us via A2A — validates our tool API surface. EnergyPlus-MCP is stateless (file-based), which scales horizontally more easily.

### Engineering / CAD / Scientific Computing

| Project | Tools | Notable Pattern |
|---------|-------|-----------------|
| **STK-MCP** (Ansys) | 3 tools + 5 resources | Uses MCP Resources for query state; HTTP transport |
| **Fusion 360 MCP** | 3 tools, 3 resources, 2 prompts | Only project using all 3 MCP primitives |
| **MATLAB MCP** (MathWorks) | 5 | Official vendor server; Go implementation; lazy MATLAB init |
| **Jupyter MCP** (Datalayer) | 20+ | Streamable HTTP + stdio; multi-notebook sessions |
| **Revit MCP** | 24 | WebSocket bridge to desktop app; most mature BIM MCP |
| **Blender MCP** | ~10 | TCP socket bridge to Blender addon |
| **OpenFOAM MCP** | 12 | Socratic questioning; user expertise tracking |
| **FEA-MCP** | 10 | Unified API across ETABS + LUSAS backends |
| **mcp.science** | 12 servers | Federated: many small single-purpose servers |

**Key takeaway**: Almost no peer uses MCP resources, prompts, or sampling. STK-MCP and Fusion 360 are exceptions. Most have no formal test suites. We're ahead on feature breadth but behind on MCP spec feature adoption.

---

## 2. Best Practices Inventory

### 2.1 Tool Annotations

**Best practice**: Every tool should declare `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`. Clients use these for auto-approval (skip confirmation for read-only tools from trusted servers), confirmation dialogs (destructive), and safe retries (idempotent).

**Spec reference**: Tool annotations added 2025-03-26; blog post 2026-03-16.

**Our status**: **NOT IMPLEMENTED.** Zero annotations on 142 tools. All tools default to `destructiveHint=true, readOnlyHint=false` — meaning clients like Claude Desktop prompt for confirmation on every call, even `list_thermal_zones`.

**Impact**: High — immediate UX improvement in Claude Desktop, VS Code, and any annotation-aware client. Users currently click "allow" for every read-only query.

**Classification of our 142 tools**:
- ~70 read-only (`list_*`, `get_*`, `extract_*`, `query_*`, `search_*`, `inspect_*`, `compare_*`, `read_file`) — should be `readOnlyHint=true`
- ~50 mutating (`create_*`, `add_*`, `set_*`, `apply_*`, `replace_*`, `assign_*`, `enable_*`, `adjust_*`, `shift_*`, `match_*`) — `destructiveHint=false` (reversible)
- ~10 destructive (`delete_object`, `remove_*`, `clean_unused_objects`, `cancel_run`) — `destructiveHint=true`
- ~12 idempotent (`set_*`, `change_building_location`, `set_simulation_control`) — `idempotentHint=true`
- All 142 — `openWorldHint=false` (local-only, no external network calls)

### 2.2 Progressive Tool Discovery

**Best practice**: At 100+ tools, don't ship all schemas to the client. Use meta-tools for discovery:
- `list_tools(prefix?)` — browse tool categories
- `describe_tools(names)` — lazy-load schemas
- `execute_tool(name, args)` — call by name

Benchmarked at 90-96% token reduction (Speakeasy, 400 tools). Constant initial tokens (~2,500) regardless of toolset size.

**Our status**: **PARTIALLY IMPLEMENTED.** We have `recommend_tools` (keyword routing) and `list_skills`/`get_skill` (workflow guidance). But all 142 tool schemas still ship on `tools/list` — the token cost is paid upfront regardless.

True progressive discovery requires the tools NOT be registered with FastMCP at init, and instead routed through a meta-tool dispatcher. This is a fundamental architecture change.

**Alternatives**:
- Anthropic's "code-as-API" pattern: expose tool definitions as files the agent reads on demand (98.7% reduction reported)
- MCP spec proposal for hierarchical `tools/categories` + `tools/discover` + `tools/load` + `tools/unload` (discussion phase, not in spec yet)
- Semantic search via embeddings over tool descriptions

**Impact**: Very high for token cost. At ~450 tokens/tool, 142 tools = ~64K tokens of schema per session. Progressive discovery would reduce to ~3K initial + ~2K per task.

### 2.3 Tool Annotations: Tags & Grouping

**Best practice**: Use `tags` on tools for client-side filtering and organization. Group tools by domain.

**Our status**: **IMPLEMENTED.** All 142 tools have tags: `core`, `geometry`, `hvac`, `loads`, `measures`, `simulation`, `results`, `envelope`, `meta`. Our `recommend_tools` router uses these groups.

### 2.4 Error Handling

**Best practice (3-tier model)**:
1. Transport errors — connection failures (client infra handles)
2. Protocol errors — JSON-RPC codes -32700 to -32802 (SDK handles)
3. Application errors — `isError: true` in tool result (LLM reasons about)

Tool error messages should be:
- Written for LLMs, not developers
- Include actionable guidance ("Call load_osm_model first")
- Include retry guidance where applicable
- Sanitize internals (no stack traces, no secrets)

**Our status**: **MOSTLY GOOD.** `{"ok": False, "error": "..."}` pattern is clean. Errors are sanitized (no stack traces to client). Many errors include actionable guidance ("No model loaded. Call load_osm_model first."). No retry guidance.

**Gaps**:
- Errors don't use MCP's `isError` flag on the tool result content — they return `{"ok": false}` as regular content. This means the LLM must parse JSON to detect failure, rather than the protocol signaling it.
- No suggested-next-action field for recovery guidance

### 2.5 MCP Resources

**Best practice**: Use resources for read-only context the LLM should have automatically, without requiring a tool call. Resources are application-controlled (host decides which to include), unlike tools (model-controlled).

Use cases:
- Current model state summary (auto-attached to context)
- Standards reference data (ASHRAE tables)
- Simulation results summary (auto-updated via subscriptions)

**Our status**: **PARTIALLY IMPLEMENTED.** 4 static resources (ASHRAE baselines, modern HVAC, common materials, tool catalog). No dynamic resources, no subscriptions, no resource templates.

**Gaps**:
- No dynamic resource for loaded model state — every session starts blind and must call `get_model_summary`
- No simulation results resource — results require explicit `extract_*` tool calls
- No resource subscriptions — client can't know when model changes

### 2.6 MCP Prompts

**Best practice**: Prompts are user-controlled workflow templates. They appear as slash commands in VS Code. Should return structured `PromptMessage` arrays with roles, not flat strings.

**Our status**: **PARTIALLY IMPLEMENTED.** 6 prompts exist (baseline comparison, envelope retrofit, etc.). All return plain text strings, not structured `PromptMessage` arrays.

**Gap**: Prompts could embed resources (e.g., results deep dive could embed `openstudio://run/{id}/summary`) and use multi-turn message structures.

### 2.7 Async Tasks (Long-Running Operations)

**Best practice**: Operations >5s should use MCP Tasks (experimental in 2025-11-25 spec). Client gets immediate task ID, polls via `tasks/get`, retrieves results when done. Eliminates custom polling patterns.

**Our status**: **NOT IMPLEMENTED.** `run_simulation` returns a `run_id` and the LLM polls `get_run_status` every 1-2 minutes. This is a custom polling pattern that MCP Tasks would replace at the protocol level.

**Impact**: Medium-high. EnergyPlus sims take 30-120s. MCP Tasks would:
- Eliminate the instructions telling LLMs to poll every 1-2 minutes
- Let the client show native progress UI
- Allow the agent to do other work while sim runs

**Caveat**: Tasks are experimental in the spec. Client support (Claude Desktop, Claude Code) may be limited.

### 2.8 Progress Reporting

**Best practice**: Attach `progressToken` to long requests. Server sends `notifications/progress` with `{progress, total, message}`.

**Our status**: **NOT IMPLEMENTED.** No progress notifications. Sim progress visible only via polling `get_run_status`.

### 2.9 Structured Output (outputSchema)

**Best practice**: Tools declare `outputSchema` (JSON Schema) and return `structuredContent` alongside text `content`. Enables client-side validation and typed parsing.

FastMCP auto-generates schemas from Pydantic models or typed dicts.

**Our status**: **NOT IMPLEMENTED.** All tools return `{"ok": True, ...}` as text content. No `outputSchema`, no `structuredContent`. We have a `tool_responses.schema.json` but it's only used in unit tests, not declared to clients.

**Impact**: Medium. Would let future clients validate responses and build typed integrations. Low urgency since our JSON response pattern is well-established.

### 2.10 Transport

**Best practice**: stdio for local/single-client. Streamable HTTP for remote/multi-user. SSE is deprecated.

**Our status**: **CORRECT for current use case.** stdio only. For the planned remote multi-user deployment, Streamable HTTP would be needed.

### 2.11 Security

**Best practice**: Path traversal prevention, input validation, no eval/exec, no secrets in errors. For remote: OAuth 2.1, per-tool scopes, TLS.

**Our status**: **GOOD for local deployment.**
- Allowlist-based path validation (`is_path_allowed`)
- No `eval()`, `exec()`, or `getattr()` dispatch
- No secrets in error messages
- `parse_str_list()` handles JSON-string array inputs safely

**Gap**: No OAuth, no per-tool scopes — not needed for stdio but will be for remote.

### 2.12 Testing

**Best practice (3-tier)**:
1. Unit — tool logic, input validation (pytest, mock dependencies)
2. Integration — full protocol flow with real server (Docker/Testcontainers)
3. LLM/Agent — tool selection and multi-step workflows

FastMCP in-memory testing (no subprocess overhead) is the emerging best practice for unit tests.

**Our status**: **INDUSTRY-LEADING.**
- 480+ integration tests in Docker with real OpenStudio SDK
- LLM agent tests (~160 tests) with Claude evaluating tool selection
- 5-shard CI pipeline balanced at ~200s each
- Strict test quality rules (regression/validates comments, exact values, no mocks in integration)
- `unwrap()` helper, `create_and_load()` fixtures, `poll_until_done()`

**Minor gap**: Not using FastMCP in-memory client for unit tests (would be faster than subprocess).

### 2.13 Observability / Logging

**Best practice**: MCP servers should emit structured logs via `notifications/message`. Levels: debug through emergency. OpenTelemetry semantic conventions for tracing.

**Our status**: **MINIMAL.** Python `logging` only in skill auto-discovery. No per-tool logging, no MCP log notifications, no structured logging, no tracing.

**Impact**: Low for current single-user Docker deployment. Would matter for remote/multi-user debugging.

### 2.14 Server Instructions

**Best practice**: Server provides `instructions` field at init to guide LLM behavior. Should be concise, focused on what the LLM must know to use tools correctly.

**Our status**: **GOOD.** 42-line instructions embedded in `server.py`. Covers "use tools, don't write code" directive, tool-specific guidance, polling instructions. Well-targeted.

### 2.15 Pagination

**Best practice**: Server-side pagination with metadata (total count, truncation flag).

**Our status**: **GOOD.** `list_paginated()` with `max_results`, `total_available`, `truncated` flags. LLM-friendly.

### 2.16 Capability Negotiation

**Best practice**: Declare capabilities explicitly. Only use features both sides support.

**Our status**: **AUTOMATIC.** FastMCP handles capability declaration based on registered tools/prompts/resources.

### 2.17 Cancellation

**Best practice**: Wire protocol-level `notifications/cancelled` to actual cancellation of long operations.

**Our status**: **CUSTOM IMPLEMENTATION.** `cancel_run` tool exists but isn't wired to MCP protocol-level cancellation. Functional but non-standard.

---

## 3. Gap Analysis Summary

### What We Do Well (keep doing)

| Area | Status | Notes |
|------|--------|-------|
| Tool organization (skills) | Strong | 26 skills, clean tools/operations separation |
| Error handling pattern | Strong | `{"ok": bool}` is clean, sanitized, often actionable |
| Path traversal security | Strong | Allowlist-based, no eval/exec |
| Integration testing | Industry-leading | 480+ tests, 5-shard CI, real SDK |
| LLM agent testing | Unique | Only BEM MCP with LLM evaluation tests |
| Pagination | Good | Server-side with metadata |
| Server instructions | Good | 42-line focused guidance |
| Input validation | Good | `parse_str_list()`, Choice arg validation |
| Skill discovery | Good | `list_skills`/`get_skill` for workflows |
| Stdout suppression | Clever | Solves real SWIG/JSON-RPC corruption bug |

### What Needs Work

| Area | Gap | Effort | Impact |
|------|-----|--------|--------|
| Tool annotations | Zero annotations on 142 tools | **Low** | **High** — immediate UX in Claude Desktop/VS Code |
| Token cost | All 142 schemas ship on connect (~64K tokens) | **High** | **Very High** — 90%+ reduction possible |
| MCP Tasks | Custom sim polling vs protocol-level tasks | **Medium** | **High** — native async, client progress UI |
| Dynamic resources | No model-state or results resources | **Medium** | **Medium** — auto-context for LLM |
| Structured output | No outputSchema on any tool | **Medium** | **Medium** — typed responses for clients |
| MCP logging | No protocol-level log notifications | **Low** | **Low** (until remote) |
| `isError` flag | Errors returned as regular content | **Low** | **Low-Medium** — protocol-correct error signaling |
| Progress reporting | No progress notifications for sims | **Medium** | **Medium** — replaces polling |
| Prompt structure | Flat strings, not PromptMessage arrays | **Low** | **Low** |

---

## 4. Recommended Changes (Plan Only)

### Phase 1: Quick Wins (1-2 days)

#### 1a. Tool Annotations
Add `readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` to all 142 tools.

**Approach**: Create a classification map in a central module. Apply via a helper or directly in each `@mcp.tool()` call. FastMCP supports `annotations=ToolAnnotations(...)` parameter.

```python
from mcp.types import ToolAnnotations

# Read-only tools
@mcp.tool(name="list_thermal_zones", tags={"geometry"},
          annotations=ToolAnnotations(
              readOnlyHint=True,
              destructiveHint=False,
              openWorldHint=False,
          ))
```

**Classification pass needed**:
- Audit all 142 tools
- Assign each to: read-only / mutating / destructive / idempotent
- Set `openWorldHint=False` on all (we never make network calls)

**Test**: Unit test asserting every registered tool has annotations.

#### 1b. `isError` Flag on Error Responses
When `{"ok": False}`, set `isError=True` on the MCP tool result content. This is a middleware-level change — inspect the JSON response and set the flag.

**Approach**: Add a FastMCP middleware (`on_call_tool`) that parses the tool result, checks for `"ok": false`, and sets `isError=True`. Note: the server previously had `_StdoutSuppressionMiddleware`, but commit 2395d95 replaced it with a one-shot `redirect_c_stdout_to_stderr()` at startup — this would be a net-new middleware.

#### 1c. Error Recovery Guidance
Add `"suggestion"` field to error responses for common failures:
- No model loaded → `"suggestion": "Call load_osm_model or create_new_building first"`
- Object not found → `"suggestion": "Call list_model_objects to see available objects"`
- Path not allowed → `"suggestion": "Files must be under /runs or /inputs"`

### Phase 2: Spec Feature Adoption (3-5 days)

#### 2a. Dynamic Resources for Model State
Add resources that reflect current loaded model:

- `openstudio://model/summary` — building info, zone count, loop count (auto-updates on model change)
- `openstudio://model/zones` — thermal zone list
- `openstudio://run/{run_id}/results` — simulation results summary

Implement resource subscriptions so clients get `notifications/resources/updated` on model save, measure apply, simulation complete.

**Approach**: model_manager emits events; resource handlers listen and notify.

#### 2b. MCP Protocol Logging
Emit structured log notifications for key events:
- Model load/save
- Simulation start/complete/error
- Measure application
- Error conditions

**Approach**: Add `ctx.log(level, message)` calls in operations. FastMCP propagates as `notifications/message`.

#### 2c. Progress Notifications for Simulation
During `run_simulation`, parse EnergyPlus stdout for stage indicators (warmup, sizing, annual simulation months) and emit `notifications/progress`.

**Approach**: Simulation runner already reads subprocess output. Add progress token tracking and emit notifications at stage boundaries.

### Phase 3: Async Tasks for Simulation (5-7 days)

#### 3a. MCP Tasks for `run_simulation`
Replace custom `run_simulation` → `get_run_status` polling with protocol-level Tasks:
- `run_simulation` returns `CreateTaskResult` with task ID immediately
- Client polls via `tasks/get` or receives push notifications
- `tasks/result` returns final results when sim completes

**Prerequisites**: Verify FastMCP Tasks support (experimental). May need SDK upgrade or custom implementation.

**Impact**: Eliminates the "poll every 1-2 minutes" instruction from server.py. Client shows native progress UI.

#### 3b. Wire Protocol Cancellation
Connect `notifications/cancelled` for `run_simulation` tasks to the existing `cancel_run` subprocess kill logic.

### Phase 4: Token Optimization (7-14 days)

#### 4a. Progressive Tool Discovery
Replace static 142-tool registration with dynamic discovery:

**Option A — Meta-tool dispatcher** (most impactful, highest effort):
- Register only 3 tools: `list_available_tools(category?)`, `get_tool_schema(name)`, `call_tool(name, args)`
- Tools loaded lazily on `get_tool_schema`
- ~95% token reduction
- Requires reworking how FastMCP registers tools

**Option B — Lazy schema loading** (moderate impact, medium effort):
- Register all tools but with minimal descriptions
- Full schema/description loaded on demand via `describe_tool(name)`
- ~60% token reduction
- Easier to implement within FastMCP

**Option C — Client-side filtering** (lowest effort):
- Ship all schemas but use tool annotations + tags to let smart clients filter
- No token reduction but better organization
- Depends on client support

**Recommendation**: Start with Option C (annotations, already in Phase 1). Plan Option A for when the MCP spec finalizes hierarchical tool management (expected 2026).

#### 4b. Structured Output (outputSchema)
Add `outputSchema` to high-frequency tools: `extract_summary_metrics`, `list_thermal_zones`, `get_model_summary`, `get_building_info`, `list_air_loops`, `list_plant_loops`.

**Approach**: Define Pydantic response models. FastMCP auto-generates schemas. Return `structuredContent` alongside text `content` for backward compatibility.

### Phase 5: Remote / Multi-User (future)

#### 5a. Streamable HTTP Transport
Add Streamable HTTP alongside stdio. FastMCP claims support. Needed for:
- Multi-user access
- Web client integration
- Cloud deployment

#### 5b. Session Isolation
Replace global `model_manager` singleton with per-session state. Each connected client gets its own model instance.

**Approach**: Session-keyed dict of model states. FastMCP provides session context.

#### 5c. OAuth 2.1 Authentication
Per-tool scopes. Read-only scope for `list_*`/`get_*`, write scope for mutations, admin scope for destructive ops.

---

## 5. Priority Matrix

| Change | Effort | Impact | Dependencies | Phase |
|--------|--------|--------|-------------|-------|
| Tool annotations (142 tools) | Low (1 day) | High | None | 1 |
| `isError` flag middleware | Low (2 hrs) | Medium | None | 1 |
| Error recovery suggestions | Low (4 hrs) | Medium | None | 1 |
| Dynamic model resource | Medium (2 days) | Medium | None | 2 |
| MCP protocol logging | Low (1 day) | Low | None | 2 |
| Sim progress notifications | Medium (2 days) | Medium | None | 2 |
| MCP Tasks for simulation | Medium (5 days) | High | FastMCP Tasks support | 3 |
| Protocol-level cancellation | Low (4 hrs) | Low | Phase 3a | 3 |
| Progressive tool discovery | High (10 days) | Very High | Spec finalization | 4 |
| Structured output schemas | Medium (3 days) | Medium | None | 4 |
| Streamable HTTP transport | Medium (3 days) | High (for remote) | None | 5 |
| Session isolation | High (7 days) | High (for remote) | Phase 5a | 5 |
| OAuth 2.1 | High (5 days) | High (for remote) | Phase 5a | 5 |

---

## 6. Lessons From Peers

### EnergyPlus-MCP (LBNL)
- Stateless file-based design (IDF path per call) vs our stateful in-memory model
- Pro: scales horizontally, survives restarts. Con: slower (disk I/O per call), no in-memory object graph
- Published in SoftwareX journal — our approach is more powerful but less documented academically

### BEM-AI (PNNL)
- Multi-agent A2A architecture wrapping MCP servers (including openstudio-mcp)
- Uses small language models (Qwen3:4B) with context engineering
- Blackboard pattern for shared state across agents
- Validates that our tool API surface works as a composable building block

### Fusion 360 MCP
- Only project using all 3 MCP primitives (tools + resources + prompts)
- Tiny tool count (3) but demonstrates resources for exposing design state

### STK-MCP (Ansys)
- 3 tools + 5 resources — resources carry the query workload
- Resources for object listing, health, access analysis — what we do with tools

### mcp.science (Path Integral Institute)
- Federated approach: 12 small single-purpose servers
- Opposite of our monolith. Simpler per-server, harder to orchestrate.
- MCP Gateway pattern would unify multiple servers behind one endpoint

### OpenFOAM MCP
- User expertise tracking ("context engineering system")
- Adjusts explanation depth based on detected user knowledge
- Interesting for our LLM-facing tool descriptions

---

## 7. Industry Trends (2026)

1. **Tool annotations becoming standard** — clients auto-approve read-only, prompt for destructive
2. **Progressive discovery for large toolsets** — token cost is the bottleneck, not tool count
3. **Tasks primitive maturing** — async is the future for simulation/build/deploy workflows
4. **Streamable HTTP replacing stdio** for production — stateless horizontal scaling
5. **MCP Gateway pattern emerging** — aggregate multiple servers behind single endpoint
6. **A2A + MCP layering** — MCP for tools, A2A for agent-to-agent coordination
7. **Spec governance moving to Linux Foundation AAIF** — enterprise features coming (audit, SSO)
8. **97M monthly SDK downloads** — MCP is the de facto standard for AI-tool integration

---

## 8. Unresolved Questions

- FastMCP `annotations=ToolAnnotations(...)` support — which version added it? Need `fastmcp>=?`
- MCP Tasks: FastMCP support status? Experimental spec feature, SDK coverage unclear
- Claude Desktop / Claude Code: which annotations actually change UX behavior today?
- Progress notification rendering: does Claude Desktop show progress bars?
- Streamable HTTP in FastMCP: production-ready or experimental?
- `outputSchema` / `structuredContent`: any client actually validates/uses these today?
- Progressive discovery: does FastMCP support dynamic tool registration/unregistration?
- `isError` flag: can FastMCP middleware set this, or does it require patching the SDK?
- How does BEM-AI's A2A wrapper invoke our tools — direct stdio or via MCP client SDK?

---

## Sources

### Official MCP
- [MCP Spec 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25)
- [2026 MCP Roadmap](https://blog.modelcontextprotocol.io/posts/2026-mcp-roadmap/)
- [Tool Annotations Blog](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)
- [MCP Security Best Practices](https://modelcontextprotocol.io/specification/draft/basic/security_best_practices)
- [MCP Transports](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports)

### Industry Research
- [Speakeasy: 100x Token Reduction with Dynamic Toolsets](https://www.speakeasy.com/blog/100x-token-reduction-dynamic-toolsets)
- [Progressive Tool Discovery Pattern](https://agentic-patterns.com/patterns/progressive-tool-discovery/)
- [Anthropic: Code Execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
- [Stop Vibe-Testing Your MCP Servers (FastMCP creator)](https://www.jlowin.dev/blog/stop-vibe-testing-mcp-servers)
- [CoSAI: Practical Guide to MCP Security](https://www.coalitionforsecureai.org/securing-the-ai-agent-revolution-a-practical-guide-to-mcp-security/)

### Peer Projects
- [EnergyPlus-MCP (LBNL)](https://github.com/LBNL-ETA/EnergyPlus-MCP) — [Paper](https://www.sciencedirect.com/science/article/pii/S2352711025003334)
- [BEM-AI (PNNL)](https://github.com/pnnl/BEM-AI) — [Paper](https://www.sciencedirect.com/science/article/abs/pii/S0378778825314422)
- [STK-MCP (Ansys)](https://github.com/alti3/stk-mcp)
- [Fusion 360 MCP](https://github.com/Joe-Spencer/fusion-mcp-server)
- [MATLAB MCP Core Server](https://github.com/matlab/matlab-mcp-core-server)
- [Jupyter MCP Server](https://github.com/datalayer/jupyter-mcp-server)
- [mcp.science](https://github.com/pathintegral-institute/mcp.science)
- [MCP Hierarchical Tool Management Discussion](https://github.com/orgs/modelcontextprotocol/discussions/532)
