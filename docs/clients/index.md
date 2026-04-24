# MCP Client Setup Guide

This section covers how to connect openstudio-mcp to each supported AI client, what to expect from the 142-tool surface in each environment, and how to evaluate the performance impact on your context window.

---

## Client Compatibility

| Client | Tool Limit | Discovery | Status | Notes |
|--------|-----------|-----------|--------|-------|
| **Claude Code** | Unlimited | ToolSearch (auto-defer) | ✅ Best | Defers all 142 tools; retrieves 3-5 per turn by keyword |
| **Claude Desktop** | ~100 practical | None (all in context) | ✅ Full | All tools load upfront; degradation above ~100 tools |
| **VS Code Copilot** | 128 hard | None | ✅ Full | Requires VS Code 1.99+ with MCP support enabled |
| **Windsurf** | 100 hard | Per-tool toggle | ⚠️ Partial | Must disable 42+ tools via UI; not plug-and-play |
| **Gemini CLI** | 100 soft / 512 API | includeTools/excludeTools | ⚠️ Partial | Use `includeTools` to scope to a working subset |
| **Cursor** | 40 hard | None | ❌ Incompatible | 40-tool hard cap; use Windsurf or Claude Code instead |

**Recommendation:** Claude Code is the optimal client for openstudio-mcp. It is the only client with dynamic tool discovery that handles 142 tools efficiently and without manual configuration.

---

## Canonical Docker Server Config

Every client needs a block that tells it how to launch the server. The **core Docker command** is the same in all cases — only the key names differ by client.

```json
{
  "command": "docker",
  "args": [
    "run", "--rm", "-i",
    "-v", "/ABSOLUTE/PATH/TO/inputs:/inputs",
    "-v", "/ABSOLUTE/PATH/TO/runs:/runs",
    "-e", "OPENSTUDIO_MCP_MODE=prod",
    "openstudio-mcp:dev", "openstudio-mcp"
  ]
}
```

**Required substitutions:**
- `/ABSOLUTE/PATH/TO/inputs` — folder containing your `.osm` and weather files
- `/ABSOLUTE/PATH/TO/runs` — folder where simulation outputs will be written

> **Use absolute paths.** Many clients run the command from an unpredictable working directory, so relative paths like `./runs` will silently fail or point to the wrong location.

**Optional: mount skill guides for `get_skill()` / `list_skills()` access**

```json
"-v", "/ABSOLUTE/PATH/TO/openstudio-mcp/.claude/skills:/skills:ro",
```

See each client guide for how to embed this block in the client's specific config format.

---

## Guide Index

- [Claude Desktop](./claude-desktop.md) — Recommended starting point; GUI client with full tool support
- [Claude Code](./claude-code.md) — Best for power users; ToolSearch handles 142 tools efficiently
- [VS Code Copilot](./vs-code-copilot.md) — VS Code 1.99+; 128-tool limit, workspace-scoped config
- [Windsurf](./windsurf.md) — Cascade AI; 100-tool limit requires manual tool selection
- [Gemini CLI](./gemini-cli.md) — Terminal-based; 1M token context; use `includeTools` to subset
- [Cursor](./cursor.md) — Not compatible; 40-tool hard cap; alternatives listed

## Reference

- [Token Context & Performance Impact](./token-context-performance.md) — How the 142-tool surface affects each client's context budget
