# Claude Desktop Setup

> **Last verified:** April 2026 · Claude Desktop 0.10+ · [Docs](https://support.anthropic.com/en/articles/9517730-getting-started-with-claude-desktop)

Claude Desktop is the recommended starting point for openstudio-mcp. It has a GUI, supports all 142 tools, and handles the full skill workflow. The main limitation is that all tool schemas load into context upfront — above ~100 tools, you may notice the model spending more tokens on tool routing before the first useful response.

---

## Prerequisites

- **Docker Desktop** running ([download](https://www.docker.com/products/docker-desktop/))
- **Claude Desktop** installed ([download](https://claude.ai/download))
- openstudio-mcp image built: `docker build -t openstudio-mcp:dev -f docker/Dockerfile .`

---

## Configuration

Open the Claude Desktop config file:

| OS | Path |
|----|------|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

Add the `openstudio-mcp` entry to the `mcpServers` block. Replace the placeholder paths with **absolute paths** on your machine:

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

**Optional: include skill guides** (enables `list_skills()` / `get_skill()` tools):

```json
"-v", "/absolute/path/to/openstudio-mcp/.claude/skills:/skills:ro",
```

---

## Verification

1. **Restart Claude Desktop** after saving the config
2. Look for the **hammer icon (🔨)** in the chat input bar — it appears when at least one MCP server is connected
3. Click the hammer icon to see all available tools listed under "openstudio-mcp"
4. Send this test prompt:

   > *"Call list_skills and tell me what skill categories are available."*

   A successful response lists the skill categories (geometry, HVAC, simulation, etc.). If you see a generic response or an error, check the troubleshooting section below.

---

## First Prompts

Try these in order of complexity:

```
Simple:   "Create an example model and tell me about it"
Medium:   "Create a small office building with ASHRAE System 3 and show me the HVAC components"
Advanced: "Load my model at /inputs/MyBuilding.osm, apply the 90.1-2019 template, and run a simulation"
```

---

## File Access Pattern

Place your `.osm` models and weather files in the folder you mapped to `/inputs`. Claude Desktop's built-in file upload puts files into an Analysis sandbox that cannot reach MCP tools — always use the `/inputs` mount instead.

```bash
# Copy your model to the inputs folder before referencing it in chat
cp MyBuilding.osm /absolute/path/to/your/inputs/

# Then reference it in the prompt
"Analyze the building at /inputs/MyBuilding.osm"
```

---

## Context & Performance Notes

Claude Desktop loads all 142 tool schemas into context on the first tool call. This costs approximately **15K tokens** of your context budget upfront — see [Token Context & Performance](./token-context-performance.md) for a full breakdown.

Practical effect: initial responses in a new conversation may include brief tool-selection overhead. Long conversations (15+ turns with heavy tool use) may exhaust context on complex models. If this happens, start a fresh conversation and reference `/runs/` outputs by path.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No hammer icon | Docker not running, or config JSON is invalid | Validate JSON at jsonlint.com; check `docker ps` |
| Hammer icon but no openstudio-mcp tools | Image not found | Run `docker images` to confirm `openstudio-mcp:dev` exists |
| `Error: volume path is not absolute` | Relative paths in config | Replace `./runs` with the full absolute path |
| Model loaded but changes lost | `/runs` not mounted | Confirm the `-v` run path mount is in your config |
| Upload file, tools not used | File went to Analysis sandbox | Move file to `/inputs` folder and reference by path instead |
