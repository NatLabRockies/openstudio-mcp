# Architecture & Testing Patterns for AI-Driven BEM

Research consolidation: GPD orchestrator analysis, BEM-AI multi-agent paper, MCP ecosystem testing survey. Compiled for openstudio-mcp project planning.

---

## 1. Multi-Agent Architectures

### GPD (Get Physics Done)

Open-source AI copilot for physics research from Physical Superintelligence PBC (Apache 2.0, v1.1.0). **Not an MCP server** -- it is an MCP client/consumer and prompt-orchestration framework that installs into Claude Code, Gemini CLI, Codex, and OpenCode.

**Core pattern:** 61 commands drive the host LLM through structured research workflows via slash commands. No simulation engine -- relies on the LLM's inherent physics knowledge, carefully guided.

**6 knowledge injection mechanisms:**

| Mechanism | How it works |
|---|---|
| Convention locking | `/gpd:new-project` pins notation, assumptions, sign conventions to `.gpd/PROJECT.md` |
| Structured research memory | `.gpd/` directory: PROJECT.md, STATE.md (<150 lines), ROADMAP.md, observability logs, traces |
| Physics verification stages | 7 dedicated commands: dimensional analysis, limiting cases, convergence, experiment comparison, regression check |
| Specialist agent roles | 3 model tiers (opus/sonnet/haiku) x 5 research profiles (deep-theory, numerical, exploratory, review, paper-writing) |
| Deterministic validators | CLI validators for plan contracts, verification alignment, paper quality, reproducibility -- code-based, not LLM |
| Wave-based execution | Project -> Milestone -> Phase -> Plan -> Task; plans grouped into dependency waves for parallel execution |

**Key architectural insight:** Don't trust the LLM to validate its own work -- use deterministic code where possible.

### BEM-AI (PNNL)

Xu et al., *Energy & Buildings* 2025. Multi-agent orchestrator using A2A protocol. Repo: `pnnl/BEM-AI` (renamed `automa-ai` v0.5.2 on PyPI).

**Core pattern:** Planner (70B) decomposes task -> specialized agents (4B each) execute with 1-2 tools -> orchestrator assembles results via blackboard.

**7 agents:**

| Agent | Model | Role |
|---|---|---|
| Planner | llama3.3:70b | Decompose query into task list |
| Generator | qwen3:4b | Load template model by type/standard/CZ |
| Envelope | qwen3:4b | Modify WWR and insulation |
| Lighting | qwen3:4b | Adjust LPD, daylighting sensors |
| Simulation | qwen3:4b | Run annual simulation |
| Output | qwen3:4b | Retrieve EUI from results |
| Orchestrator | llama3.3:70b | Manage workflow graph, generate summary |

Agent cards stored as JSON (A2A AgentCard schema), embedded in ChromaDB for semantic search discovery.

**Small-model optimization techniques:**
1. Decision trees in prompts instead of reasoning
2. Forced chain-of-thought scaffolding (numbered steps)
3. One agent = one tool (reliable selection even at 4B)
4. Strict JSON output format with artifact markers
5. History amnesia ("Do NOT check history") -- state goes to blackboard
6. `<think>` tag stripping (reasoning unreliable, final answer usually correct)
7. Semi-automated tuning: run -> analyze logs -> categorize error -> fix context -> rerun -> if fails at 70B, give up

**Result:** ~15K total tokens for full WWR comparison workflow. A single Claude call with 142 tools burns ~60K+ on tool descriptions alone.

**Blackboard pattern:** Shared key-value store replacing conversation context for cross-agent coordination. Agent A writes `original_model_path`, Agent C reads it directly without passing through intermediate agents. Production version (`automa_ai/blackboard/`) has optimistic concurrency, schema validation, revision tracking, audit trail, S3/DynamoDB backends.

**Tool coverage:** 6 tools (4 OpenStudio + 2 model management). Medium office only. Envelope + lighting only. Zero HVAC.

