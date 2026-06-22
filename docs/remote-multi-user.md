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
Build the image once: `docker build -f docker/Dockerfile -t openstudio-mcp:dev .`

**macOS / Linux — per-user tokens (the default for HTTP):**
```bash
docker run -d --name openstudio-mcp \
  -p 8000:8000 \
  -e MCP_TRANSPORT=http \
  -e MCP_AUTH=token \
  -e MCP_TOKENS='{"<token-alice>":"alice","<token-bob>":"bob"}' \
  -v /data/runs:/runs \
  -v /data/inputs:/inputs \
  openstudio-mcp:dev openstudio-mcp
```

**Windows (PowerShell) — per-user tokens:**
```powershell
# Pass MCP_TOKENS via $env, NOT inline -e "...": Windows PowerShell strips the
# embedded double quotes when handing JSON to docker.exe, so the JSON arrives
# malformed and the server fails closed. Setting $env: first sidesteps that.
$env:MCP_TOKENS = '{"<token-alice>":"alice","<token-bob>":"bob"}'
docker run -d --name openstudio-mcp `
  -p 8000:8000 `
  -e MCP_TRANSPORT=http `
  -e MCP_AUTH=token `
  -e MCP_TOKENS `
  -v "C:/data/runs:/runs" `
  -v "C:/data/inputs:/inputs" `
  openstudio-mcp:dev openstudio-mcp
```

**Trusted network / VPN, no app auth** — drop the two token lines and add
`-e MCP_AUTH=none` instead. Verify either way: `docker logs openstudio-mcp`
should show `Uvicorn running on http://0.0.0.0:8000`.

`MCP_TOKENS` maps each bearer token → a username. That username becomes the
user's identity: it scopes their run directory and their run ownership. If you
set `MCP_TRANSPORT=http` and forget `MCP_AUTH`, it defaults to `token` and — with
no `MCP_TOKENS` — rejects everyone (fail-closed). Use `MCP_AUTH=none` to opt out.

**You issue the tokens.** There is no self-service signup: the operator generates
a strong random string per user, adds it to `MCP_TOKENS`, and hands it to that
user out-of-band — treat it like a password.

```bash
openssl rand -hex 24                                   # macOS / Linux
```
```powershell
# Windows PowerShell — cryptographically random 24-byte hex token
$b = New-Object byte[] 24
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
($b | ForEach-Object { '{0:x2}' -f $_ }) -join ''
```

The server verifies the `Authorization: Bearer …` header on **every** request
before any tool runs; a missing or unknown token is rejected (401). Rotate or
revoke by editing `MCP_TOKENS` and restarting. For `jwt` mode, tokens are minted
and signed by your IdP instead, and the server only verifies them.

> **Token storage is plaintext** (`StaticTokenVerifier`). Fine for a trusted team
> behind a VPN. For SSO/public deployments use `MCP_AUTH=jwt` and point it at your
> IdP's verifying key (`MCP_JWT_PUBLIC_KEY`, a PEM) or JWKS endpoint
> (`MCP_JWT_JWKS_URI`), optionally constraining `MCP_JWT_ISSUER` / `MCP_JWT_AUDIENCE`.

---

## 2. Connect a client

`url` points at the server's `/mcp` path; add the bearer header only if you ran
with `MCP_AUTH=token`. **Claude Code, Cursor, and VS Code** all support this.
Copy [`.mcp.json.example`](../.mcp.json.example) and fill in your host + token.

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

> **Restart your MCP client after editing its config** — Claude Code reads
> `.mcp.json` only at startup; then `/mcp` shows the server connected.

### Reaching the server from another computer

The client `url` is the only thing pointing at the server, so it must be an
address the *other* machine can route to — `localhost` only works on the box
running the container. Use the server's LAN IP (or its VPN/Tailscale address).

**Find the server's address** (run on the server):
```bash
ip -4 addr | grep inet            # Linux
ipconfig getifaddr en0            # macOS (Wi-Fi; try en1 if blank)
```
```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '169.*' -and $_.IPAddress -ne '127.0.0.1' } |
  Select-Object IPAddress, InterfaceAlias        # Windows
```

**Open the firewall** for inbound TCP 8000 on the server (skip for a VPN-only
interface you already trust):
```bash
sudo ufw allow 8000/tcp                                   # Linux (ufw)
# macOS: System Settings → Network → Firewall (often off on a trusted LAN)
```
```powershell
New-NetFirewallRule -DisplayName "openstudio-mcp 8000" `
  -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow   # Windows (admin)
```

Then set the other computer's `.mcp.json` `url` to `http://<server-ip>:8000/mcp`
with that user's token. Keep this on a LAN/VPN — see [Network & security](#4-network--security).

---

## 3. How isolation works

