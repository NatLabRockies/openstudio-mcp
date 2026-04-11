# Plan: Remote Multi-User MCP Server

## Context
openstudio-mcp is stdio-only, single-user. Users want to run the server on one machine (with OpenStudio SDK + Docker) and let teammates connect from their laptops via Claude Desktop, Claude Code, Cursor, VS Code Copilot, etc. MCP spec (2025-06-18) now has Streamable HTTP as the standard remote transport, and FastMCP supports it natively.

## Phase 1: Single-User Remote HTTP (~1 day)
One-person remote access, zero tool changes.

### Files
- **`mcp_server/server.py`** — env-var transport selection:
  ```python
  transport = os.environ.get("MCP_TRANSPORT", "stdio")
  if transport == "http":
      mcp.run(transport="http", host=os.environ.get("MCP_HOST", "0.0.0.0"),
              port=int(os.environ.get("MCP_PORT", "9000")))
  else:
      mcp.run()  # stdio default, backward compatible
  ```
- **`mcp_server/stdout_suppression.py`** — skip `redirect_c_stdout_to_stderr()` in HTTP mode (stdout isn't the protocol channel, and the fd-1→stderr `os.dup2` isn't thread-safe for HTTP workers)
- **`docker/Dockerfile`** — add `EXPOSE 9000`
- **`docker/docker-compose.yml`** (new) — HTTP mode with port mapping + volume mounts

### Client Setup
| Client | Config |
|--------|--------|
| Claude Code | `claude mcp add --transport http openstudio http://server:9000/mcp` |
| Claude Desktop | `mcp-remote` bridge in `claude_desktop_config.json`, or Custom Connector on claude.ai |
| Cursor | Native MCP config pointing to `http://server:9000/mcp` |
| VS Code Copilot | MCP agent mode config |
| OpenAI ChatGPT | MCP server tools (Developer Mode) |
| Gemini CLI | Native MCP support |
| Continue.dev / Cline | HTTP transport config |

### Verify
- `docker compose up` starts HTTP server on :9000
- `claude mcp add --transport http openstudio http://localhost:9000/mcp` connects
- All 142 tools work
- `MCP_TRANSPORT=stdio` (default) still works for local use

---

## Phase 2: Per-Session Model Isolation (~2 days)
Multiple users each load/save their own model concurrently. **Only `model_manager.py` changes; all 142 tools unchanged.**

### Core Change: `mcp_server/model_manager.py`
Replace globals with session-keyed dict using FastMCP's ContextVar:

```python
_session_models: dict[str, _SessionModel] = {}  # session_id -> (model, path)
_lock = threading.Lock()

def _session_id() -> str:
    """Get MCP session ID, or 'default' for stdio/testing."""
    try:
        from fastmcp.server.context import _current_context
        ctx = _current_context.get(None)
        if ctx: return ctx.session_id
    except: pass
    return "default"

def get_model():       # all 98 call sites unchanged
    sm = _session_models.get(_session_id())
    if not sm: raise RuntimeError("No model loaded")
    return sm.model
```

### Other Files
- **`simulation/operations.py`** — add `session_id` field to `RunRecord`, filter `list_runs` by session
- **Session cleanup** — idle timeout (30min) evicts model from memory (~50-200MB each)

### Verify
- Two Claude Code instances connect simultaneously
- User A loads model_A, User B loads model_B
- `get_building_info()` returns correct model for each
- Stdio mode still works (`session_id="default"`)

---

## Phase 3: Auth + Hardening (~2 days)
Production readiness.

### Files
- **`server.py`** — add `StaticTokenVerifier` (bearer tokens from env/config):
  ```python
  auth = StaticTokenVerifier(tokens={"token-alice": {"client_id": "alice"}, ...})
  ```
- **`session_limits.py`** (new) — max concurrent sessions, idle eviction, memory caps
- **`docker/docker-compose.prod.yml`** (new) — Caddy reverse proxy (auto-TLS) + openstudio-mcp + resource limits
- **`/health` endpoint** — active sessions, memory usage, OS version

### Client Auth
```bash
claude mcp add --transport http --header "Authorization: Bearer token-alice" \
  openstudio https://server:9000/mcp
```

---

## 142-Tool Context Window Problem
Not blocking, but relevant: 142 tools = ~60K chars of schemas sent to every client. All current Claude/Cursor clients handle this fine. Future optimization: use FastMCP tool visibility (`Context.disable()`/`Context.enable()`) to serve subsets per session. The existing `tool_router` skill could gate discovery.

---

## Hosting Options
| Option | Fit | Notes |
|--------|-----|-------|
| Docker on office server | Best for small teams | Current Docker setup, add HTTP transport |
| AWS ECS / Google Cloud Run | Production | Container hosting, auto-scaling |
| Cloudflare Workers | No | Needs OpenStudio SDK binaries (C++ SWIG) |

---

## Unresolved Questions
1. **SWIG thread safety** — concurrent `VersionTranslator().loadModel()` safe? need empirical test, may need coarse lock
2. **Session cleanup trigger** — FastMCP has `on_initialize` but no `on_session_close` hook; may need periodic GC or idle timeout
3. **Claude Desktop native HTTP** — does it now support HTTP MCP directly, or still need `mcp-remote` bridge?
4. **Memory cap** — 5 users x 200MB = 1GB; hard cap + LRU eviction vs error on limit?
5. **Stateless HTTP** — `stateless_http=True` breaks model persistence across calls; skip or support for health checks only?
