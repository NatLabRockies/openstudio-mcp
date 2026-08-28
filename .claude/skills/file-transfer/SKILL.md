---
name: file-transfer
description: Move user files to or from a remote openstudio-mcp server — upload local models/measures/weather for server-side tools, or hand results back as download links. Use when a needed file is on the user's machine, or the user wants a file from the server.
---

# File Transfer (remote servers)

Over HTTP the server runs on a different machine than the user. Every file
tool (`load_osm_model`, `apply_measure`, `change_building_location`,
`import_floorspacejs`) takes a **server-side path**, but the user's files are
on their laptop. Never pass file bytes through tool arguments (base64 in-band
is token-prohibitive and leaks bytes into context/logs) — move bytes
out-of-band over signed HTTP routes on the same port.

## Upload (get a local file onto the server)

0. Check first: `list_files()` / `list_uploads()` — staged inputs (e.g. under
   `/inputs`) are already server-visible and need no upload.
1. `request_upload(filename="model.osm", size_bytes=<bytes>)` →
   `{file_id, upload_url, ...}` (optional `sha256` for integrity,
   `kind="measure"` for measure zips)
2. Have the user PUT the raw bytes:
   ```
   curl --upload-file model.osm "<upload_url>"
   ```
3. `get_upload(file_id=<file_id>)` → `server_path` once ready
   (`extracted_path` for a `.zip` — ready for `apply_measure(measure_dir=...)`)
4. Pass that server path to `load_osm_model` / `change_building_location` / etc.

## Download (hand a server file back to the user)

`request_download(path=<server_path>)` or
`request_download(run_id=<run_id>, bundle=True)` → `download_url`; the user
fetches it:
```
curl -O -J "<download_url>"
```
For small text (logs, err files) prefer `read_file` / `get_run_logs` — no
download needed.

## Notes

- Upload URLs are signed (HMAC, short TTL) and op/file-scoped; the bearer
  token never enters a URL. Uploads land in your private per-user area and
  count against a quota; archives are zip-bomb and path-escape guarded.
- `delete_upload(file_id=...)` frees quota.
- Shell-less clients: `python -m mcp_server.tools.osmcp put <file> --kind measure`
  and `python -m mcp_server.tools.osmcp get <server_path>` wrap the same two
  HTTP calls.
