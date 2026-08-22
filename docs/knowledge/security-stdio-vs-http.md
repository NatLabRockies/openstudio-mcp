# Security & Isolation: stdio (local) vs HTTP (remote) deployment

**Scope:** how the sandbox, path allow-listing, seccomp, rlimits, identity, and quotas
behave in a **local stdio** deployment versus an **HTTP multi-user** deployment.
Last verified claim-by-claim against the code on 2026-08-22 (line references as of that
date).

**Deployment assumption:** *all* deployments run the project Docker container
(`docker/Dockerfile`, Linux). This matters — the kernel sandbox backends (Landlock,
seccomp) are Linux-only. Because we never run the server as a bare Python process on
Windows/macOS, the "degrade to clean-env only" fallback (`sandbox.py:112-113`) is not a
real deployment scenario. In both stdio and HTTP the full `auto` tier is available.
Run directories are bind-mounted from the host in both modes; that changes *where the
bytes live*, not *what the process is allowed to touch*.

---

## TL;DR

Almost all of the isolation machinery exists to separate **multiple users**. In stdio it
collapses to a single trusted principal (`"local"`), so the multi-tenant features become
no-ops or single-principal. The one layer doing real work in stdio is the **subprocess
sandbox** confining measure/simulation execution — and because we're always in the Linux
container, it is fully effective.

| Mechanism | stdio / local | HTTP / remote |
|---|---|---|
| **Auth** | none (trusted local process) | `token` (default) or `jwt`; `none` only behind VPN |
| **Identity** (`user_key`) | hardcoded `"local"` | JWT `client_id`/`azp`/`sub` or bearer token → sanitized |
| **Subprocess sandbox** (`OSMCP_SANDBOX`) | full `auto`: Landlock + seccomp + rlimits | same, **plus** per-tenant uid |
| **Sandbox uid** | baked `SANDBOX_UID=1001` (server root → child drops) | per-tenant uid 2000–61999 (SHA256 of user key) |
| **Run dirs** | whole `RUN_ROOT` owned by `"local"` | `RUN_ROOT/<user_key>/`, keyed every request |
| **Measures dirs** | `MEASURES_DIR/local/` (still keyed) | `MEASURES_DIR/<user_key>/` |
| **Path allow-list** (`is_path_allowed`) | rejects paths outside RUN_ROOT + RO shared roots | same, plus cross-tenant paths denied R **and** W |
| **Model state** | one shared in-memory model | per-session dict, LRU cap 16, 30-min idle TTL |
| **Quotas** | subprocess rlimits only | rlimits + upload/download quotas + session caps |
| **Concurrency** | process-global FIFO queue (`MAX_CONCURRENCY`) | same queue, optional per-user cap |
| **Audit** | tool calls + sim lifecycle → stderr | same, plus optional audit file; users see only own runs |

---

## 1. Transport & identity — what "stdio" actually means

Transport is selected by `MCP_TRANSPORT` (`server.py:119-128`): unset/`stdio` →
`mcp.run()`; `http`/`streamable-http` → `mcp.run(transport="http", host, port, path)`.

Two identity keys (`identity.py`):

- `session_key()` — ephemeral in-memory model state (per connection). Keyed by the
  FastMCP `session_id` in **both** transports (it has no transport check); a stdio
  process has exactly one connection, so this is one model per server process. Only
  off-request callers (unit tests, atexit) collapse to `"local"`.
- `user_key()` — **durable**: run dirs, path scope, run ownership, sandbox uid. stdio →
  `"local"`; HTTP → auth `client_id` (FastMCP's `JWTVerifier` resolves it as
  `client_id || azp || sub`; `StaticTokenVerifier` maps token → username) → else
  `session_id` → else `"local"`.

`_is_http_transport()` is false for stdio, so `user_key()` short-circuits to `"local"`
(`identity.py:57-78`). **There is no auth middleware in stdio** — the MCP client launches
the server as your own subprocess, so you *are* the trust boundary. Auth (token/JWT) is an
HTTP-only concern; default for HTTP is `token` (secure-by-default), and `MCP_AUTH=none` is
reserved for VPN-only networks.

## 2. Subprocess sandbox (`OSMCP_SANDBOX`) — the layer that still works in stdio

Tiers (`config.py:90-107`, default `auto`, fail-closed: an unrecognized value falls back
to `auto`, never to a weaker tier):

- `off` — passthrough / escape hatch.
- `posix` — clean env + uid drop + rlimits.
- `auto` / `full` / `landlock` (aliases) — posix **plus** Landlock filesystem confinement
  + seccomp network deny. Fail-closed: if a requested kernel backend can't engage, the
  exec shim refuses to run rather than silently downgrading.

