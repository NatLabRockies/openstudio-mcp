# Plan: Multi-MCP Server Split (Deferred)

**Date:** 2026-03-20
**Branch:** optimize
**Status:** deferred — only needed if Cursor support required or tool count causes issues

## Motivation

142 tools exceeds client limits:
- Cursor: 40 tools hard cap (maybe 80 recently)
- Windsurf: 100 tools
- OpenAI: 128 limit, recommends ~10
- Claude Code: works via ToolSearch (auto-defers at 10% context)

Split into multiple smaller MCP servers aligned with energy modeling phases.

## Proposed Split

| Server | Skills | ~Tools | Persona |
|--------|--------|--------|---------|
| `openstudio-model` | model_management, geometry, spaces, constructions, loads, schedules, space_types, weather, building | ~35 | Building Designer |
| `openstudio-hvac` | hvac, hvac_systems, loop_operations, component_properties, api_reference | ~35 | HVAC Engineer |
| `openstudio-simulate` | simulation, simulation_outputs, results, common_measures (viz/report subset) | ~25 | Energy Analyst |
| `openstudio-measures` | measure_authoring, measures, comstock, common_measures (envelope/loads subset) | ~15 | Measure Developer |

Shared tools duplicated across all servers (~10):
list_model_objects, get_object_fields, set_object_property, delete_object,
rename_object, list_files, list_skills, get_skill, recommend_tools, search_api

## Implementation: Profile-Based Registration

Single entry point, single Docker image. Profile selects which skills register.

```python
# mcp_server/server.py
import sys

PROFILES = {
    "model": ["model_management", "geometry", "spaces", "constructions",
              "loads", "schedules", "space_types", "weather", "building",
              "object_management", "skill_discovery", "tool_router"],
    "hvac": ["hvac", "hvac_systems", "loop_operations",
             "component_properties", "api_reference",
             "object_management", "skill_discovery", "tool_router"],
    "simulate": ["simulation", "simulation_outputs", "results",
                 "object_management", "skill_discovery", "tool_router"],
    "measures": ["measure_authoring", "measures", "comstock",
                 "common_measures", "object_management",
                 "skill_discovery", "tool_router"],
    "all": None,  # register everything (default, backward compatible)
}

def main():
    profile = "all"
    if "--profile" in sys.argv:
        idx = sys.argv.index("--profile")
        profile = sys.argv[idx + 1]

    if profile == "all":
        register_all_skills(mcp)
    else:
        register_skills(mcp, only=PROFILES[profile])
    mcp.run()
```

```toml
# pyproject.toml — single entry point, profile via CLI arg
[project.scripts]
openstudio-mcp = "mcp_server.server:main"
```

### Claude Desktop Config

Same Docker image, different `--profile` arg:

```json
{
  "mcpServers": {
    "openstudio-model": {
      "command": "docker",
      "args": ["run", "--rm", "-i",
               "-v", "C:/projects/openstudio-mcp/runs:/runs",
               "-v", "C:/projects/openstudio-mcp/tests/assets:/inputs:ro",
               "openstudio-mcp:dev",
               "openstudio-mcp", "--profile", "model"]
    },
    "openstudio-hvac": {
      "command": "docker",
      "args": ["run", "--rm", "-i",
               "-v", "C:/projects/openstudio-mcp/runs:/runs",
               "openstudio-mcp:dev",
               "openstudio-mcp", "--profile", "hvac"]
    },
    "openstudio-simulate": {
      "command": "docker",
      "args": ["run", "--rm", "-i",
               "-v", "C:/projects/openstudio-mcp/runs:/runs",
               "openstudio-mcp:dev",
               "openstudio-mcp", "--profile", "simulate"]
    },
    "openstudio-measures": {
      "command": "docker",
      "args": ["run", "--rm", "-i",
               "-v", "C:/projects/openstudio-mcp/runs:/runs",
               "openstudio-mcp:dev",
               "openstudio-mcp", "--profile", "measures"]
    }
  }
}
```

## Model State Sharing

Each `docker run` is a separate container = separate Python process =
separate `_current_model` global. Model changes in one server are
invisible to others until saved to disk and reloaded.

### Solution: Auto-save + load-on-demand

- After every mutation tool, auto-save model to `/runs/current/model.osm`
- On first tool call in any server, load from `/runs/current/model.osm`
- Within same server, model stays in memory (no penalty)
- Cross-server transition: ~0.5s latency (disk I/O)

### Changes needed

- `model_manager.py`: add `_auto_save_path` config, call `save_model()` after mutations
- Each `operations.py`: no changes (model_manager handles it)
- New env var: `OSMCP_SHARED_MODEL_PATH=/runs/current/model.osm`

