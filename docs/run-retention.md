# Run retention & garbage collection

Every simulation leaves a run directory under the run root — roughly **40 MB**
each (the 23 MB `eplusout.sql`, plus `.eso`/`.mtr`, the HTML tables, logs). Left
alone they accumulate forever. Retention reclaims them. It is **off by default**
and only ever touches simulation run directories.

There are two halves:

- a **background daemon** that auto-deletes old run dirs (opt-in), and
- four **MCP tools** the agent calls on demand (`cleanup_runs`, `delete_run`,
  `pin_run`, `unpin_run`) — these work whether or not the daemon is enabled.

---

## 1. Enabling the auto-GC daemon

Off by default — nothing is deleted automatically until you turn it on. The
daemon is started in `server.main()`; it spawns a background thread
(`sim-retention`) only when the effective window is greater than 0.

Three ways to turn it on (CLI wins over env):

| Method | Effect |
|---|---|
| `openstudio-mcp --gc` | enable with a 7-day window (or the env window, if set) |
| `openstudio-mcp --gc-days 14` | enable with an explicit 14-day window |
| `OSMCP_RUN_RETENTION_DAYS=14` | enable via env (docker `-e`, mcp.json `env`) |
| *(nothing)* | **off** |

Precedence: `--gc-days N` > `--gc` > `OSMCP_RUN_RETENTION_DAYS` > off.
`--gc-days 0` is an explicit "stay off".

```bash
# HTTP server, GC on at 14 days
docker run -d -p 8000:8000 -e MCP_TRANSPORT=http -v /data/runs:/runs \
  openstudio-mcp:dev openstudio-mcp --gc-days 14
```
```jsonc
// stdio (mcp.json): enable GC for the local container
{ "mcpServers": { "openstudio-mcp": {
  "command": "docker",
  "args": ["run","-i","--rm","-v","C:/runs:/runs","openstudio-mcp:dev","openstudio-mcp","--gc"]
}}}
```

The daemon sweeps every `OSMCP_RETENTION_SWEEP_SECONDS` (default `3600`, **60s
floor**), starting with one sweep at boot.

---

## 2. What gets deleted

A directory is removed only if it passes **every** gate — miss one and it is
skipped:

1. **It's a real directory, not a symlink.** Symlinks are never followed or removed.
2. **It physically sits at `RUN_ROOT/<user>/<run>`** (or `RUN_ROOT/<run>` for the
   local single user) — verified against the *resolved* path, so nothing whose
   real location is outside the run root can be touched.
3. **It looks like a run** — contains `run_record.json`, `out.osw`, or a `run/`
   subdir. A plain saved `.osm` model has none of these and is never a target.
4. **It isn't a working dir** — directories named `examples/` or `exports/` are
   excluded by name (your saved models and exports are safe).
5. **It isn't pinned** — no `.pinned` marker (see [Pinning](#4-pinning)).
6. **It isn't active** — `run_record.json` status is terminal. A `queued` run, or
   a `running` run whose PID is still alive, is skipped. An unreadable record is
   treated as active (fail-safe).
7. **It's old enough** — age ≥ the window. Age is taken from the run record's
   `ended_at` (when the sim finished), falling back to the directory's mtime.

So: a real, non-symlink run directory, in the right place, with a sim-output
fingerprint, terminal, unpinned, and past the window.

---

## 3. Safety guarantees

The GC is confined so a bug or misconfiguration can't reach beyond run dirs:

- **No escape from the run root.** Before any delete, the resolved path must be a
  genuine child of the swept root (`_is_real_child`). A run-shaped **symlink**, or
  any entry resolving outside the tree, is rejected — deletion never follows a
  link out of `RUN_ROOT`.
- **No system roots.** The daemon refuses to start or sweep if `RUN_ROOT` resolves
  to `/`, `/home`, `/etc`, `/tmp`, `/usr`, `/var`, … (`_run_root_is_sane`); it logs
  `retention_disabled(reason=unsafe_run_root)` instead. Guards against a bad
  `OSMCP_RUN_ROOT`.
