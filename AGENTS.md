# AGENTS.md — Shared instructions for all coding agents

Single source of truth for project rules (Claude Code imports this file from `CLAUDE.md`;
Codex, Copilot coding agent, Cursor and Gemini CLI read it directly). Copilot code review
reads the condensed `.github/copilot-instructions.md`; keep it in sync when rules change.

## Project: openstudio-mcp
MCP server giving AI agents full control of building energy modeling —
create buildings, author measures, configure HVAC, run EnergyPlus sims, extract
results — all through 150+ MCP tools backed by the OpenStudio SDK
(exact roster: `EXPECTED_TOOLS` in `tests/test_skill_registration.py`).

## Coding Rules
1. New files target ~250 lines; don't grow a file past ~400 without splitting by responsibility. Don't split artificially. Legacy large files are grandfathered — split opportunistically when touched
2. Every MCP tool must have an integration test. New behavior, bug fixes, and security hardening need tests too — not just the happy path
3. Integration tests must be added to `.github/workflows/ci.yml` — append to the lightest shard's `FILES=` list (5 amd64 shards, keep balanced; each runs ~12-14 min as of 2026-08)
4. Follow testing rules in `.claude/rules/testing.md`. Critical: every test needs `# Regression:` or `# Validates:` comment; never delete failing tests or weaken assertions; assert exact values not existence; integration tests mock nothing; unit tests never import `openstudio`
5. Operations return `{"ok": True/False, ...}` — never raise through MCP
6. Use `openstudio` Python bindings directly
7. All OpenStudio attribute access must handle `is_initialized()` checks
8. `_extract_*` functions return dicts with `snake_case` keys matching OpenStudio attribute names
9. Tool functions keep `_tool` suffix internally; MCP-visible names strip it via `@mcp.tool(name="...")`
10. Never commit generated/temp files — `.gitignore` covers `__pycache__/`, `*.pyc`, `runs/`, `.claude/*` (except tracked `.claude/skills/` and `.claude/rules/`), `.pytest_cache/`. Test artifacts go to `runs/`. Only permanent reference models go in `tests/assets/`
11. Bundled measures get wrapper tools with typed args — don't expose raw `apply_measure` as primary interface
12. No `getattr()` or string-based dispatch — every OpenStudio API method called directly (grepable, lintable, visible in stack traces)
13. MCP clients may send `list[str]` as JSON strings — use `list[str] | str` type annotation + `parse_str_list()` from `osm_helpers.py`
14. Multi-user isolation: new persistent user data MUST live under an identity-scoped root (`user_run_root()`/`user_measures_root()`), never a process-global path constant; never add a per-user dir to `_SHARED_READ_ROOTS`; validate path args via `is_path_allowed(..., write=…)`. The sandbox covers execution only — see `docs/security-isolation.md`
15. Tool roster has ONE source of truth: `EXPECTED_TOOLS` in `tests/test_skill_registration.py`. Add/remove a tool → edit that set (one line per tool; merges cleanly across branches). `test_tool_count`/`test_tags_coverage` derive from it — never hardcode a tool-count literal in tests. Docs/instructions say "150+ tools", not an exact count
16. List tools (`list_*`): filters are primary, `max_results` (default 10, 0=unlimited) is the safety net, brief fields by default, explicit typed filter params (no generic filter dict). Use `list_paginated()` + `build_list_response()` from `osm_helpers.py` so truncated responses carry `count`/`total_available`/`truncated`; put common-filter examples in the docstring
17. No `shell=True` in subprocess calls

More rules for specific tasks (read when relevant):
- `.claude/rules/testing.md` — test tiers, assertion quality, review checklist
- `.claude/rules/component-types.md` — adding HVAC component / setpoint manager types
- `.claude/rules/api-reference.md` — OpenStudio SDK, CLI, external resources

## Architecture
- Each skill lives in `mcp_server/skills/<name>/`
- `tools.py` exports `register(mcp)` — MCP tool definitions only
- `operations.py` — business logic, returns plain dicts, no MCP awareness
- `README.md` — internal dev notes; LLM-facing skills live in `.claude/skills/` (served via get_skill)
- Key modules: `model_manager.py` (load/get/save/clear model), `osm_helpers.py` (fetch_object, optional_name, list_all_as_dicts), `skills/__init__.py` (auto-discovers all skills)