### Three-Way Comparison

| Dimension | GPD | BEM-AI | openstudio-mcp |
|---|---|---|---|
| **Architecture** | Prompt orchestrator / MCP client | Multi-agent orchestrator (A2A) | MCP tool server (JSON-RPC stdio) |
| **What it wraps** | LLM's inherent physics knowledge | OpenStudio (6 tools) | OpenStudio + EnergyPlus (142 tools) |
| **MCP role** | Configures/consumes MCP servers | Consumes via LangChain adapter | IS the MCP server |
| **LLMs** | Frontier (tiered opus/sonnet/haiku) | Small local (4B-70B) | Frontier (Claude Sonnet/Opus) |
| **Agent count** | 1 LLM + specialist profiles | 7 specialized agents | 1 agent, all tools |
| **Memory** | `.gpd/` directory, STATE.md | Blackboard (shared KV store) | Agent's context window + skills |
| **Tool discovery** | Slash commands (fixed set) | RAG over agent cards (ChromaDB) | All 142 tools visible to client |
| **Verification** | 7 physics checks + deterministic validators | 10/10 reliability at temp=0 | `run_qaqc_checks` + 9-category ASHRAE |
| **HVAC coverage** | N/A (physics, not BEM) | None | All 10 ASHRAE + DOAS/VRF/radiant |
| **Building types** | N/A | Medium office only | 17 DOE prototypes |
| **Tests** | Not disclosed | 3 scenarios x 10 repeats | 625 integration + ~200 LLM + ~100 unit |
| **Dependencies** | Python venv, runtime configs | LangChain + LangGraph + ChromaDB + A2A + ADK + LiteLLM + Streamlit | Pure MCP, openstudio SDK |
| **License** | Apache 2.0 | Apache 2.0 | Custom |

**Fundamental relationship:** Complementary, not competing. GPD orchestrates reasoning; BEM-AI orchestrates agents; openstudio-mcp provides the tool layer. BEM-AI could use openstudio-mcp as its MCP server and get 142 tools instead of 6.

---

## 2. Testing Practices Across MCP Ecosystem

### 8-Server Comparison

| Repo | Stars | Unit | Integration (MCP protocol) | E2E (real backend) | LLM-in-Loop | Tool Chaining | Schema Snapshots | CI |
|---|---|---|---|---|---|---|---|---|
| modelcontextprotocol/servers | 81.6K | Yes | No | No | No | No | No | Yes |
| microsoft/playwright-mcp | 29.3K | No | Yes (stdio) | Yes (real browser) | No | Yes | No | Yes (3 OS) |
| github/github-mcp-server | 28.1K | Yes | No | Yes (real GitHub API) | No | Yes | Yes (toolsnaps) | Yes (3 OS) |
| supabase-community/supabase-mcp | 2.5K | Yes | Yes (StreamTransport) | Yes (PGlite + Anthropic API) | Yes (Claude) | Yes | No | Yes |
| upstash/context7 | 49.9K | Yes | No | No | No | No | No | Yes |
| executeautomation/mcp-playwright | 5.3K | Yes | No | No | No | No | No | Yes |
| stripe/agent-toolkit | 1.4K | No | No | No | Yes (multi-model) | Yes | No | N/A |
| **openstudio-mcp** | -- | Yes | Yes (stdio, Docker) | Yes (OpenStudio SDK) | Yes (Claude CLI) | Yes | No | Yes (5 shards) |

### Key Findings

**The testing gap:** Most MCP servers (even 50K+ stars) have only unit tests with mocked backends. Official SDK guidance covers protocol conformance but not behavioral correctness.

**Notable patterns from the ecosystem:**
- **Playwright MCP** -- best integration testing: real `Client` over `StdioClientTransport`, real browser
- **GitHub MCP** -- novel **toolsnaps**: tool JSON schemas serialized to `.snap` files, CI fails on schema drift
- **Supabase MCP** -- most sophisticated before openstudio-mcp: LLM-in-the-loop E2E, LLM-as-judge assertions, prompt injection tests
- **Stripe** -- evaluation framework (not test suite): benchmark scenarios with multi-model comparison

