# Security Policy

## Scope

This document covers the `openstudio-mcp` MCP server — a container-bound process that gives
AI agents programmatic control of building energy models via the OpenStudio SDK.

---

## Path Safety

### Allowed Roots

All file operations (`read_file`, `copy_file`, `run_osw`, `validate_osw`, etc.) are restricted
to a fixed set of allowed path roots enforced by `is_path_allowed()` in `mcp_server/config.py`:

| Root | Default | Env Override |
|---|---|---|
| `/runs` | Run outputs, simulation artifacts | `OPENSTUDIO_MCP_RUN_ROOT` |
| `/inputs` | User-provided models and weather files | `OPENSTUDIO_MCP_INPUT_ROOT` |
| `/repo` | Server source code (read-only use cases) | — |
| Bundled measures dirs | ComStock and common measures | — |
| Skills dir | Skill Markdown guides | — |

Any path that resolves (after symlink expansion) outside these roots is rejected with
`{"ok": false, "error": "invalid_path"}`. Symlink traversal is prevented by calling
`Path.resolve()` before comparison.

### Path Traversal Mitigations

| Attack Vector | Mitigation |
|---|---|
| `../../etc/passwd` in `file_path` | `Path.resolve()` + allowlist check |
| `../../etc` in `copy_file` `destination` | Same: both source and destination validated |
| `../model.osm` in `seed_file` (OSW) | Flattened to `basename` before staging into run dir |
| Symlink escape from `/runs` | `resolve()` follows symlinks before allowlist check |

### What Is Not Protected

- **Denial of service** via large file reads: `read_file` defaults to 50 KB (`max_bytes=50_000`)
  but callers can override `max_bytes`. No upper-bound cap is enforced — consider adding one
  if exposing this server to untrusted clients.
- **EnergyPlus subprocess**: The simulation runner (`run_simulation`, `run_osw`) invokes
  `openstudio run` as a subprocess. The OSM/OSW content is caller-controlled; a malicious model
  could cause unexpected EnergyPlus behavior. The container boundary is the primary mitigation.

---

## Container Isolation

The server is designed to run inside a Docker container with explicit volume mounts:

```
docker run --rm \
  -v "/path/to/models:/inputs" \
  -v "/path/to/outputs:/runs" \
  openstudio-mcp:latest
```

- The host filesystem is **not mounted** except for the two explicit volumes.
- By default, the server performs no outbound network calls; OpenStudio/EnergyPlus
  are fully offline. **Exception:** when `TRACELOOP_BASE_URL` is set, the server
  exports traces to that OTLP endpoint.
- The server process runs as the user defined by the container runtime. The repo
  Dockerfile does not set a `USER` instruction — it runs as root by default.
  Production deployments should add a non-root `USER` in a derived image.

---

## Stdout / MCP Transport Integrity

OpenStudio's SWIG bindings emit log warnings to C stdout. This would corrupt the JSON-RPC
transport (MCP communicates over stdio). Two mitigations are applied at startup in `server.py`:

1. `silence_openstudio_stdout_logger()` — sets OpenStudio's standard-out logger to `Fatal`
   level, suppressing operational warnings.
2. `redirect_c_stdout_to_stderr()` — permanently redirects C-level stdout (fd 1) to stderr,
   with Python's `sys.stdout` on a private pipe to the MCP client. This is a backstop for
   any C-extension output that bypasses the logger.

These mitigations prevent log injection into the MCP JSON-RPC stream.

---

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Email the maintainers directly or use GitHub's
[private security advisory](https://github.com/settings/security-advisories) feature. Include:

- A description of the vulnerability and its impact
- Steps to reproduce (minimal repro preferred)
- Affected versions or commits

We aim to acknowledge reports within 72 hours and provide a fix or mitigation within 14 days
for confirmed issues.

---

## Known Limitations / Out of Scope

- **Authentication / authorization**: The MCP server has no built-in auth. Access control is
  the responsibility of the MCP client and the host environment.
- **EnergyPlus model content**: The server executes whatever EnergyPlus model the caller
  provides. Malicious model content is an EnergyPlus concern, not an MCP server concern.
- **Multi-tenancy**: The server holds a single shared in-memory model. It is not designed for
  simultaneous untrusted multi-user access.
