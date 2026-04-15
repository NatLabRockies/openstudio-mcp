# Claude Code Setup

> **Last verified:** April 2026 · Claude Code 1.x · [Docs](https://docs.anthropic.com/en/docs/claude-code/mcp)

Claude Code is the **optimal client** for openstudio-mcp. Its ToolSearch feature automatically defers all 142 tools and retrieves only the 3-5 most relevant ones per turn — this eliminates context bloat and keeps accuracy high even on long multi-step workflows. No manual tool filtering is required.

---

## Prerequisites

- **Docker Desktop** running ([download](https://www.docker.com/products/docker-desktop/))
- **Claude Code** installed: `npm install -g @anthropic-ai/claude-code`
- openstudio-mcp image built: `docker build -t openstudio-mcp:dev -f docker/Dockerfile .`

---

## Configuration

Create `.mcp.json` in your project root (or any directory you run `claude` from). This file is the standard Claude Code MCP config and can be committed to source control to share the setup with your team.

```json
{
  "mcpServers": {
    "openstudio-mcp": {
      "command": "docker",
      "args": [
        "run", "--rm", "-i",
        "-v", "/absolute/path/to/your/inputs:/inputs",
        "-v", "/absolute/path/to/your/runs:/runs",
        "-v", "/absolute/path/to/openstudio-mcp/.claude/skills:/skills:ro",
        "-e", "OPENSTUDIO_MCP_MODE=prod",
        "openstudio-mcp:dev", "openstudio-mcp"
      ]
    }
  }
}
```

> **Tip:** Include the `.claude/skills` mount. Claude Code's ToolSearch indexes tool descriptions at connection time — the skill guides improve keyword matching for `get_skill()` and `list_skills()` calls.

**Alternative: pass config path explicitly**

```bash
claude --mcp-config /path/to/mcp.json
```

---

## Verification

```bash
# Start Claude Code in your project directory
claude

# At the prompt, type:
> list_skills
```

A successful response shows the available skill categories. You can also ask:

```
> What MCP tools do you have access to for building energy modeling?
```

Claude Code will call ToolSearch with relevant keywords and return the matching tools without loading all 142 schemas.

---

## How ToolSearch Works

When the total tool schema size exceeds 10% of the model's context window, Claude Code automatically defers all tools and exposes only a `mcp__openstudio-mcp__search_tools` search endpoint. The workflow becomes:

1. Your prompt arrives
2. Claude Code searches for relevant tools by keyword
3. 3–5 matching tool schemas are loaded into context
4. The tool is called with correct parameters
5. Repeat as needed

This means openstudio-mcp's 142 tools behave as if there were only 5 at any given moment. **ToolSearch indexes at Docker image build time** — always rebuild the image after adding new tools (`docker build`).

### Why ToolSearch Accuracy Depends on Descriptions

ToolSearch uses BM25/regex matching on tool names and descriptions. Vague prompts ("add HVAC") depend on description keywords to route correctly. The skills system supplements this — calling `list_skills()` and `get_skill("add-hvac")` gives Claude a step-by-step guide that bypasses tool ambiguity entirely.

---

## First Prompts

```
Simple:   "Create an example model and describe its thermal zones"
Medium:   "Follow the new-building skill to create a 5-story office in Boston"
Advanced: "Load /inputs/baseline.osm, run a simulation, and show me the EUI breakdown by end use"
```

---

## Context & Performance Notes

ToolSearch reduces per-turn schema overhead from ~15K tokens (all 142 loaded) to ~1K tokens (3-5 tools loaded). This is the primary reason Claude Code is the recommended client — see [Token Context & Performance](./token-context-performance.md) for numbers.

Observed benchmark (3-model sweep, 180 tests, zero retries):
- Sonnet: 94.4% pass rate, avg 1.9 ToolSearch calls/test
- Opus: 94.4% pass rate, avg 2.0 ToolSearch calls/test
- Haiku: 88.9% pass rate (does not use ToolSearch; reasons directly from tool list)

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| ToolSearch returns "No matching tools found" | Image not rebuilt after tool additions | `docker build -t openstudio-mcp:dev -f docker/Dockerfile .` |
| Tools work in one session, not another | `.mcp.json` not in working directory | Check `pwd` matches where `.mcp.json` lives |
| Claude generates Python scripts instead of using tools | ToolSearch not finding MCP tools | Rebuild image; check descriptions include relevant keywords |
| Long workflows lose model state | In-memory model cleared between `claude` sessions | Save model to `/runs/` at end of each session with `save_osm_model` |
