# Plan: Tool Consolidation & Discovery Optimization

**Date:** 2026-03-20
**Branch:** optimize
**Status:** planning

## Problem

142 tools. Cursor caps at 40, Windsurf at 100, OpenAI recommends ~10.
Even with ToolSearch (Claude Code), 95.9% pass rate masks that vague
prompts still fail — the LLM uses wrong tools, not that it can't find any.

Tags do nothing — they're FastMCP server-side metadata, never sent over
the wire, not in MCP spec, not used by any client. Keep for future-proofing
but they're not a discovery mechanism.

## Energy Modeler Use Cases

| Persona | What they do | Tools needed |
|---------|-------------|-------------|
| **Building Designer** | Geometry, envelope, loads, weather | model, geometry, constructions, loads, weather |
| **HVAC Engineer** | Systems, loops, components, controls | HVAC systems, components, sizing, SPMs |
| **Energy Analyst** | Run sims, extract results, compare | simulation, results, reporting |
| **Measure Developer** | Author custom measures | measure authoring, API reference |
| **Full-Stack Modeler** | Everything | All tools |

Most sessions use one persona. Full-stack sessions are rare but must work.

## Architecture Options

### Option A: Consolidate to ~80 tools (single server)

Merge redundant tools. Keep single MCP server. Works with all clients
except Cursor (40 cap). ToolSearch handles discovery.

**Consolidation targets:**

| Merge | Before | After | How |
|-------|--------|-------|-----|
| Typed list tools → `list_model_objects` | 10 | 0 | `list_spaces` = `list_model_objects("Space")` |
| Typed detail tools → `get_object_fields` | 10 | 0 | `get_space_details` = `get_object_fields("Space", name)` |
| get/set property pairs | 8 | 4 | Merge each get+set into one tool with optional `properties` param |
| Run info tools | 3 | 1 | `get_run_info(run_id, what="status|logs|artifacts")` |
| Remove duplicate list tools | 2 | 0 | `list_baseline_systems` + `get_baseline_system_info` → docstring on `add_baseline_system` |
| `inspect_osm_summary` → `get_model_summary` | 2 | 1 | Nearly identical |

**Saves ~33 tools → ~109 total.** Still over Cursor's 40 limit.

**Risk:** Typed tools have better descriptions for ToolSearch. `list_spaces`
is more discoverable than `list_model_objects("Space")`. Losing typed tools
may hurt discovery even as it reduces count.

### Option B: Split into multiple MCP servers (~35 each)

4 servers aligned with energy modeling phases. Under Cursor's 40 limit.
Shared model state via filesystem (save/load between servers).

```
openstudio-model     (~35): create, load, save, geometry, constructions, loads, weather, schedules
openstudio-hvac      (~35): HVAC systems, loops, components, sizing, controls, wiring patterns
openstudio-simulate  (~25): run, status, results, reporting, comparison, visualization
openstudio-measures  (~15): author, test, edit, apply, comstock, API reference
+ shared:            (~10): list_model_objects, get_object_fields, set_object_property, delete, rename, list_files, list_skills, get_skill, recommend_tools, search_api
```

**Claude Desktop config:**
```json
{
  "mcpServers": {
    "openstudio-model": { "command": "docker", "args": ["run", ..., "openstudio-model"] },
    "openstudio-hvac": { "command": "docker", "args": ["run", ..., "openstudio-hvac"] },
    "openstudio-simulate": { "command": "docker", "args": ["run", ..., "openstudio-simulate"] },
    "openstudio-measures": { "command": "docker", "args": ["run", ..., "openstudio-measures"] }
  }
}
```

**Shared state problem:** Each server is a separate Docker container with
its own `model_manager` globals. Model changes in one server aren't visible
to others until saved to disk and reloaded.

**Workaround:** Auto-save after every mutation. Each server loads from disk
on first tool call. Adds ~0.5s latency per cross-server transition.

**Risk:** User must save model between phases. Error-prone. Multi-container
setup is heavier (4x Docker processes). Tool names get prefixed
(`openstudio-model__list_spaces`) which is ugly and harder for LLM.

### Option C: FastMCP mount() composition (~35 per namespace)

Single process, single Docker container. Mount sub-servers with namespaces.
Model state shared via Python globals (current architecture).

```python
main = FastMCP("openstudio-mcp")
model_server = FastMCP("model")
hvac_server = FastMCP("hvac")
sim_server = FastMCP("simulate")
measures_server = FastMCP("measures")

# Register skills to appropriate sub-servers
register_model_skills(model_server)
register_hvac_skills(hvac_server)
register_sim_skills(sim_server)
register_measure_skills(measures_server)

# Mount without namespace (tools keep original names)
main.mount(model_server)
main.mount(hvac_server)
main.mount(sim_server)
main.mount(measures_server)
```

**Problem:** All tools still appear in `tools/list` — no reduction.
Mounting is organizational, not a discovery mechanism. Same 142 tools.

Could combine with `disable(tags=...)` at init + activation tools, but
Claude Desktop/Code don't support `tools/list_changed`.

### Option D: Consolidate + split (hybrid)

1. First consolidate: merge typed tools into generic ones (~109 tools)
2. Then split into 3 servers (~35 each)
3. Shared tools duplicated across servers (list_model_objects etc.)

Gets under Cursor's 40. Works with all clients. Model state is the
only hard problem.

### Option E: Keep 142 tools, optimize descriptions only

ToolSearch works when descriptions are rich. Instead of consolidating:
- Enrich every tool description with use cases, keywords, examples
- Ensure every tool is findable by natural language queries
- Accept that Cursor users need manual tool disabling

**Lowest risk.** No architecture changes. Already partially done
(search_api, search_wiring_patterns descriptions enriched).

## Tool Name & Description Audit

**Bad names (too generic for ToolSearch):**
- `get_run_status` → "Get current status for a run" (47 chars)
- `cancel_run` → "Attempt to cancel a running job" (31 chars)
- `copy_file` → "Copy a file or directory" (24 chars)

**Bad descriptions (too short for ToolSearch matching):**
- 85 tools have first-line descriptions under 60 chars
- Short descriptions = fewer keywords = harder for ToolSearch to match

**Good examples (ToolSearch finds these easily):**
- `create_measure` — 7024 chars, many keywords, examples
- `get_object_fields` — 575 chars, "introspection", "properties", "setter methods"
- `search_api` — enriched with use cases and examples

**Fix:** Enrich all tool descriptions. Doesn't reduce count but improves
discovery. Compatible with any future consolidation.

## Recommendation

**Phase 1 (now): Enrich all descriptions** — Option E. Zero risk, improves
ToolSearch for all clients that support deferred loading. ~2 hours across
22 tools.py files.

**Phase 2 (next sprint): Consolidate typed tools** — Option A partial.
Remove typed list/detail tools that are redundant with generic access.
Saves ~20 tools, gets to ~120. Test with ToolSearch to verify generic
tools are still discoverable.

**Phase 3 (if needed): Split servers** — Option D. Only if Cursor support
is required or consolidation isn't enough. Requires solving model state
sharing. Significant architecture change.

## Unresolved

- Does Cursor's 40-tool limit apply per-server or total across all MCP servers?
- If we enrich all 142 descriptions, does ToolSearch handle them all well or is there a practical limit?
- Would removing typed list tools (list_spaces etc.) hurt LLM test pass rates? Need to measure.
- Model state sharing: auto-save on every mutation adds latency — is 0.5s acceptable?
- Should shared tools (list_model_objects, get_object_fields) be duplicated across split servers or centralized?
