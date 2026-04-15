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

Create `.mcp.json` in your project root (or any directory you run `claude` from). A template is provided at `.mcp.json.example` in the openstudio-mcp repo. Copy it and fill in your absolute paths:

```bash
cp .mcp.json.example .mcp.json
# Edit .mcp.json and replace /ABSOLUTE/PATH/TO/... placeholders
```

`.mcp.json` contains machine-specific absolute paths so it is gitignored by default. Share the `.mcp.json.example` template with your team instead.

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
# Confirm .mcp.json is valid and openstudio-mcp is registered
# (run from the project directory containing .mcp.json)
claude mcp add openstudio-mcp --scope project docker -- run --rm -i \
  -v "/absolute/path/to/inputs:/inputs" \
  -v "/absolute/path/to/runs:/runs" \
  -e OPENSTUDIO_MCP_MODE=prod openstudio-mcp:dev openstudio-mcp
# → prints "MCP server openstudio-mcp already exists in .mcp.json" if it's registered
```

> **Note:** `claude mcp list` shows only user-scope servers. Project-scope `.mcp.json` servers load when you start an interactive `claude` session from that directory — they won't appear in `mcp list`.

Start a session and test:

```bash
# Start Claude Code in the project directory
cd /path/to/your/project
claude

# At the prompt:
> list_skills
```

A successful response shows available skill categories. Claude Code will use ToolSearch to find and load only the relevant tool schemas for each request.

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
