# Plan — Per-user measures isolation (fix PR #65 regression)

Status: ready to implement. Targets the open PR branch `measure-updates` (PR #65),
so the fix lands before merge.

## Problem (scoped to PR #65 diff only)

PR #65 moved authored/downloaded measures from the per-user run root to a flat,
process-global `/measures` tree, breaking HTTP multi-tenant isolation. The
isolation machinery (`user_run_root`, `user_key`, `is_path_allowed`,
`_SHARED_READ_ROOTS`) is pre-existing develop code and was **not** changed by the
PR — only its *usage* regressed. Concrete leaks introduced by the PR:

- `measure_authoring/operations.py` `custom_measures_dir()` →
  `CUSTOM_MEASURES_DIR.resolve()` (was `user_run_root()/"custom_measures"`). Shared
  across all tenants; `create_measure` writes directly (no `is_path_allowed`) and
  `shutil.rmtree`s a name collision → cross-tenant overwrite/destruction.
- `measures/operations.py` `list_local_measures` discovery roots include
  `CUSTOM_MEASURES_DIR`, `MEASURES_DIR` (walks every tenant's subtree), and
  `RUN_ROOT/"custom_measures"` (points at **LOCAL's** dir, not the caller's).
- `measures/operations.py` `download_measure_archive` defaults to shared
  `BCL_MEASURES_DIR`, validates against shared `MEASURES_DIR`, gates with a *read*
  `is_path_allowed` then writes directly.
- `config.py` adds `USER_MEASURES_DIR`/`MEASURES_DIR`/`CUSTOM_MEASURES_DIR`/
  `BCL_MEASURES_DIR` to `_SHARED_READ_ROOTS` → the whole `/measures` tree is
  world-readable across tenants.

Security note: most measure ops (`create`/`list`/`edit`/`download`/`read_file`)
run **in-process** (server uid) and are guarded **only** by `is_path_allowed` — the
OS sandbox (per-tenant uid + Landlock) wraps **execution only** (ops lines ~513,
~1144). So correct path scoping is the primary boundary, not backed up by the
sandbox.

## Decisions (resolved)

1. Custom measures = per-user (measure-authoring's private write area).
2. BCL downloads = per-user (full isolation; no shared cache).
3. Layout: **every user gets a private folder named by their user ID; nobody can
   reach the top `/measures` folder.** Path shape `MEASURES_DIR/<user_key>/{custom,bcl}`
   — e.g. `/measures/alice/custom`, `/measures/bob/custom`, and the desktop/stdio user
   at `/measures/local/custom`. The access rule is one line: "you may touch
   `/measures/<your-id>/…` and nothing else under `/measures`."
   - Why include `local` as just another ID (instead of letting the local user own the
     top folder, like `/runs` does): so **no identity maps to "all measures."** If any
     request were ever mislabeled `local`, it still only reaches `/measures/local/`, not
     everyone's. And it prevents an accidental shared folder if a real user's ID happens
     to be the word `custom`/`bcl` (those names now only live *inside* a user folder).
   - `/runs` only uses the older "local owns the root" style for backward-compat with
     existing run dirs; measures is new, so we use the cleaner, safer shape for free.
4. No operator "shared drop-zone" measures dir — bundled `common`/`comstock` cover
   shared read-only libraries. (Skipped.)
5. Deployment requirement (file permissions, not layout): **mount `/measures` as a
   normal writable volume the server owns — exactly like `/runs` today.** Two OS
   accounts write here: the main server (creates/downloads measures) and the
   locked-down per-tenant account that runs a measure test (the server chowns just that
   one measure folder to it, same dance as run dirs). If `/measures` were read-only or
   owned by an unmanageable account, create + in-place test break. One shared volume ≠
   shared access — per-user subfolders + per-tenant accounts (uid drop + Landlock) keep
   tenants apart at both the app and OS levels.
6. Signed file-transfer routes: no change. They reference run dirs only; with
   `/measures` out of `_SHARED_READ_ROOTS`, `is_path_allowed_for` denies all
   `/measures` paths by default (correct).
7. No data migration (feature unmerged). Pre-feature legacy custom measures stay
   discoverable per-caller via `user_run_root()/"custom_measures"`.

## Design

Mirror `user_run_root()`, but always keyed:

```python
# config.py
def user_measures_root() -> Path:
    from mcp_server.identity import user_key
    root = (MEASURES_DIR / user_key()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root

def user_custom_measures_dir() -> Path:
    d = (user_measures_root() / "custom").resolve(); d.mkdir(parents=True, exist_ok=True); return d

def user_bcl_measures_dir() -> Path:
    d = (user_measures_root() / "bcl").resolve(); d.mkdir(parents=True, exist_ok=True); return d
```

`is_path_allowed()` — insert before the write/shared fallthrough (after the
`RUN_ROOT` block):

```python
    if _under(rp, user_measures_root()):
        return True              # own measures area: read + write
    if _under(rp, MEASURES_DIR):
        return False             # another tenant's measures area
```

## Code changes

### `mcp_server/config.py`
- Add `user_measures_root` / `user_custom_measures_dir` / `user_bcl_measures_dir`.
- Add the two-line measures rule to `is_path_allowed`.
- **Remove** `USER_MEASURES_DIR`, `MEASURES_DIR`, `CUSTOM_MEASURES_DIR`,
  `BCL_MEASURES_DIR` from `_SHARED_READ_ROOTS` (the tree is now governed by the rule
  above).
- **Remove** the flat `CUSTOM_MEASURES_DIR` / `BCL_MEASURES_DIR` constants and their
  `OPENSTUDIO_MCP_CUSTOM_MEASURES_DIR` / `OPENSTUDIO_MCP_BCL_MEASURES_DIR` env
  overrides (a flat override silently breaks isolation). Keep `MEASURES_DIR` /
  `USER_MEASURES_DIR` (mount root) configurable via `OPENSTUDIO_MCP_MEASURES_DIR`.
- `grep` for any other importers of the removed constants.

### `mcp_server/skills/measure_authoring/operations.py`
- `custom_measures_dir()` → `return user_custom_measures_dir()`; swap import
  (`CUSTOM_MEASURES_DIR` → `user_custom_measures_dir`).
- Effect restored: a caller's own custom measure is now `is_path_allowed(..., write=True)`,
  so `test_measure` tests **in place** again and the `measure.xml` update persists
  (per-user), instead of the throwaway-copy path the PR forced.

### `mcp_server/skills/measures/operations.py`
- `list_local_measures` default roots → `user_custom_measures_dir()` /
  `user_bcl_measures_dir()` / `user_run_root()/"custom_measures"` (legacy, per-caller)
  / `COMMON_MEASURES_DIR` / `COMSTOCK_MEASURES_DIR` / `INPUT_ROOT/"measures"`. Drop the
  `MEASURES_DIR` sibling-walk. For these *internal* roots, `continue` when
  `not is_path_allowed(root)`; keep the hard error only for a user-supplied `root_dir`.
- `download_measure_archive` → default dest `user_bcl_measures_dir()`,
  `measures_root = user_measures_root()`, gate `is_path_allowed(destination_root, write=True)`.
- `find_measure` inherits both automatically (no change).

## Tests (red-green)

Write the regression tests first, confirm they FAIL on the current PR branch, then
implement to green.

### Unit — `tests/test_measure_isolation.py` (new; monkeypatch `identity.user_key`)
The test that would have caught PR #65:
```python
# Regression: PR #65 moved custom measures to a flat shared /measures/custom,
# breaking HTTP multi-tenant isolation. Each tenant's dir must be distinct + non-nested.
def test_custom_measures_dir_is_per_tenant(monkeypatch):
    monkeypatch.setattr("mcp_server.identity.user_key", lambda: "alice"); a = custom_measures_dir()
    monkeypatch.setattr("mcp_server.identity.user_key", lambda: "bob");   b = custom_measures_dir()
    assert a != b
    assert not str(a).startswith(str(b)) and not str(b).startswith(str(a))
```
Plus:
- `test_is_path_allowed_denies_other_tenant_measures` — alice rw own; alice on
  `/measures/bob/...` denied (read AND write); same for bcl sibling.
- `test_list_local_measures_excludes_other_tenant` — seed alice + bob trees; list as
  alice → only alice's entries.
- Parametrized invariant (closes the whole class): for `user_run_root`,
  `user_measures_root`, `custom_measures_dir`, `user_bcl_measures_dir`, two distinct
  keys → disjoint, non-nested paths.

### Integration — add to `tests/test_measure_discovery.py` (HTTP, two authed sessions)
Mirror `test_session_isolation.py`: distinct `client_id`s (auth on). User A
`create_measure` → A's `list_custom_measures` sees it; B's is empty; B
`edit_measure` / `test_measure` on A's `measure_dir` → `ok:false`, "not allowed".

### CI (`.github/workflows/ci.yml`)
- Unit file → lightest shard's `FILES=`.
- Integration → the shard already running `http_server` tests (where
  `test_session_isolation` lives).
- `EXPECTED_TOOLS` unchanged (no tool names added/removed by this fix).

## Docs & repo knowledge (committed only — `.claude/rules/` is gitignored)

- **New `docs/security-isolation.md`** — canonical "how to structure per-user
  storage": identity model (`user_key`/`LOCAL`, stdio=local), the
  `user_run_root()`/`user_measures_root()` per-user-root pattern, "key every
  principal / nobody owns the bare root," `is_path_allowed` semantics (own=rw,
  sibling-under-shared-parent=deny, shared roots=read-only), and a checklist for
  adding any new user-data location.
- **`docs/remote-multi-user.md`** — fix line 117 ("shared reference dirs (measures,
  /inputs) are read-only" — now false); §3 state custom+downloaded measures are
  per-user rw under the measures root; §5 add `OPENSTUDIO_MCP_MEASURES_DIR`.
- **`docs/architecture.md`** §Security — update the `is_path_allowed` allowlist
  description (~lines 105/110) to include the per-user measures root; drop
  "measures = shared read-only".
- **`docs/testing/testing.md`** — security tier: every per-user path helper needs a
  two-identity disjoint-path test + the cross-tenant negative pattern.
- **`CLAUDE.md`** — one-line rule + pointer to `docs/security-isolation.md`
  (e.g. "New persistent user data MUST live under an identity-scoped root
  (`user_run_root()`/`user_measures_root()`), never a process-global constant;
  never add a per-user dir to `_SHARED_READ_ROOTS`; validate path args via
  `is_path_allowed(..., write=…)`").
- **`.claude/skills/measure-authoring/SKILL.md`** (tracked) — note measures are
  per-user/private in multi-user mode.

## Why PR #65 slipped through

`tests/test_path_safety.py::test_distinct_uid_per_tenant` already monkeypatches
`user_key` to two tenants for UIDs — the exact 3-line pattern that would have failed
here was never applied to the storage-path helpers. With single-user
`user_key()=="local"`, flat and per-user paths are identical, so every existing test
stayed green; the bug is invisible without a second identity. The parametrized
invariant test above is the durable guard.

## Git hygiene
- `git fetch`; verify local `measure-updates` is current with `origin/measure-updates`
  (it has collaborator commits) before adding commits. Fast-forward if stale.
- Separate commits: (1) failing isolation tests, (2) fix to green, (3) docs.
  New commits for hook/lint fixes (don't amend).

## Open items
None — all decisions resolved. Awaiting go-ahead to implement.