## Stdout Suppression
Two real classes of stdout pollution corrupt MCP JSON-RPC — two-layer defense at startup in `server.py::main()` before `mcp.run()`.
- **Class A — SWIG memleak warnings** (interpreter shutdown): `"swig/python detected a memory leak of type 'boost::optional< ... > *'"`. PyPI `openstudio==3.11.0` wheel built WITHOUT `SWIG_PYTHON_SILENT_MEMLEAK`. Upstream SWIG#2638 / OpenStudio#5421; fix #5422 applied to .deb only, not the wheel (filed as NatLabRockies/OpenStudio#5608).
- **Class B — OpenStudio Logger Polyhedron/Space** (during ops): `[utilities.Polyhedron]` / `[openstudio.model.Space]` warnings on stdout from `Space::volume()`/`floorArea()` on imperfect geometry. Default `standardOutLogger` sink runs at Warn level → C stdout.
- `stdout_suppression.py::silence_openstudio_stdout_logger()` — primary fix for Class B. Calls `openstudio.Logger.instance().standardOutLogger().setLogLevel(openstudio.Fatal)`. Uses intended Logger API, no fd manipulation.
- `stdout_suppression.py::redirect_c_stdout_to_stderr()` — backstop for Class A + unknowns. Permanently dups fd 1 → stderr; Python `sys.stdout` gets a private fd to the real MCP client pipe.
- `cbe6399`-style claims that FourPipeBeam / `add_baseline_system` emit stdout do NOT reproduce — per-call wrappers are no-ops now.
- `suppress_openstudio_warnings()` retained as no-op for import compat
- No action needed for new skills

## Skill Eval Maintenance
- Every served skill requires `.claude/skills/<name>/eval.md` with positive and negative routing cases, or a non-empty `eval-exempt` reason in `SKILL.md` frontmatter
- Follow the machine-readable table grammar in `tests/llm/README.md#skill-eval-files`; malformed or prose-only rows fail deterministic tests
- Keep `eval.md` as repository test data; it must not be served to runtime agents through `get_skill`
- Run `pytest tests/test_skill_docs.py -k eval -v` after changing skill metadata or eval cases; live LLM execution remains opt-in and budgeted

## Commands

### Docker Build & Test
```bash
docker build -f docker/Dockerfile -t openstudio-mcp:dev .
```

Run all tests (single container, fastest; same suite CI runs across 5 shards):
```bash
docker run --rm \
  -v "C:/projects/openstudio-mcp:/repo" \
  -v "C:/projects/openstudio-mcp/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 \
  -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_*.py"
```

Run a specific test file: same command with `pytest -vv tests/test_load_save_model.py`.

### Local Development
- Lint: `ruff check mcp_server/`
- Unit tests (no Docker): `pytest tests/test_skill_registration.py -v`

### Notes
- Integration tests require Docker and OpenStudio
- Use `C:/` Windows-style paths for Docker volume mounts (MSYS `/c/` paths don't resolve dotfile dirs)
- Tests create temporary models in `runs/` (mounted as `/runs` in container)
- After builds, prune dangling images: `docker image prune -f`

## Review Focus
When reviewing code, check for:
1. **Error handling** — bare `except Exception: pass`, swallowed errors, missing error context
2. **is_initialized()** — OpenStudio optionals accessed without checking `.is_initialized()`
3. **Dead code** — unused imports, unreachable branches, commented-out code
4. **Type safety** — implicit string-to-number coercion, unvalidated inputs
5. **Security** — path traversal in file ops, f-string SQL, unsanitized user input
6. **Consistency** — return shape mismatches between similar tools, naming drift
7. **Resource leaks** — unclosed files, temp dirs not cleaned up

Severity: critical > high > medium > low. Always include a reason — not just "bad practice" but why it matters here.

## OpenStudio SDK Behavior (important for reviewers)

These SDK behaviors are intentional — do NOT flag them as bugs:

- **No transactional rollback.** Once an object is created in the model via SWIG
  bindings, it exists permanently. Create-then-validate is the standard pattern.
  "Should rollback on failure" is not actionable — the SDK doesn't support it.
- **`.get()` on optionals** is safe when the preceding API call guarantees a result
  for valid inputs (e.g., `Space.fromFloorPrint()` with a valid polygon). Only flag
  `.get()` when the input is user-supplied and could legitimately be invalid.
- **Plant loops without source equipment** are intentional scaffolds. Users add
  boilers/chillers afterward via `add_supply_equipment`. DOAS and radiant templates
  create the loop structure; source equipment is a separate step.
- **OpenStudio setters validate inputs** and throw `RuntimeError` on bad values.
  The outer `except RuntimeError` in operations already catches these. Missing
  pre-validation is LOW severity (nice-to-have), not HIGH.
- **`except Exception: pass` in extractors** is often intentional — OpenStudio
  objects may lack optional attributes depending on version or object type. Flag
  only when the exception would hide a real bug vs. a legitimately missing field.
- **DistrictHeating/DistrictCooling** fuel options are documented as future work.
  Silent fallback to default fuel is known, not a current bug.