## Docker Considerations

Each MCP server = separate `docker run` = separate container instance.
4 containers from same image means:
- ~200MB memory each (OpenStudio SDK), ~800MB total
- Same Docker image, no extra build time
- Shared `/runs` volume for model state + simulation outputs
- No extra Dockerfile changes

This is heavier than non-Docker MCP servers (which are just processes).
We use Docker because OpenStudio SDK requires specific Linux libraries,
not because MCP needs it.

### Alternative: Single container, multiple processes

Not feasible — MCP stdio transport expects one process per client
connection, and Claude Desktop launches each server independently.

## Client Compatibility

| Client | 1 server (142 tools) | 4 servers (~35 each) |
|--------|---------------------|---------------------|
| Claude Code | Works (ToolSearch) | Works |
| Claude Desktop | Works | Works |
| Cursor | Blocked (40 cap) | Works |
| Windsurf | Over 100 cap | Works |
| Gemini CLI | Over 100 soft cap | Works |
| OpenAI | Over 128 limit | Works |

## Tool Name Prefixing

Claude Desktop prefixes MCP tool names: `mcp__openstudio-model__list_spaces`.
With split servers, the prefix changes per server. The LLM sees different
prefixes for different tools — shouldn't affect selection but is noisier.

If tools are duplicated across servers (e.g. `list_model_objects` in all 4),
Claude Desktop sees 4 copies with different prefixes. Unclear if this causes
confusion — needs testing.

## Testing Strategy

- Unit tests: `--profile model` registers only model skills
- Integration: each profile's tools work independently
- Cross-server: save in model server, load in hvac server, verify state
- LLM: does split improve tool selection on the same test cases?

## Research Citations

### Client Tool Limits
- Cursor 40-tool cap: https://forum.cursor.com/t/request-increase-mcp-tools-limit/108637
- Cursor tool filtering request: https://forum.cursor.com/t/add-the-possibility-to-filter-mcp-tools/76776
- Cursor mcp-hub workaround (2 tools proxy): https://forum.cursor.com/t/unlimited-mcp-tools-break-the-40-tools-limit/78040
- Windsurf 100-tool limit: https://docs.windsurf.com/windsurf/cascade/mcp
- OpenAI 128 limit + defer_loading: https://developers.openai.com/api/docs/guides/tools-tool-search
- Gemini CLI 100/512 limits: https://github.com/google-gemini/gemini-cli/issues/21823

### Discovery Mechanisms
- VS Code Copilot embedding-based routing (40→13 tools): https://github.blog/ai-and-ml/github-copilot/how-were-making-github-copilot-smarter-with-fewer-tools/
- Anthropic Tool Search (85% context reduction): https://www.anthropic.com/engineering/advanced-tool-use
- Anthropic defer_loading docs: https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool
- Claude Code ENABLE_TOOL_SEARCH env var: auto at 10% context threshold
- Portkey mcp-tool-filter (embedding proxy): https://github.com/Portkey-AI/mcp-tool-filter
- RAG-MCP paper (13.6% → 43% accuracy): arxiv:2505.03275

### MCP Architecture
- MCP spec: host creates one client per server, fully isolated connections
- FastMCP mount() composition: https://gofastmcp.com/servers/composition
- FastMCP tags + enable/disable: https://gofastmcp.com/servers/tools
- FastMCP namespace activation pattern: examples/namespace_activation/server.py
- tools/list_changed NOT supported by Claude Desktop/Code: https://github.com/apify/mcp-client-capabilities
- Cline dynamic filtering proposal: https://github.com/cline/cline/discussions/3081

### Multi-Server Patterns
- MCPHub aggregation: https://github.com/samanhappy/mcphub
- openclaw-mcp-router (semantic gateway): embeds tools in LanceDB, exposes mcp_search + mcp_call
- MCP context overload analysis: https://eclipsesource.com/blogs/2026/01/22/mcp-context-overload/
- Redis solving MCP tool overload: https://redis.io/blog/from-reasoning-to-retrieval-solving-the-mcp-tool-overload-problem/

## Related Research

See [../research-tool-discovery-at-scale.md](../research-tool-discovery-at-scale.md)
for full industry survey on tool discovery patterns, empirical accuracy data,
and gateway/proxy landscape.

## Decision Criteria

Implement this plan when ANY of:
- Cursor support is explicitly requested
- ToolSearch discovery degrades as tools grow past ~150
- New client with hard tool limit needs support
- Energy modeler feedback indicates tool overload in real workflows
