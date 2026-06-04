# Remote & Multi-User Setup (HTTP transport)

By default openstudio-mcp runs over **stdio** — one server process per user,
launched on demand by the MCP host (the Quick Start in the README). For a
shared deployment — one beefy machine, many people connecting from their own
laptops — run it over **streamable HTTP** instead. Same image, one env var.

| | stdio (default) | HTTP (remote/multi-user) |
|---|---|---|
| Who launches it | the MCP host, per user | you, once, as a service |
| Transport | stdin/stdout | `http://<host>:8000/mcp` |
| Users | one (the local user) | many concurrent, isolated |
| Auth | none (local trust) | bearer token (default) or none on a VPN |
| Config key | `command` + `args` | `type: http` + `url` |

Everyone shares the one running server but is **isolated**: each connection gets
its own loaded model, its own run directory (`/runs/<user>/…`), and can't see
another user's runs or files. Simulations are queued so the box isn't thrashed.

---

## 1. Run the server in HTTP mode

The server stays single-box (model state is heavy and in-memory). Put it on a
machine your users can reach — see [Network & security](#4-network--security).

**Trusted network / VPN (no app auth):**
```bash
docker run -d --name openstudio-mcp \
  -p 8000:8000 \
  -e MCP_TRANSPORT=http \
  -e MCP_AUTH=none \
  -v /data/runs:/runs \
  -v /data/inputs:/inputs \
  openstudio-mcp:dev openstudio-mcp
```

**With per-user tokens (default for HTTP):**
```bash
docker run -d --name openstudio-mcp \
  -p 8000:8000 \
  -e MCP_TRANSPORT=http \
  -e MCP_AUTH=token \
  -e MCP_TOKENS='{"s3cret-alice":"alice","s3cret-bob":"bob"}' \
  -v /data/runs:/runs \
  openstudio-mcp:dev openstudio-mcp
```

`MCP_TOKENS` maps each bearer token → a username. That username becomes the
user's identity: it scopes their run directory and their run ownership. If you
set `MCP_TRANSPORT=http` and forget `MCP_AUTH`, it defaults to `token` and — with
no `MCP_TOKENS` — rejects everyone (fail-closed). Use `MCP_AUTH=none` to opt out.

> **Token storage is plaintext** (`StaticTokenVerifier`). Fine for a trusted team
> behind a VPN. For SSO/public deployments use `MCP_AUTH=jwt` and point it at your
> IdP's verifying key (`MCP_JWT_PUBLIC_KEY`, a PEM) or JWKS endpoint
> (`MCP_JWT_JWKS_URI`), optionally constraining `MCP_JWT_ISSUER` / `MCP_JWT_AUDIENCE`.

---

## 2. Connect a client

`url` points at the server's `/mcp` path; add the bearer header only if you ran
with `MCP_AUTH=token`. **Claude Code, Cursor, and VS Code** all support this.

**Claude Code** — add to `.mcp.json` (or `claude mcp add`):
```json
{
  "mcpServers": {
    "openstudio-mcp": {
      "type": "http",
      "url": "http://10.0.0.5:8000/mcp",
      "headers": { "Authorization": "Bearer s3cret-alice" }
    }
  }
}
```

**Cursor** — `~/.cursor/mcp.json` (or project `.cursor/mcp.json`), same shape:
```json
{ "mcpServers": { "openstudio-mcp": {
  "url": "http://10.0.0.5:8000/mcp",
  "headers": { "Authorization": "Bearer s3cret-alice" }
}}}
```

**VS Code (Copilot)** — `.vscode/mcp.json`:
```json
{ "servers": { "openstudio-mcp": {
  "type": "http",
  "url": "http://10.0.0.5:8000/mcp",
  "headers": { "Authorization": "Bearer s3cret-alice" }
}}}
```

On a VPN with `MCP_AUTH=none`, drop the `headers` block. The local stdio config
(README Quick Start) is unchanged and still works for single-user use.

---

## 3. How isolation works

- **Per-session model.** Each connection has its own loaded OSM model. Two
  windows (even the same user) never overwrite each other's working model.
  Idle sessions are dropped after `OSMCP_SESSION_TTL` (default 30 min); a hard
  cap (`OSMCP_MAX_SESSIONS`, default 16) bounds resident models.
- **Per-user files.** Everything a user creates lives under `/runs/<user>/…`.
  Tool path arguments are scoped: a user can't read or write another user's run
  area; shared reference dirs (measures, `/inputs`) are read-only. `list_files`
  with `/runs` shows only the caller's own runs.
- **Run ownership.** `get_run_status` / `get_run_logs` / `get_run_artifacts` /
  `cancel_run` only work on the caller's own runs — another user's `run_id`
  returns "unknown run_id".
- **Simulation queue.** Runs are FIFO-queued; at most `OSMCP_MAX_CONCURRENCY`
  (default 1) EnergyPlus simulations execute at once. Excess runs report
  `status: "queued"` and start automatically as slots free.

---

## 4. Network & security

The server is **not** the TLS edge — it speaks plain HTTP and trusts the network
around it. Pick one:

- **VPN (recommended).** Bind it inside a corporate LAN/firewall or a
  Tailscale/WireGuard tailnet; users connect to a private IP. With the network as
  the boundary you can run `MCP_AUTH=none`.
- **Reverse proxy for TLS.** Front it with Caddy/nginx/Traefik (or a Cloudflare
  Tunnel) terminating HTTPS and forwarding to `:8000`. Keep `MCP_AUTH=token`.

Don't expose port 8000 to the public internet directly.

---

## 5. Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `MCP_TRANSPORT` | `stdio` | `http` (or `streamable-http`) to serve remotely |
| `MCP_HOST` | `0.0.0.0` | bind address (HTTP mode) |
| `MCP_PORT` | `8000` | listen port (HTTP mode) |
| `MCP_PATH` | `/mcp` | URL path of the MCP endpoint |
| `MCP_AUTH` | `token` on HTTP, else `none` | `none` (open), `token`, or `jwt` |
| `MCP_TOKENS` | `{}` | JSON map `{"<bearer-token>":"<username>"}` (token mode) |
| `MCP_JWT_PUBLIC_KEY` / `MCP_JWT_JWKS_URI` | — | verifying key (PEM) or JWKS endpoint (jwt mode) |
| `MCP_JWT_ISSUER` / `MCP_JWT_AUDIENCE` | — | optional JWT issuer/audience checks |
| `OSMCP_MAX_CONCURRENCY` | `1` | max simultaneous EnergyPlus simulations |
| `OSMCP_MAX_CONCURRENCY_PER_USER` | `0` | per-user sim cap for fairness (`0` = no limit) |
| `OSMCP_MAX_SESSIONS` | `16` | LRU cap on resident per-session models |
| `OSMCP_SESSION_TTL` | `1800` | idle seconds before a session model is dropped (`0` disables) |
| `OSMCP_RUN_ROOT` | `/runs` | base directory for per-user run dirs |

---

## 6. Limitations / not yet

- **Single box only** — in-memory model state isn't shared across machines.
  Horizontal scale would need a per-user-container topology behind a router.
- **Static token auth is plaintext** — use `MCP_AUTH=jwt` (IdP-signed JWTs) for
  SSO/public deployments.
- Two internal measure-execution temp dirs still write to shared `/runs`
  (no cross-user read exposure) — to be scoped per-user in a follow-up.

See `docs/plans/multi-user-remote-mcp.md` for the full design rationale.
