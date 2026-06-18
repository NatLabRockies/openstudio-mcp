# file_transfer

Move user files to/from a **remote (HTTP) openstudio-mcp server** securely.

## Why
Over HTTP the server runs on a different machine than the user. Every file tool
(`load_osm_model`, `apply_measure`, `change_building_location`, `import_floorspacejs`)
takes a **server-side path**, but the user's files are on their laptop. MCP tool
args flow through the LLM, so passing file bytes in-band (base64) is infeasible
(token cost) and leaks bytes into context/logs. This skill moves bytes
**out-of-band** over signed HTTP routes on the same port.

## Flow (upload)
1. `request_upload(filename, size_bytes[, sha256, kind])` → `{file_id, upload_url, ...}`
2. PUT raw bytes: `curl --upload-file model.osm "<upload_url>"`
3. `get_upload(file_id)` → `server_path` (or `extracted_path` for a `.zip`)
4. pass that path to `load_osm_model` / `apply_measure` / `change_building_location`

A `.zip` (or `kind="measure"`) is auto-extracted server-side; `extracted_path`
is the measure dir, ready for `apply_measure(measure_dir=...)`.

## Flow (download)
`request_download(path=...)` or `request_download(run_id=..., bundle=True)` →
`download_url`; `curl -O -J "<download_url>"`. Small text → use `read_file` instead.

## Security
- **Signed URLs** (HMAC, short TTL) authorize the routes — the bearer token never
  enters the URL or the model context; a leaked URL expires fast + is op/file-scoped.
- Uploads land in `RUN_ROOT/<user>/uploads/` — the existing per-user, sandboxed,
  path-allowlisted area. Server mints the `file_id` (client filename can't traverse).
- Enforced: max size (`OSMCP_MAX_UPLOAD_MB`), per-user quota (`OSMCP_USER_QUOTA_MB`),
  optional sha256 integrity, zip-bomb + path/symlink-escape guards on archives.

## Tools
`request_upload`, `get_upload`, `list_uploads`, `delete_upload`, `request_download`.

## CLI (shell-less clients)
`python -m mcp_server.tools.osmcp put <file> --kind measure` /
`python -m mcp_server.tools.osmcp get <server_path>` wrap the same two HTTP calls.