- **Run dirs only.** The fingerprint + name exclusions mean saved models, exports,
  inputs, measures, and `/repo` are never deletion candidates — the sweep only
  iterates inside `RUN_ROOT`.
- **Two levels deep, max.** The daemon walks `RUN_ROOT/<user>/<run>` (and, for the
  local single-user layout, `RUN_ROOT/<run>`) — never a deep recursive walk.

---

## 4. Pinning

Pin a run to keep it indefinitely, exempt from auto-GC:

```text
pin_run(run_id)     → writes a .pinned marker in the run dir
unpin_run(run_id)   → removes it, run is eligible again
```

Use it for reference baselines you want to revisit after the window.

---

## 5. On-demand cleanup (works with the daemon off)

The agent can reclaim disk deliberately, scoped to the caller's own runs:

| Tool | What it does |
|---|---|
| `cleanup_runs(older_than_days=None, dry_run=True)` | Preview, then delete. Defaults to the active GC window (or 7 days if GC is off). `dry_run=True` lists candidates + MB without deleting; `dry_run=False` deletes. `older_than_days=0` = all terminal runs. |
| `delete_run(run_id)` | Delete one run dir (refuses while queued/running — cancel first). |
| `pin_run` / `unpin_run` | Protect / unprotect a run from auto-GC. |

A typical flow: `cleanup_runs(dry_run=True)` → see "would free 4.2 GB / 130 runs"
→ `cleanup_runs(dry_run=False)`.

---

## 6. Storage layout

Where run dirs live depends on the transport (identity):

| Mode | Run root | Run dir |
|---|---|---|
| stdio (single local user) | `RUN_ROOT` (`/runs`) | `/runs/<run_id>/` |
| HTTP (per session/principal) | `RUN_ROOT/<user>` | `/runs/<user>/<run_id>/` |

The GC handles both: it sweeps `RUN_ROOT`'s direct-child run dirs (local layout)
and descends into each `RUN_ROOT/<user>` dir (multi-user layout). User container
dirs aren't runs (no fingerprint), so they're never deleted as a unit.

---

## 7. Audit trail

Every reclaim and pin is logged as one JSON line (stderr, and `MCP_AUDIT_FILE` if
set) — so "who/what was reclaimed, when" is answerable:

```jsonc
{"ts":1718136600.0,"event":"run_evicted","reason":"gc",      "run_id":"…","user":"alice","age_days":8.2,"freed_mb":50.2}
{"ts":1718140000.0,"event":"run_evicted","reason":"cleanup", "run_id":"…","user":"bob","age_days":3.1,"freed_mb":41.0}
{"ts":1718140100.0,"event":"run_deleted",                    "run_id":"…","user":"bob","freed_mb":39.8}
{"ts":1718140200.0,"event":"run_pinned",                     "run_id":"…","user":"alice"}
```

`reason` is `gc` for the daemon and `cleanup` for the `cleanup_runs` tool.

---

## 8. Configuration reference

| Var / flag | Default | Purpose |
|---|---|---|
| `--gc` (CLI) | — | enable auto-GC with a 7-day window (or the env window) |
| `--gc-days N` (CLI) | — | enable auto-GC with an N-day window (`0` = off) |
| `OSMCP_RUN_RETENTION_DAYS` | `0` (off) | enable auto-GC via env; window in days |
| `OSMCP_RETENTION_SWEEP_SECONDS` | `3600` | sweep interval (60s floor) |
| `OSMCP_RUN_ROOT` | `/runs` | base directory for run dirs |
| `MCP_AUDIT` / `MCP_AUDIT_FILE` | `on` / — | audit logging of evictions |

Recommended posture: leave GC **off** for single-user/dev; for a shared HTTP box,
enable `--gc-days 7` (or longer) and `pin_run` the baselines you want to keep.
