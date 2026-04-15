# Cursor — Not Compatible

Cursor has a **40-tool hard cap** for MCP servers. openstudio-mcp provides 142 tools. Cursor will silently truncate the tool list to the first 40 returned by `tools/list`, which means the majority of the BEM workflow — including HVAC configuration, geometry editing, results extraction, and measure authoring — will be inaccessible.

There is no supported workaround within Cursor itself (tool filtering is not user-configurable at the MCP level in current versions).

---

## What Happens If You Try

Adding openstudio-mcp to `.cursor/mcp.json` will technically connect the server. Cursor will load the first 40 tools alphabetically from `tools/list`. Prompts that happen to use those 40 tools will work; anything requiring tools beyond position 40 will fail silently (the model will either hallucinate a response or say the operation isn't possible).

---

## Recommended Alternatives

| Client | Why it's better for this use case |
|--------|----------------------------------|
| **Claude Code** | Best option: ToolSearch handles 142 tools with auto-deferral |
| **Windsurf** | 100-tool limit; workable with manual tool selection |
| **VS Code Copilot** | 128-tool limit; close to full coverage with minor tool disabling |
| **Gemini CLI** | 100 soft limit; `includeTools` filter makes it manageable |
| **Claude Desktop** | Full 142 tools; good for interactive exploration |

---

## If You Must Use Cursor

If your workflow is confined to a narrow subset of tools (e.g., only model inspection and simulation result reading), you can curate a 40-tool subset by running a local wrapper that filters the tool list before serving it to Cursor. This is an advanced workaround and not officially supported.

Track Cursor's MCP roadmap for changes to the tool cap: [Cursor MCP docs](https://docs.cursor.com/context/model-context-protocol).
