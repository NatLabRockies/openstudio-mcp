# Gemini CLI Setup

> **Last verified:** April 2026 · Gemini CLI 0.1.x · [Docs](https://github.com/google-gemini/gemini-cli)

Gemini CLI is a terminal-based AI agent with a **1M token context window** — the largest of any supported client. This makes it well-suited for long BEM workflows and large file analysis. The soft 100-tool limit (512 via API) requires using `includeTools` to avoid degraded performance when all 142 tools are registered.

---

## Prerequisites

- **Docker Desktop** running
- **Gemini CLI** installed:
  ```bash
  npm install -g @google/gemini-cli
  ```
  > **Note:** The Homebrew formula (`brew install gemini-cli`) has a known dependency issue with `@google/gemini-cli-core`. Use npm.
- **Google account** (free tier: 60 req/min, 1,000 req/day) or Gemini API key
- openstudio-mcp image built: `docker build -t openstudio-mcp:dev -f docker/Dockerfile .`

---

## Configuration

Add openstudio-mcp to `~/.gemini/settings.json`. Create the file if it doesn't exist:

```json
{
  "mcpServers": {
    "openstudio-mcp": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/absolute/path/to/your/inputs:/inputs",
        "-v", "/absolute/path/to/your/runs:/runs",
        "-e", "OPENSTUDIO_MCP_MODE=prod",
        "openstudio-mcp:dev", "openstudio-mcp"
      ]
    }
  }
}
```

**Alternative: project-scoped config** via `GEMINI.md` in your project directory. Add a code block with the server config — Gemini CLI reads `GEMINI.md` as project context on startup.

---

## Managing the Tool Limit

Gemini CLI has a soft limit of 100 tools in interactive mode (512 via API). With 142 tools registered, performance may degrade. Use the `includeTools` filter to expose only the tools you need:

```json
{
  "mcpServers": {
    "openstudio-mcp": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/absolute/path/to/inputs:/inputs",
        "-v", "/absolute/path/to/runs:/runs",
        "-e", "OPENSTUDIO_MCP_MODE=prod",
        "openstudio-mcp:dev", "openstudio-mcp"
      ],
      "includeTools": [
        "list_skills", "get_skill",
        "create_new_building", "create_bar_building", "create_typical_building",
        "load_osm_model", "save_osm_model", "get_model_summary", "get_building_info",
        "list_thermal_zones", "list_spaces", "list_air_loops", "list_plant_loops",
        "add_baseline_system", "list_baseline_systems",
        "run_simulation", "get_run_status",
        "extract_summary_metrics", "extract_end_use_breakdown", "compare_runs",
        "validate_model", "change_building_location",
        "list_surfaces", "replace_window_constructions",
        "create_measure", "test_measure", "apply_measure",
        "generate_results_report", "recommend_tools"
      ]
    }
  }
}
```

Extend the `includeTools` list as needed. See [index.md](./index.md) for the full tool list organized by workflow.

---

## Verification

```bash
# Confirm openstudio-mcp is registered (no API call needed)
gemini mcp list
# → Should show "✓ openstudio-mcp: docker run ... (stdio) - Connected"

# Start Gemini CLI and test interactively
gemini
> Use openstudio-mcp to list the available skills
```

---

## First Prompts

```
"Create a medium office building in Chicago using openstudio-mcp and run a simulation"
"Load the model at /inputs/baseline.osm and compare the envelope constructions"
"Write a Ruby measure to set all lights to 8 W/m2, test it, and apply it"
```

---

## Context & Performance Notes

Gemini 2.0/2.5 models have a 1M token context window, so tool schema overhead (~15K tokens for all 142) is a small fraction of total capacity. Long BEM workflows with many intermediate results are well-suited to Gemini CLI's large context.

However, accuracy is a function of tool count presented per turn, not total context size. Using `includeTools` to present 30–40 tools at a time keeps the model focused. See [Token Context & Performance](./token-context-performance.md).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Tools not found | Config file location wrong | Confirm `~/.gemini/settings.json` (not `.gemini/config.json`) |
| Tool count exceeds limit warning | >100 tools registered | Add `includeTools` filter to config |
| Slow first response | All 142 schemas loading | Add `includeTools` to reduce initial schema payload |
| Free tier rate limit hit | >60 req/min | Upgrade to Gemini API key or reduce tool calls per workflow |
