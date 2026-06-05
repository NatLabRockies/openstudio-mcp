# Multi-User Remote MCP Server — Design & Implementation Plan

**Branch:** `feat/multi-user-remote-mcp` (off `origin/develop`)
**Status:** Increment 1 complete + verified. Increments 3–4 in progress.

Lets openstudio-mcp run on one beefy box and serve multiple remote users
(Claude Code / Cursor / VS Code) over the network, each with an isolated
session, isolated files, and fair access to simulation compute — while the
existing local stdio workflow stays byte-for-byte unchanged.

---

## 1. Context & constraints

- **Deploy targets:** (a) NLR LAN behind firewall, reached over NLR's VPN;
  (b) a small business, reached over Tailscale/WireGuard. Same artifact, only
  the network around it differs → **Pattern A (private/VPN-fronted)**.
- **Clients:** Claude Code, Cursor, VS Code — all do native `url` + bearer
  header HTTP. (Claude Desktop would need `mcp-remote`; out of scope.)
- **Composability:** a public deployer can add their own perimeter (TLS,
  OAuth, WAF) *on top* without touching tool code. The server owns
  *correctness* (isolation, fairness, identity-keying); the deployer owns the
  *perimeter*. The only hard rule: don't bake in "we are the TLS edge" or
  "auth is static" — keep both as seams.
- **No horizontal scale:** model state is a heavy in-memory OpenStudio object,
  so this is single-box. Multi-box scale-out = future per-user-container
  topology (same isolation model as stdio-per-user, orchestrated).

## 2. Locked decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Model state keyed per-SESSION** (not per-user) | Two windows of the same user must not stomp each other's working model. Matches stdio (1 process = 1 model). |
| 2 | **Sim queue = global FIFO** for v1 | Simplest correct enforcement of `MAX_CONCURRENCY`; per-user fairness is a documented follow-up. |
| 3 | **HTTP auth default = `token`** (secure-by-default) | `MCP_AUTH=none` is an explicit opt-in for trusted VPN. stdio stays `none`. |
| 4 | **Session eviction = 30min idle TTL + max-sessions LRU cap** | Heavy models can't accumulate unbounded; both env-tunable. LRU cap shipped first (hard RAM backstop); TTL sweep is a follow-up. |
| 5 | **Shared roots read-only** | Least privilege: `/repo`, measures, `/skills`, `/inputs` are read-only for all; the only per-user writable area is `RUN_ROOT/<user>`. |
| 6 | **One feature branch**, increments shippable in sequence | — |

## 3. Architecture

```
User (Claude Code / Cursor / VS Code)
        │  HTTPS + bearer token
        ▼
[ TLS / exposure: VPN or tunnel ]        ← deployer's perimeter (NOT in repo)
        ▼
[ FastMCP, transport=http, auth=verifier ]
        │  identity: session_key() / user_key()  (from get_context())
        ├── per-session model state (model_manager: dict + lock + LRU)
        ├── per-user files: RUN_ROOT/<user_key>/...  + path scoping
        └── global sim queue (FIFO, cap = MAX_CONCURRENCY) → EnergyPlus
```

**One identity, two keys** (`mcp_server/identity.py`):

| Key | Source | Keys |
|-----|--------|------|
| `session_key()` | `ctx.session_id` (HTTP) / `"local"` (stdio/off-request) | ephemeral **model** state |
| `user_key()` | auth `client_id` → else `session_id` → else `"local"`, sanitized | durable **run dirs + path scope + run ownership** |

All 142 tools call `get_model()` / `is_path_allowed()` unchanged — the keys
are resolved *inside* those chokepoints, so multi-user is invisible to skills.

**Verified fact:** `get_context().session_id` propagates into FastMCP's
sync-tool worker threads (FastMCP 3.2.0) — so session-keyed isolation is real.

## 4. Component design