- **Per-session model.** Each connection has its own loaded OSM model. Two
  windows (even the same user) never overwrite each other's working model.
  Idle sessions are dropped after `OSMCP_SESSION_TTL` (default 30 min); a hard
  cap (`OSMCP_MAX_SESSIONS`, default 16) bounds resident models.
- **Per-user files.** Everything a user creates lives under `/runs/<user>/…`, and
  authored/downloaded measures under `/measures/<user>/{custom,bcl}`. Tool path
  arguments are scoped: a user can't read or write another user's run **or measures**
  area. Shared reference dirs (`/inputs`, bundled common/ComStock measures) are
  read-only. `list_files` with `/runs` (and `list_custom_measures`) show only the
  caller's own. See [security-isolation.md](security-isolation.md).
- **Run ownership.** `get_run_status` / `get_run_logs` / `get_run_artifacts` /
  `cancel_run` only work on the caller's own runs — another user's `run_id`
  returns "unknown run_id".
- **Simulation queue.** Runs are FIFO-queued; at most `OSMCP_MAX_CONCURRENCY`
  (default 1) EnergyPlus simulations execute at once. Excess runs report
  `status: "queued"` and start automatically as slots free.
- **Run retention (disk).** Finished run dirs (~40 MB each) can be reclaimed by a
  background sweeper — but it is **off by default**. Enable it explicitly with the
  `--gc` / `--gc-days N` CLI flag or by setting `OSMCP_RUN_RETENTION_DAYS>0`; it
  then deletes runs older than that window, skipping pinned and queued/running
  runs. Only run dirs are swept — saved models under `examples/` are never
  touched, and it never follows symlinks or runs against a system root. On demand
  (regardless of the daemon), agents can `cleanup_runs` (preview with
  `dry_run=True`, then delete), `delete_run`, and `pin_run` / `unpin_run` to
  exempt a reference run. Every reclaim is audit-logged as `run_evicted`.

**Audit log.** Every tool call and the full sim lifecycle are recorded as JSON
lines — to stderr (`docker logs`) and, if `MCP_AUDIT_FILE` is set, to that file:

```jsonc
{"ts":1717532001.2, "event":"tool_call",   "user":"alice", "tool":"run_simulation", "ok":true, "ms":38}
{"ts":1717532001.3, "event":"sim_queued",   "run_id":"…", "user":"alice"}
{"ts":1717532001.4, "event":"sim_launched", "run_id":"…", "user":"alice", "pid":123}
{"ts":1717532019.9, "event":"sim_finished", "run_id":"…", "user":"alice", "status":"success"}
{"ts":1718136600.0, "event":"run_evicted",  "run_id":"…", "user":"alice", "reason":"gc", "age_days":8.2, "freed_mb":50.2}
```

So you can answer "who ran what, when, did it succeed". Disable with `MCP_AUDIT=off`.

**Who can access logs.** Two audiences, two boundaries — enforced in code:

- **End users (through the MCP API)** see only their *own* run logs:
  `get_run_logs` / `get_run_artifacts` (and `read_file` on their run dir) are
  run-ownership scoped, so another user's `run_id` returns "unknown". **No tool
  exposes the audit log** or any other user's logs — there is no API path to them.
- **Operators (host/container access)** see everything: the audit JSON and server
  logs via `docker logs <container>`, and the `MCP_AUDIT_FILE` on the mounted
  volume. This is the only way to read the cross-user audit trail — guard host
  and `docker` access accordingly.
- **Keep `MCP_AUDIT_FILE` off any user-reachable path.** Top-level
  `/runs/audit.log` is already safe in HTTP mode — it sits outside every user's
  `/runs/<user>/` scope, so `read_file` / `list_files` deny it — but never point
  it *inside* a user's run area, or that user could read the whole audit trail.

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
| `OPENSTUDIO_MCP_MEASURES_DIR` | `/measures` | base dir for per-user measures (`<dir>/<user>/{custom,bcl}`); mount writable + chownable like `/runs` |
| `OSMCP_RUN_RETENTION_DAYS` | `0` (off) | enable auto-GC: delete finished run dirs older than N days (`0` = off) |
| `OSMCP_RETENTION_SWEEP_SECONDS` | `3600` | how often the retention daemon sweeps (60s floor) |
| `MCP_AUDIT` | `on` | structured audit logging (tool calls + sim lifecycle); `off` to disable |
| `MCP_AUDIT_FILE` | — | also append audit JSON lines to this file (e.g. `/runs/audit.log`) |
| `OSMCP_MAX_UPLOAD_MB` | `200` | max size of a single uploaded file |
| `OSMCP_USER_QUOTA_MB` | `4096` | per-user cap on total bytes under `uploads/` (`0` = unlimited) |
| `OSMCP_UPLOAD_URL_TTL` | `300` | seconds a signed upload/download URL stays valid |
| `OSMCP_MAX_ARCHIVE_UNCOMPRESSED_MB` | `1024` | zip-bomb cap on extracted archive size |
| `OSMCP_MAX_ARCHIVE_ENTRIES` | `5000` | max entries in an uploaded archive |
| `OSMCP_PUBLIC_BASE_URL` | — | pin the public origin for signed file URLs (set behind a TLS reverse proxy); direct connections auto-resolve it from the request `Host` |
| `OSMCP_FILE_SIGNING_KEY` | auto | HMAC key for signed file URLs (auto-generated + persisted under `RUN_ROOT` if unset) |

