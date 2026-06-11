# Plan: Remote File Transfer (HTTP deployment)

**Branch:** `feat/remote-file-transfer` (off `origin/develop` @ 6c5d0e0)
**Depends on:** multi-user-remote-mcp (HTTP transport, token/JWT auth, per-user
`RUN_ROOT/<user_key>/`, path allowlist, per-tenant-UID sandbox) — all shipped.
**Status:** Implemented + verified — 24/24 (7 integration over HTTP harness + 17
unit) pass in Docker; ruff clean. New skill `mcp_server/skills/file_transfer/`,
CLI `mcp_server/tools/osmcp.py`, CI shard 4, docs §6.

**Q1 resolved (empirically):** FastMCP `custom_route` is NOT behind the `auth=`
verifier — a custom route serves 200 with no/bad token. So signed URLs are the
route's authorization (not optional). No bearer required on the routes.

## 1. Problem

Remote/HTTP server: every file tool takes a **server-side path**
(`load_osm_model(osm_path)`, `apply_measure(measure_dir)`,
`change_building_location(weather_file)`, `import_floorspacejs`). User's `.osm`,
custom measure **.zip**, `.epw`/`.ddy`/`.stat`, FloorspaceJS `.json` live on the
**laptop**. No path on the server points at them.

Why in-band (base64 tool arg) is dead: MCP tool args are emitted by the LLM, so
a 1 MB OSM ≈ 1.4 MB base64 ≈ ~350K tokens — and file bytes would land in context
+ audit logs. **Bytes must move out-of-band, beside the protocol, not through it.**

## 2. Locked decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Out-of-band HTTP, not in-band base64** | Cost + log hygiene; only viable path for real model files |
| 2 | **Local-disk sidecar** (not object store) | Matches Pattern-A target (VPN/Tailscale single box); reuses all isolation. Object store = multi-box follow-up |
| 3 | **Presigned (HMAC) URLs**, not bearer-on-route | Authenticated `request_upload` mints short-TTL signed URL bound to (user, file_id, op). Route verifies signature → token never enters model context; leaked URL expires fast + scoped to one file |
| 4 | **Land in existing sandbox**: `RUN_ROOT/<user_key>/uploads/<file_id>/` | Already the only writable, per-tenant-UID, allowlisted area — `is_path_allowed`, UID drop, `reject_escaping_symlinks` reused for free |
| 5 | **Auto-extract archives on ingest** | `.zip` → guarded extract, return resolved dir for `apply_measure`. One round-trip |
| 6 | **One general ingest tool**, type-agnostic transport | Per-type logic is post-ingest only (OSM single file / weather set / measure dir) |
| 7 | **Both uploaders**: agent-curl default + thin CLI fallback | Claude Code/Cursor/VS Code have local shell; CLI for shell-less clients |
| 8 | **Existing consuming tools unchanged** | They already accept allowlisted paths; uploads land under the user's own run root = readable |

## 3. Flow

```
request_upload(filename, sha256, size, kind?)   ← authenticated MCP call
   → server: mint file_id, mkdir uploads/<file_id>/, record pending meta,
             return {file_id, upload_url=signed, expires_at, max_size}
[agent] curl --upload-file model.osm "<upload_url>"   ← out-of-band PUT, no bearer
   → route /files/u/{file_id}?sig=…&exp=…: verify HMAC+TTL+size, stream to disk,
             verify sha256, (if .zip/kind=measure) guarded extract, mark ready
get_upload(file_id)  → {ready, server_path, extracted_path?}
load_osm_model(osm_path=server_path)   ← existing tool, unchanged
```

Download (outputs back): `request_download(path|run_id+artifact)` → signed GET URL
→ `GET /files/d/{token}` streams bytes (saved OSM, HTML reports, CSV). `read_file`
stays for small text; binary GET is for large/binary artifacts.

## 4. Components

- **New skill `mcp_server/skills/file_transfer/`**
  - `tools.py` — `request_upload`, `get_upload`, `list_uploads`, `delete_upload`,
    `request_download`; plus `@mcp.custom_route` for `PUT /files/u/{id}` +
    `GET /files/d/{token}`. All thin → call operations.
  - `operations.py` — file_id minting, HMAC sign/verify, streamed write w/ size
    cap, sha256 verify, archive extraction guards, quota accounting. (split if >250 LOC)
  - `SKILL.md`
- **`config.py`** — `OSMCP_MAX_UPLOAD_MB` (default 200), `OSMCP_USER_QUOTA_MB`,
  `OSMCP_FILE_SIGNING_KEY` (HMAC secret; refuse to start signed URLs if unset on
  HTTP), `OSMCP_UPLOAD_URL_TTL` (default 300s). `uploads/` already under run_root
  → `is_path_allowed` covers it.