- **`server.py`** — `MCP_TRANSPORT` branch (`stdio` default | `http`).
  `MCP_HOST/MCP_PORT/MCP_PATH`. `_build_auth()` reads `MCP_AUTH`
  (`none` | `token` via `StaticTokenVerifier`, `MCP_TOKENS` JSON map).
  stdout: keep `silence_openstudio_stdout_logger()` always; startup
  `redirect_c_stdout_to_stderr()` is safe in both modes (one-time, pre-threads;
  stdout isn't the HTTP protocol channel). No per-request fd ops.
- **`identity.py`** — `session_key()`, `user_key()`, `_sanitize()`.
- **`model_manager.py`** — `dict[session_key → _SessionState]` under an
  `RLock`; LRU evict over `OSMCP_MAX_SESSIONS` (16). Public signatures
  unchanged. `atexit` clears all (SWIG #5421).
- **`config.py`** — `user_run_root()` = `RUN_ROOT/<user_key>`.
  `is_path_allowed(p, *, write=False)`: shared roots read-only; writes only
  under own run dir.
- **`skills/simulation/operations.py`** — run dir =
  `RUN_ROOT/<user_key>/<run_id>`; `RunRecord.user_key`; ownership checks on
  `get_run_status/logs/artifacts/cancel`. Sim **queue**: `run_osw` enqueues
  (`status="queued"`); a background daemon dispatcher reaps finished PIDs and
  launches FIFO up to `MAX_CONCURRENCY`.

## 5. Test strategy

**Harness problem:** stdio spawns one server *process per client*, so "two
stdio sessions" can't prove session-keying. Real isolation is only provable
over **HTTP** (one process, two sessions). Added `http_server()` +
`http_session()` to `conftest.py` (server runs inside the test container; no
published port needed).

| File | Tier | Validates |
|------|------|-----------|
| `test_http_transport.py` | integration | server boots under HTTP; tool round-trips |
| `test_session_isolation.py` | integration | 2 HTTP sessions, 1 process → independent models |
| `test_per_user_run_dirs.py` | integration | run dir namespaced; cross-user run_id → not found; cross-user path → not allowed |
| `test_sim_queue.py` | integration | `MAX_CONCURRENCY=2`, 4 sims → ≤2 running / rest queued → all terminal |
| `test_sim_queue_unit.py` | unit | queue policy: cap, FIFO, slot-release (mock launch only) |
| `test_identity_unit.py` | unit | stdio→`local`; mocked session_id; token→user |
| `test_path_safety.py` (extend) | unit | per-user `is_path_allowed`, write vs read |
| `test_stdio_smoke.py` (extend) | integration | stdio still single-`local`, model persists |

Mocking confined to *dependencies* (subprocess launch, context) — never the
unit under test. CI: light integration → shard 4, sims → shard 5, `*_unit` →
`pytest -m unit` job.

## 6. Increment plan & status

1. **Transport + identity + session-keyed model + HTTP harness** — ✅ DONE, verified.
2. **Sim queue (FIFO, MAX_CONCURRENCY)** — ✅ DONE, verified (unit + integration + e2e).
3. **Per-user run dirs + path scoping + run ownership** — ✅ DONE, verified across all changed skills.
4. **Token auth + HTTP default `token` (secure-by-default)** — ✅ DONE, verified (accept/reject + principal→run-dir).
5. **CI shards (2 + 5) + Dockerfile `EXPOSE 8000`** — ✅ DONE.
6. **Session idle-TTL eviction** (`OSMCP_SESSION_TTL`, default 30 min) + LRU cap — ✅ DONE.
7. **Setup docs** (`docs/remote-multi-user.md` + README pointer) — ✅ DONE.

Follow-up (noted in commits): scope the two `MCP_RUNS_DIR` measure-exec temp
dirs (`measures`/`measure_authoring`) per-user.

## 7. Risks & honest caveats

- **RAM:** N sessions = N heavy models. LRU cap is the backstop; TTL sweep
  follows. Cap sized to box RAM.
- **Intra-session concurrency** on one model is still the client's
  responsibility (unchanged from today); cross-session is what we isolate.
- **Session-id API:** uses public `get_context()` (not private
  `_current_context`); pinned by `test_identity_unit` + isolation test.
- **No multi-box scale** (in-memory models).
- **FIFO queue:** one user can fill the queue (no per-user cap in v1) —
  documented, not silently capped.

## 8. Out of scope for v1 (follow-ups)

- Per-user queue fairness cap.
- OAuth/JWT (the `auth=` seam already supports swapping `JWTVerifier`).
- Per-user-container topology for horizontal scale.
- Quotas / disk accounting per user.

## 9. How to run

**Server (HTTP, trusted VPN):**
```bash
docker run -d -p 8000:8000 \
  -e MCP_TRANSPORT=http -e MCP_AUTH=none \
  -v /data/runs:/runs openstudio-mcp:dev openstudio-mcp
```

**Server (HTTP, token auth):**
```bash
-e MCP_AUTH=token -e MCP_TOKENS='{"s3cret-abc":"alice","s3cret-xyz":"bob"}'
```

**Client (Claude Code / Cursor / VS Code):**
```json
{ "mcpServers": { "openstudio-mcp": {
  "type": "http",
  "url": "http://<box>:8000/mcp",
  "headers": { "Authorization": "Bearer s3cret-abc" }
}}}
```

**Local stdio (unchanged):**
```json
{ "mcpServers": { "openstudio-mcp": {
  "command": "docker",
  "args": ["run","--rm","-i","-v","C:/.../runs:/runs","openstudio-mcp:dev","openstudio-mcp"]
}}}
```