Auto-GC of old run dirs is **off by default**. Enable it with `openstudio-mcp --gc`
(7-day window), `openstudio-mcp --gc-days 14`, or `OSMCP_RUN_RETENTION_DAYS=14`
(CLI wins over env). See **[Run retention & garbage collection](run-retention.md)**
for the full setup, safety model, and the `cleanup_runs` / `delete_run` /
`pin_run` tools.

---

## 6. Getting your files to & from the server

Over HTTP the server runs on a different machine, so a tool path like
`load_osm_model(osm_path=...)` can't see a file on your laptop. Move it across
**out-of-band** with the `file_transfer` tools — bytes travel beside the MCP
protocol (never through the model context), authorized by a short-lived
HMAC-signed URL.

**Upload (agent-driven):**

1. `request_upload(filename, size_bytes[, sha256, kind])` → `{file_id, upload_url}`
2. `curl --upload-file model.osm "<upload_url>"`
3. `get_upload(file_id)` → `server_path` (or `extracted_path` for a `.zip`)
4. pass that path to `load_osm_model` / `apply_measure` / `change_building_location`

`upload_url` (and `download_url`) come back **absolute** — resolved from the host
you connected on — so the agent PUTs/GETs them directly without ever being told
the server address (the MCP transport hides it; it lives only in client config).
Behind a TLS reverse proxy, set `OSMCP_PUBLIC_BASE_URL` to pin the public origin.
On Windows use `curl.exe --upload-file …` (bare `curl` is a PowerShell alias for
`Invoke-WebRequest`, which takes different flags).

A `.zip` (or `kind="measure"`) is auto-extracted server-side, guarded against
zip bombs and path/symlink escapes; `extracted_path` points at the measure dir.

**Download:** `request_download(path=...)` (single file) or
`request_download(run_id=..., bundle=True)` (zip a run's `reports/`) →
`download_url`; `curl -O -J "<download_url>"`. Small text → use `read_file`.

**CLI (shell-less clients):**

```bash
export OSMCP_URL=http://box:8000/mcp OSMCP_TOKEN=s3cret-abc
python -m mcp_server.tools.osmcp put my_measure.zip --kind measure   # prints server path
python -m mcp_server.tools.osmcp get /runs/<user>/<run>/exports/model.osm -o model.osm
```

**Security.** Uploads land only in your own sandboxed `RUN_ROOT/<user>/uploads/`
(another tenant can't read them). The server mints the `file_id`, so a hostile
filename can't traverse paths. Enforced: `OSMCP_MAX_UPLOAD_MB`,
`OSMCP_USER_QUOTA_MB`, optional sha256 integrity, and archive bomb/escape guards.
The signed URL carries no bearer token, so it never enters the model context and
expires after `OSMCP_UPLOAD_URL_TTL`. Its absolute origin is resolved from the
request host; behind a reverse proxy, set `OSMCP_PUBLIC_BASE_URL` to pin it.

---

## 7. Limitations / not yet

- **Single box only** — in-memory model state isn't shared across machines.
  Horizontal scale would need a per-user-container topology behind a router.
- **Static token auth is plaintext** — use `MCP_AUTH=jwt` (IdP-signed JWTs) for
  SSO/public deployments.

See `docs/plans/multi-user-remote-mcp.md` for the full design rationale.

---

## 8. Stress testing locally

`scripts/stress_remote.py` drives many concurrent sessions at one server and
asserts the multi-user invariants under load — session isolation, the sim
concurrency cap, cross-user run ownership, and bounded memory:

```bash
docker run --rm -v "$PWD:/repo" -v "$PWD/runs:/runs" openstudio-mcp:dev \
  bash -lc "cd /repo && python scripts/stress_remote.py --profile moderate"
```

Profiles: `smoke` (8 sessions, fast, no sims), `moderate` (24 sessions + a sim
burst), `heavy` (64 sessions + sims). Override any knob with
`--users N --calls K --cap C --sims/--no-sims --max-sessions M` — a tiny
`--max-sessions` forces LRU/TTL eviction so you can watch that path too.

By default Phase 2 launches the sims, checks the cap + ownership, and cancels
them (fast). Add **`--drain`** to instead run them to completion with a live
`queued/running/success` readout — e.g. watch the cap throttle real work:

```bash
python scripts/stress_remote.py --users 6 --cap 2 --drain
```