- **CLI helper** `tools/osmcp_put.py` / `osmcp_get.py` (or a `osmcp` console entry)
  — calls `request_upload`, curls bytes. ~50 LOC each.
- **Docs** — extend `docs/remote-multi-user.md`; client-setup snippet.

## 5. Security

| Threat | Mitigation | Source |
|---|---|---|
| Bytes in LLM ctx / audit log | Out-of-band channel; log name/size/sha256 only | new |
| Token leakage to model | Presigned URL carries no bearer | new |
| Cross-tenant read/write | file_id under `user_key`; download path checked vs requester run_root | reuse (run-ownership pattern) |
| Path traversal via filename | **Server** mints file_id path; filename = metadata only, sanitized | new |
| Malicious measure/OSM | Exec as dropped tenant UID under Landlock+seccomp | reuse sandbox |
| Zip-bomb | Decompressed-size cap + entry-count cap | new |
| Zip path/symlink escape | Reject `..`/absolute entries; `reject_escaping_symlinks` on extracted tree | reuse + new |
| Integrity | client `sha256` verified on close | new |
| Resource exhaustion | per-upload size cap (mid-stream abort) + per-user quota + TTL GC | new |
| URL replay | short TTL + one-time consume on PUT | new |
| TLS | deployer perimeter (VPN/proxy) | unchanged |
| **DAC: sandbox UID must read uploads** | ensure `uploads/` perms let dropped tenant UID read at measure/sim exec (apply_measure already copies measure into run dir before exec) | integration w/ sandbox — verify |

## 6. Tests (split: functional vs adversarial)

**`tests/test_file_transfer.py`** — functional, CI shard 4: upload→`load_osm_model`
round-trip; measure `.zip` auto-extract → `list_measure_arguments`; download round-trip.

**`tests/test_security_file_transfer.py`** — adversarial; auto-runs in `security.yml`
on amd64 + arm64 (globs `test_security_*.py`): forged-sig 403; traversal filename
neutralized; sha/size tampering 422; oversize at mint + mid-stream 413; cross-user
read/download denied; **download path-escape (`/etc/passwd`) denied (exfil guard)**;
upload replay 409; **zip-bomb over the live route 422**; **per-user quota enforced**;
**isolation under real token auth (signed PUT needs no bearer)**.

**`tests/test_file_transfer_unit.py`** — `-m unit`, Docker (no openstudio): HMAC
sign/verify + tamper/expiry/wrong-op; filename sanitize (parametrized); archive
guards (escape, symlink member, bomb, entry cap, clean); finalize size/sha mismatch.

Verified: 17 unit + 3 functional + 10 security = 30 pass; ruff clean; full
`-m "not integration"` = 218 pass (tool-count gates updated 146→151).

## 7. Out of scope (follow-ups)

- Object store (S3/MinIO presigned) for multi-box / cloud
- Resumable/chunked upload for very large files
- Antivirus/content scanning beyond magic-byte + sandbox
- Client-native file sync (no MCP host supports it today)

## 8. Decisions taken (was: unresolved)

1. **custom_route auth** — RESOLVED: not behind `auth=`; signed URL is the route
   authz. No bearer on routes.
2. **Size cap** — `OSMCP_MAX_UPLOAD_MB=200`, env-tunable (smart default).
3. **Quota** — `OSMCP_USER_QUOTA_MB=4096`, env-tunable; checked at mint against
   `uploads/` size. (Standalone, not folded into run-retention GC.)
4. **CLI** — `python -m mcp_server.tools.osmcp put|get` (module entry, no pyproject
   console script needed). Agent-curl remains the default path.
5. **Signing key** — auto-generate + persist `RUN_ROOT/.file_signing_key` (0600)
   if `OSMCP_FILE_SIGNING_KEY` unset; env overrides for rotation/multi-box.
6. **Report download** — both: single-file GET (`path=`) and zip-on-the-fly bundle
   (`run_id=...&bundle=True`).

## 9. Residuals / follow-ups

- DAC: uploaded files are written by the server process; `apply_measure` copies
  the measure into a per-run dir and the sandbox chowns it to the tenant uid
  before exec, so the dropped uid reads the copy (not the upload) — verified by
  `test_measure_zip_autoextract`. Watch if a future tool reads an upload *in place*
  under the dropped uid.
- Single `.epw` upload has no `.ddy`/`.stat` companions — upload them together as
  a `kind="weather"` zip (auto-extracted side by side) or as separate files.
- Object store (S3/MinIO presigned) still the multi-box / cloud follow-up.