### Three Testing Tiers

| Tier | What it validates | Docker | LLM |
|---|---|---|---|
| **Deterministic** (unit) | Skill registration, path safety, tool metadata, wiring recipes | No | No |
| **Protocol** (integration) | Full MCP JSON-RPC, real SDK, tool dispatch, stdout suppression | Yes | No |
| **Behavioral** (LLM agent) | Tool selection accuracy, workflow completion, guardrail compliance | Yes (server) | Yes |

### Gaps in Official Guidance

| Aspect | Support Level |
|---|---|
| In-memory unit testing | Strong (both SDKs) |
| Protocol conformance | Moderate (conformance package) |
| Integration with real backends | Weak (no patterns) |
| LLM behavioral testing | None |
| Tool description quality validation | None |
| Multi-tool workflow testing | None |

### Complexity Scaling (Academic)

TaskBench (NeurIPS 2024): single-tool accuracy 96% drops to 25% at 8 tools. openstudio-mcp operates at 142 tools -- far beyond any benchmark scale -- making its ~96% pass rate a significant data point.

Temperature matters: BFCL shows 0.0 vs 0.7 can swing accuracy ~10%. Benchmarks disagree with each other (BFCL vs NFCL rankings don't correlate).

### openstudio-mcp Novel Contributions

| Contribution | What it is |
|---|---|
| Progressive prompt specificity (L1/L2/L3) | 43 cases x 3 levels. L1 vague, L2 moderate, L3 explicit. Pass-rate gradient diagnoses discovery vs execution failures |
| Eval.md-driven test generation | Skill authors write eval tables co-located with implementation. 32 cases auto-generated from 8 skill eval.md files |
| Guardrail regression tests | Verify LLM uses MCP tools instead of writing raw IDF/Python/Bash |
| Full workflow E2E | 31 multi-tool workflows, 10+ tool chains (load -> weather -> HVAC -> simulate -> extract -> compare) |
| Measure quality assertions | Authored measures checked for typed args, defaults, descriptions, valid run_body |
| Custom retry with budget caps | LLM tests retry up to 2x, stable/flaky auto-classification, 180 invocation max |
| CI sharding | 5 parallel Docker shards (~200s each), image built once |

### Quantitative Comparison

| Metric | Official Servers | Playwright MCP | GitHub MCP | Supabase MCP | **openstudio-mcp** |
|---|---|---|---|---|---|
| Tools tested | ~20 | ~30 | ~50 | ~30 | **142** |
| Integration tests (MCP protocol) | No | Yes | No | Yes | **Yes (625)** |
| LLM behavioral tests | No | No | No | Yes (~10) | **Yes (~200)** |
| Progressive difficulty | No | No | No | No | **Yes (3 levels)** |
| Multi-tool workflows | No | 2-step | 5-step | 2-step | **10+ step** |
| Guardrail tests | No | No | No | Yes (injection) | **Yes (bypass)** |

### Emerging Best Practices

- **In-memory transport** for fast unit tests (SDK pattern)
- **Schema snapshot testing** for API contract stability (GitHub MCP)
- **LLM-as-judge** for fuzzy output assertions (Supabase)
- **Progressive prompt specificity** for discovery vs execution diagnosis (openstudio-mcp)
- **Outcome-based grading** over path-based (Anthropic guidance)
- **Deterministic validation alongside LLM execution** (GPD pattern)

---

## 3. Lessons for openstudio-mcp

### Adopt

| Pattern | Source | Implementation path |
|---|---|---|
| **Convention/assumption locking** | GPD | `project_init` tool writes `.bem/PROJECT.md` with climate zone, code vintage, baseline system, units, targets. Subsequent tools check it. Existing `ashrae-baseline-guide` skill becomes structural, not advisory |
| **Deterministic precondition checking** | GPD | `validate_workflow` tool checks model loaded, weather attached, design days exist, all zones have HVAC, constructions assigned -- before simulation |
| **Schema snapshot testing** | GitHub MCP | Serialize tool JSON schemas to `.snap` files, CI fails on drift. Catches accidental tool signature changes |
| **Daylighting sensor tool** | BEM-AI | Only real tool gap they exposed |

### Adopt When Needed

| Pattern | Source | Trigger |
|---|---|---|
| **Blackboard pattern** | BEM-AI | If/when we go multi-agent or remote multi-user. In single-agent arch, Claude's context IS the blackboard |
| **Project-level state persistence** | GPD | Multi-session workflows where user returns asking "what was baseline EUI?". `.bem/` directory with STATE.md, VARIANTS.md, DECISIONS.md |
| **Wave-based execution** | GPD | Multi-variant BEM workflows. Requires runtime support (subagents) more than MCP changes |
| **Agent card + semantic search** | BEM-AI | Useful for tool routing optimization -- their ChromaDB approach parallels our dynamic tool filtering |

### Validates Our Approach

| What we do | Validation |
|---|---|
| 142 MCP tools with real simulation | BEM-AI validates MCP-based BEM automation approach. They invested in architecture with 6 tools; we invested in tool depth |
| Three-tier test pyramid | Survey shows no other MCP server does all three tiers. Most have unit-only |
| Progressive L1/L2/L3 testing | No other project tests tool discoverability systematically. Academic benchmarks stop at 8 tools |
| ~96% pass rate at 142 tools | TaskBench shows 25% at 8 tools. Our scale is unprecedented in published results |
| Outcome-based grading in LLM tests | Aligns with Anthropic's "grade outcomes, not paths" guidance |
| Docker-based CI with sharding | More rigorous than any surveyed MCP server |

### Watch

| Risk | Source | Why it matters |
|---|---|---|
| Token cost at 142 tools | BEM-AI | Their 15K tokens vs our ~60K+ on tool descriptions alone. Dynamic tool filtering (our tool-routing optimization) is the answer for single-agent arch |
| Small-model support | BEM-AI | Two paths: (a) micro-agent decomposition (1-2 tools/agent), (b) dynamic tool filtering. We're pursuing (b) |
| Benchmark disagreement | Academic | BFCL vs NFCL rankings don't correlate. Need multiple evals, not single benchmark |
| Temperature sensitivity | BFCL | 0.0 vs 0.7 swings accuracy ~10%. Our LLM tests should pin temperature |

---

## 4. Sources

### Repos
- [GPD](https://github.com/psi-oss/get-physics-done) (v1.1.0) | [PSI blog post](https://theinnermostloop.substack.com/p/the-first-open-source-agentic-ai)
- [BEM-AI / automa-ai](https://github.com/pnnl/BEM-AI) | Xu et al., *Energy & Buildings* 2025
- [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) (81.6K stars)
- [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) (29.3K stars)
- [github/github-mcp-server](https://github.com/github/github-mcp-server) (28.1K stars)
- [supabase-community/supabase-mcp](https://github.com/supabase-community/supabase-mcp) (2.5K stars)
- [stripe/agent-toolkit](https://github.com/stripe/agent-toolkit) (1.4K stars)

### Industry Guidance
- Anthropic, "Demystifying Evals for AI Agents"
- AWS, "Evaluating AI Agents: Real-World Lessons"
- Lowin, "Stop Vibe-Testing Your MCP Server"
- merge.dev, "How to test MCP servers effectively"

### Academic
- BFCL (Berkeley) -- ICML 2025
- TaskBench (Microsoft) -- NeurIPS 2024
- StableToolBench -- ACL 2024
- AgentBench (Tsinghua) -- ICLR 2024
- Mohammadi et al., Agent Eval Survey -- KDD 2025
