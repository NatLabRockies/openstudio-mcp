# Multi-user isolation — how to structure per-user storage

This MCP server runs one process that may serve many remote HTTP users at once.
Every place that stores or reads user data must be **scoped to the caller's
identity**, or one tenant can read/write another's files. This doc is the rule of
thumb for adding any new user-data location. Read it before introducing a new
directory, mount, or path argument.

> The single most important rule: **new persistent user data MUST live under an
> identity-scoped root (`user_run_root()` / `user_measures_root()`), never a
> process-global path constant. Never add a per-user dir to `_SHARED_READ_ROOTS`.**

## Identity model (`mcp_server/identity.py`)

- `user_key()` — per-authenticated-user (auth principal `client_id`, else the HTTP
  session id). Keys durable, on-disk, per-user storage and path scope.
- `session_key()` — per-connection. Keys ephemeral *model* state only.
- `LOCAL` (`"local"`) — stdio (single local user) and off-request callers (unit
  tests, atexit) collapse to this. A live HTTP request never resolves to `LOCAL`.

`user_key()` is resolved **per call**, so one code path serves every user — you do
not thread identity through call args.

## The per-user root pattern

Two scoped roots exist today, both in `mcp_server/config.py`:

| Root | Helper | Layout |
|------|--------|--------|
| Runs | `user_run_root()` | `RUN_ROOT` (LOCAL) or `RUN_ROOT/<user_key>` |
| Measures | `user_measures_root()` | `MEASURES_DIR/<user_key>` — **always keyed, incl. `local`** |

Custom (authored) and BCL (downloaded) measures are leaves under the measures root:
`user_custom_measures_dir()` → `MEASURES_DIR/<user_key>/custom`,
`user_bcl_measures_dir()` → `MEASURES_DIR/<user_key>/bcl`.

### "Key every principal; nobody owns the bare root"

`user_run_root()` lets `LOCAL` own the whole `RUN_ROOT` (backward-compat with the
original single-user `/runs/<run_id>` layout). **New roots should NOT copy that
carve-out.** `user_measures_root()` keys *every* principal, including the local user
(`/measures/local/...`). Benefits:

1. **No "sees everything" identity.** No principal maps to the bare `MEASURES_DIR`,
   so even a misrouted `LOCAL` only reaches `/measures/local`, never another tenant.
2. **No name aliasing.** The fixed leaf names (`custom`, `bcl`) live *inside* a key
   dir, so a user literally keyed `"custom"` can't alias another principal's folder.
3. **Simplest access check** — one uniform rule, no special case.

Prefer this shape for any new per-user tree. There is no migration cost for a new
feature.

## The access check (`is_path_allowed`)

`is_path_allowed(p, *, write=False)` is the **primary** boundary for every path
*argument* a tool accepts (read_file, edit_measure, list, download dest, …). Order:

```
own run root            → allow (read+write)
elsewhere under RUN_ROOT → deny           (another tenant's runs)
own measures root        → allow (read+write)
elsewhere under MEASURES_DIR → deny       (another tenant's measures)
write to anything else   → deny           (shared roots are read-only)
under a shared read root → allow (read-only)
```

`_SHARED_READ_ROOTS` is **read-only, global** dirs only: `/repo`, `/inputs`, bundled
`common`/`comstock` measures, `/skills`. **Never** add a per-user tree (runs,
measures) here — that re-exposes every tenant's data. There is a unit guard for this
(`tests/test_measure_isolation.py::test_measures_tree_is_not_a_shared_read_root`).

> The sandbox is NOT a substitute. The OS sandbox (per-tenant uid + Landlock) wraps
> only *measure/sim execution* subprocesses. In-process tool logic
> (create/list/edit/download/read) is guarded **only** by `is_path_allowed`. Get the
> path scoping right; don't lean on the sandbox to cover it.

## Checklist — adding a new user-data location

1. Store under an identity-scoped helper (`user_*_root()` / a new keyed root), never
   a process-global constant or env path that ignores `user_key()`.
2. If you add a new keyed root, key **every** principal (no LOCAL-owns-root) and add
   the own-vs-sibling rule to `is_path_allowed` (allow own, deny elsewhere under the
   parent) **before** the shared-read fallthrough.
3. Do **not** add the new tree to `_SHARED_READ_ROOTS`. Only truly global read-only
   dirs go there.
4. Mount it writable + chownable like `/runs` (so create writes as the server uid and
   the per-tenant sandbox uid can be chowned the execution dir).
5. Add isolation tests: two distinct `user_key`s → disjoint, non-nested paths; and
   `is_path_allowed` denies a cross-tenant path (read AND write). Pattern:
   `monkeypatch.setattr("mcp_server.identity.user_key", lambda: "alice")`.
6. Validate user-supplied path args with `is_path_allowed(..., write=…)`; for
   internal default roots, *skip* a disallowed root rather than erroring (an error
   leaks that another tenant's dir exists).

## Deployment

Mount the per-user trees (`/runs`, `/measures`) as writable volumes the server owns
(or can chown within). Read-only or foreign-owned mounts break create + in-place
test. One shared volume ≠ shared access — per-user subdirs + per-tenant sandbox uids
keep tenants apart at both the app and OS levels.
