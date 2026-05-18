# VS Code Copilot Setup

> **Last verified:** April 2026 · VS Code 1.99+ · [Docs](https://code.visualstudio.com/docs/copilot/chat/mcp-servers)

VS Code Copilot (GitHub Copilot Chat in agent mode) supports MCP servers from VS Code 1.99 onward. The 128-tool hard limit is within openstudio-mcp's 142-tool count, so you need to either disable 14+ tools via the UI or use the workspace config's tool filtering.

---

## Prerequisites

- **Docker Desktop** running
- **VS Code 1.99 or later** ([download](https://code.visualstudio.com/))
- **GitHub Copilot** extension installed and active subscription
- openstudio-mcp image built: `docker build -t openstudio-mcp:dev -f docker/Dockerfile .`

---

## Configuration

VS Code uses `.vscode/mcp.json` (workspace) or the user-profile MCP config (global). **Note:** VS Code uses the key `"servers"`, not `"mcpServers"` — this is different from Claude Desktop and Windsurf.

**Workspace config** (`.vscode/mcp.json` in your project root — can be committed):

```json
{
  "servers": {
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

**Global config** (all workspaces): open the Command Palette (`Cmd/Ctrl+Shift+P`) and run `MCP: Open User Configuration`. The file uses the same `"servers"` key format.

---

## Enabling MCP in Agent Mode

MCP tools are only available in **GitHub Copilot Chat agent mode** (`@workspace` / `@agent`). Regular inline completions do not use MCP tools.

1. Open GitHub Copilot Chat (`Ctrl+Alt+I` / `Cmd+Ctrl+I`)
2. Switch to agent mode with the dropdown in the chat panel header
3. Click **Configure Tools** (wrench icon) to see all available MCP tools and toggle them on/off
4. Send a test prompt:

   > *"Use openstudio-mcp to create an example building model and describe it."*

---

## Handling the 128-Tool Limit

openstudio-mcp provides 142 tools. VS Code Copilot has a 128-tool hard cap across all active MCP servers. If you have other MCP servers enabled, the limit applies to the combined total.

**Option A: Disable low-priority tools via the UI**

In the Configure Tools panel, disable tools you won't use. Good candidates to disable for a first evaluation:
- `add_pv_to_shading`, `add_ev_load`, `set_lifecycle_cost_params` (renewables/cost, if not needed)
- `inspect_osm_summary`, `validate_osw`, `run_osw` (advanced file ops)
- `add_design_day` (if using `change_building_location` instead)

**Option B: Use `includeTools` in the config** *(when supported — check VS Code release notes)*

Some VS Code versions support an `includeTools` array to pre-filter exposed tools before the 128 limit is applied. Check the [MCP configuration reference](https://code.visualstudio.com/docs/copilot/reference/mcp-configuration) for the current schema.

---

## First Prompts

Use these in agent mode (`@agent`):

```
@agent Create a baseline 10-zone office building with System 7 VAV reheat
@agent Load /inputs/MyBuilding.osm and list all thermal zones with their setpoints
@agent Run a simulation on /runs/baseline.osm and show me the EUI
```

---

## Context & Performance Notes

VS Code Copilot's context window depends on the model selected in the chat panel:
- GPT-4.1: 128K tokens
- Claude 3.7 Sonnet: 200K tokens
- Gemini 2.0 Flash: 1M tokens

With 128 tools loaded, schema overhead is roughly **13–14K tokens** (reduced slightly from the full 142). See [Token Context & Performance](./token-context-performance.md) for a full breakdown.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No MCP tools appear | Using wrong key (`mcpServers` instead of `servers`) | Check `.vscode/mcp.json` uses `"servers"` |
| "Trust this server?" prompt blocks startup | New server security check | Click "Trust" to allow the server to start |
| Tools appear but agent ignores them | Not in agent mode | Switch chat panel to agent mode |
| 128-tool limit error | Too many tools across all servers | Disable low-priority tools via Configure Tools panel |
| Config not picked up | Wrong file location | Confirm `.vscode/mcp.json` exists in the workspace root you opened |