The sandbox wraps **every measure/simulation subprocess** — `apply_measure`,
`test_measure`, the post-test `openstudio measure -u`, the sim launch, plus the gbXML
import translation and the python_ems actuator-discovery run — via
`sandbox.wrap_cmd()`, which builds
`python3 -m mcp_server._sandbox_exec --uid N ... -- CMD` (`sandbox.py`,
`_sandbox_exec.py`). This is **not** gated on transport — it protects stdio exactly as it
protects HTTP. Since all deployments are the Linux container, `auto` is always in force.

**uid drop** only happens when the server runs as root (it does, in the container). The
child drops privileges before exec (`_sandbox_exec.py`):

- stdio/local → baked `SANDBOX_UID=1001` (one uid for the single principal).
- HTTP → a stable per-tenant uid in 2000–61999 derived from a SHA256 of the user key
  (`config.py:157-185`; `hashlib`, not builtin `hash()`, so the server's chown and the
  child's setuid agree across processes/restarts). This gives per-tenant
  `RLIMIT_NPROC` fork-bomb budget and DAC isolation between tenants' run dirs.

Env is scrubbed to an explicit allowlist (no prefix matching) so a confined child can't
inherit server secrets/auth tokens.

## 3. seccomp — network deny (part of `auto`)

`_seccomp.py` installs a raw cBPF filter that denies `socket(AF_INET|AF_INET6)` (and
`io_uring_setup`), allowing `AF_UNIX`. A measure or EnergyPlus run cannot open outbound
network sockets. Single-arch filter resolved at runtime; KILL on unexpected arch
(i386/x32). Identical in stdio and HTTP; always active in the Linux container under `auto`.

## 4. Landlock — filesystem confinement of the subprocess

`_landlock.py` applies read-deny-by-default with a narrow allowlist: system dirs and
bundled measures are read-only; **the only writable location is the run_dir** (plus
specific device files — `/dev/null`, `/dev/zero` RW; `/dev/urandom`, `/dev/random` RO).
`/proc` is denied (prevents `/proc/<pid>/environ` secret recovery); `/inputs` is not a
blanket read root (staged per run). Because run dirs are bind-mounts, a runaway measure
still can only write inside the specific run_dir it was handed — the host mount does not
widen the Landlock grant.

## 5. Path allow-listing (`is_path_allowed`) — the *in-process* guard

Distinct from the sandbox: the sandbox confines **subprocesses**; in-process tool logic
(`read_file`, `edit_measure`, `delete_run`, `run_osw` seed copy) is guarded **only** by
`is_path_allowed(p, write=…)` (`config.py:362`; `is_path_allowed_for` at `:329`). Two
independent layers.

- **stdio/local:** `user_run_root()` returns the bare `RUN_ROOT` — the local principal
  owns the entire mounted run tree (`config.py:245-255`). This is intentional: mounting
  the run dir to your filesystem is the point, and single-user layout stays flat.
  Measures are still keyed under `MEASURES_DIR/local/` (nobody owns the bare measures
  root, so no "sees-everything" identity).
- **HTTP/remote:** `user_run_root()` returns `RUN_ROOT/<user_key>/`, keyed on every
  request. Any path outside your own root is denied **read and write**; another tenant's
  `run_id` resolves to "unknown". Disallowed paths are skipped rather than erroring, so
  the API never confirms another tenant's dirs exist.

Shared roots (`/repo`, `/inputs`, bundled measures, `/skills`, and the
openstudio-standards gem weather dirs that `list_weather_files` advertises — issue
#121) are read-only in both modes (`_SHARED_READ_ROOTS`). Symlinks: in-process readers
such as `read_file` resolve the link and allow-list the **target** (a link pointing
outside the allowed roots resolves outside and is denied); the measure-authoring
copy-back readers (`measure -u` XML/README, `test_measure`) additionally use
`read_file_bounded` (`O_NOFOLLOW`, TOCTOU-safe) and `reject_escaping_symlinks`; chown
uses `lchown` to block symlink-traversal escalation.

## 6. "filelock" — there isn't one

No `filelock`/`flock` in the codebase. Concurrency is handled by:

- an `RLock` around the in-memory model dict (`model_manager.py`);
- a process-global **FIFO run queue** capped by `MAX_CONCURRENCY` (default 1), with an
  optional `MAX_CONCURRENCY_PER_USER`;
- a SQLite run registry for atomic run status.

One server process serves everyone, so these are identical across transports — in stdio a
single client feeds the queue.

## 7. Quotas & resource limits

- **HTTP-only:** upload/download quotas (`OSMCP_MAX_UPLOAD_MB` 200,
  `OSMCP_USER_QUOTA_MB` 4 GB), zip-bomb guards (uncompressed size + entry count), signed
  upload-URL TTL, and session memory caps (`OSMCP_MAX_SESSIONS` 16,
  `OSMCP_SESSION_TTL` 30 min). These exist because remote users push files and hold
  sessions. The file-transfer tools are registered under stdio too, but they mint
  signed URLs that only the HTTP routes serve, so uploads (and their quotas) are
  unusable there; stdio's single connection never approaches the session caps.
- **Both modes:** subprocess rlimits — `RLIMIT_FSIZE` 10 GB, `RLIMIT_NPROC` 1024;
  `RLIMIT_CPU` and `RLIMIT_AS` are off by default so long annual sims and the
  EnergyPlus/OpenStudio allocators aren't killed (`config.py:191-195`). Sim wall-clock is
  bounded by `OSMCP_SIM_TIMEOUT_SECONDS` (default 7200), enforced by the dispatcher with a
  process-group kill (TERM group → KILL) that reaps forked EnergyPlus children without
  signalling the server.

## 8. Audit

One JSON line per tool call (user, session, tool, args preview, ok, duration) plus sim
lifecycle events, written to stderr (→ `docker logs`) in both modes, and optionally to
`MCP_AUDIT_FILE`. `MCP_AUDIT=off` disables. End users only ever see their own run logs via
the MCP API (ownership- and path-scoped); operators see everything via container logs.

---

## Is local stdio + Docker safe?

Short answer: yes, for the threat model it was built for. Docker + stdio is the strongest
local configuration. But "safe" has edges worth naming.

**What you are genuinely protected against.** The real threat is LLM-authored measure/sim
code (an agent generating Ruby/Python that could be buggy or malicious). That code runs as
a subprocess confined by Landlock (writes only its run_dir), seccomp (no network sockets),
a dropped uid, and rlimits (no fork bomb). Docker adds a second boundary underneath. On
Windows, Docker Desktop runs a Linux VM, so there is also a hypervisor boundary between the
container and the host. No auth surface is exposed because stdio has no network listener.

**Three edges that "safe" does not cover:**

1. **The sandbox confines the subprocess, not the server.** The MCP server's own Python
   (all 150+ tools) runs unconfined inside the container, guarded only by
   `is_path_allowed`. The trust boundary is "server code trusted, measure code untrusted."
   A bug in a tool that bypasses `is_path_allowed` can read/write anywhere the container
   can reach. The server process itself also legitimately has network access (BCL/weather
   downloads), so seccomp net-deny does not apply to it.

2. **Whatever you bind-mount is in scope.** The server can write anywhere `is_path_allowed`
   permits, which is `RUN_ROOT` plus the measures root. Mount narrowly: mount `runs/` only,
   not the whole repo, home dir, or a drive root. Files land on the host owned by the
   container uid (root inside the container); check how that maps on the host.

3. **The sandbox stops code escape, not tool misuse.** A confused or prompt-injected agent
   can still call destructive tools that are legitimately exposed (`delete_run`,
   `edit_measure`, overwriting files) within `RUN_ROOT` and the measures root. That is
   within the allowed scope by design. If anything you care about lives under those roots,
   it is reachable.

So: safe as a local single-user tool against measure/sim code escaping, which is the
point. Not a substitute for treating the mounted directory and the exposed tool set as
"things an autonomous agent can fully act on." Mount narrow, and do not point run dirs at
anything you would not hand the agent write access to.

## Bottom line for local stdio

What actually protects a local stdio deployment:

1. **The subprocess sandbox** — Landlock + seccomp + rlimits confining measure/sim
   execution. Fully effective because deployments always run in the Linux container. A
   measure can't escape its run_dir, can't open the network, and runs under a dropped uid.
2. **`is_path_allowed`** keeping in-process file tools inside `RUN_ROOT` + read-only
   shared roots — with one `"local"` principal owning the whole run tree.

What is effectively inert in stdio (by design — single trusted user): auth, per-user root
separation, per-tenant uids (collapsed to 1001), and the upload/session quotas. The model
trusts the local operator and focuses on preventing LLM-authored measure/sim code from
escaping its run directory or making network calls. Multi-tenant separation (per-user
roots, per-tenant uids, auth, quotas) only engages under HTTP.

See also: `docs/security-isolation.md` (identity + per-user root design),
`docs/remote-multi-user.md` (HTTP deployment guide).
