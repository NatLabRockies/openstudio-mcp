# APS-Agent Paper Analysis

**Paper:** "LLM Agent for User-Friendly Chemical Process Simulations" (Liang, Groll, Sin — DTU, arxiv 2601.11650v2, Feb 2026)

**Repo:** https://github.com/gsi-lab/APS-Agent (MIT, compiled .pyd core — not readable source)

## What It Is

MCP server wrapping AVEVA Process Simulation (APS) — chemical process simulator. Claude Desktop as client. **15 tools** for flowsheet analysis, synthesis, optimization via natural language. FastMCP, supports stdio/SSE/streamable HTTP.

## Toolset (15 tools)

| Tool | Purpose |
|------|---------|
| aps_connect | Connect to APS |
| sim_open/create/save | Session management |
| sim_status | Convergence/specification check |
| models_list | All models on flowsheet |
| connectors_list | All connections |
| model_all_vars | All variables for a model (thousands) |
| model_all_params | All parameters for a model |
| var_get/set_multiple | Batch variable read/write |
| param_set_multiple | Batch parameter write |
| model_add | Add equipment to flowsheet |
| models_connect | Wire two model ports |
| fluid_create | Create fluid with components + thermo |
| fluid_to_source | Assign fluid to source model |

All return `success: bool` + structured context — same pattern as our `ok: True/False`.

## Key Findings

### Case Study 1: Analysis (read existing flowsheet)
- Agent extracts data from thousands of variables, interprets thermo relationships, presents clearly
- Minor errors: oversimplification of complex interactions, calculation mistakes
- 6 tool calls, single interaction round

### Case Study 2: Synthesis (build flowsheet from scratch)
- **Step-by-step dialogue**: reliable but requires domain expertise to prompt correctly
- **Single prompt**: 23 tool calls, 3 rounds. Less consistent — tried to set 4 nonexistent variables, redundant queries, premature parameter adjustments
- Step-by-step better for education; single-prompt better for experienced users doing rapid prototyping

### Future Architecture (Fig. 4)
Multi-agent + RAG:
- Orchestrator agent dispatches to specialized sub-agents (synthesis, analysis, optimization)
- RAG knowledge base grounds agent in simulator-specific knowledge
- Dynamic context filtering to reduce information overload

## Why They Propose RAG

**Not about context window limits** — they never mention token counts. The problem is:

1. **Information overload** — `model_all_vars` returns thousands of variables per model. Complex flowsheets overwhelm the agent's ability to pick what matters
2. **Domain knowledge gaps** — LLM hallucinates variable names, tries to set nonexistent params, doesn't know APS-specific operational modes
3. **Variable selection errors** — agent doesn't know which variables are settable vs computed, leading to failed tool calls

RAG would inject: valid variable paths, parameter constraints, best practices, operational mode knowledge.

## Comparison to openstudio-mcp

| Aspect | APS-Agent | openstudio-mcp |
|--------|-----------|----------------|
| Tools | 15 | 142 |
| Tool granularity | Coarse (dump all vars) | Fine (targeted getters) |
| Response pattern | `success: bool` | `ok: bool` |
| Context management | None (future: RAG) | Skills, ToolSearch, targeted tools |
| Testing | 2 qualitative case studies | 167 automated LLM tests (95.8%) |
| Multi-agent | Proposed future | Not yet |
| Transport | stdio/SSE/streamable HTTP | stdio |
| LLM | Claude Sonnet 4 | Claude Sonnet (configurable) |

## Lessons for Us

### Already ahead on
- **Tool discovery**: our ToolSearch + skills = their proposed "dynamic context filtering" + RAG
- **Targeted tool design**: `inspect_component` > `model_all_vars` dump. We avoid their information overload problem by design
- **Testing rigor**: 167 automated tests with failure mode analysis vs 2 qualitative case studies
- **Error handling**: our tools validate inputs, return structured errors. Their agent tries nonexistent variables

### Worth adopting
- **Multi-agent for scale**: as we add tools, orchestrator + specialized sub-agents could replace ToolSearch. Their Fig. 4 architecture aligns with our remote MCP plan
- **Streamable HTTP transport**: they already support it, we have it planned
- **Batch operations**: their `var_get/set_multiple` pattern — we could add bulk property get/set for efficiency (fewer round-trips)

### Validates our approach
- Step-by-step > single-prompt for complex tasks — matches our skills system encoding expert workflows
- Expert oversight still essential — supports our guardrails work
- `success/ok` + structured errors is the right response pattern
- Deterministic simulator as verification layer — EnergyPlus serves same role for us
