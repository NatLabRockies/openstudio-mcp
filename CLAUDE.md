# CLAUDE.md — Instructions for Claude Code
always be brutally honest
## Project: openstudio-mcp
MCP server giving AI agents full control of building energy modeling —
create buildings, author measures, configure HVAC, run EnergyPlus sims, extract
results — all through 150+ MCP tools backed by the OpenStudio SDK.

## Critical: Use MCP Tools — Do Not Reinvent
Always use openstudio-mcp tools for BEM tasks:
- Never generate raw IDF files
- OSM files are created/modified only through MCP tools (create_typical_building, create_new_building, etc)
- Never write Python/Ruby/others scripts to parse SQL results, create visualizations, build HVAC wiring, or extract data — equivalent MCP tools already exist (extract_*, query_timeseries, view_model, view_simulation_data, add_baseline_system, etc.). Sanctioned exception: custom ReportingMeasures via create_measure, when no extract_* tool covers the metric (see measure-authoring skill)
- If a task genuinely cannot be done with existing tools, ASK THE USER before writing any code or scripts
- For workflow guidance, run: `list_skills()` or `get_skill("new-building")`

## Coding Rules
1. New files target ~250 lines; don't grow a file past ~400 without splitting by responsibility. Don't split artificially. Legacy large files are grandfathered — split opportunistically when touched
2. Every MCP tool must have an integration test. New behavior, bug fixes, and security hardening need tests too — not just the happy path
3. Integration tests must be added to `.github/workflows/ci.yml` — append to the lightest shard's `FILES=` list (5 shards, keep balanced ~200s each)
4. Follow testing rules in `.claude/rules/testing.md`. Critical: every test needs `# Regression:` or `# Validates:` comment; never delete failing tests or weaken assertions; assert exact values not existence; integration tests mock nothing; unit tests never import `openstudio`
5. Operations return `{"ok": True/False, ...}` — never raise through MCP
6. Use `openstudio` Python bindings directly
7. All OpenStudio attribute access must handle `is_initialized()` checks
8. `_extract_*` functions return dicts with `snake_case` keys matching OpenStudio attribute names
9. Tool functions keep `_tool` suffix internally; MCP-visible names strip it via `@mcp.tool(name="...")`
10. Never commit generated/temp files — `.gitignore` covers `__pycache__/`, `*.pyc`, `runs/`, `.claude/`, `.pytest_cache/`. Test artifacts go to `runs/`. Only permanent reference models go in `tests/assets/`
11. Bundled measures get wrapper tools with typed args — don't expose raw `apply_measure` as primary interface
12. No `getattr()` or string-based dispatch — every OpenStudio API method called directly (grepable, lintable, visible in stack traces)
13. MCP clients may send `list[str]` as JSON strings — use `list[str] | str` type annotation + `parse_str_list()` from `osm_helpers.py`
14. Multi-user isolation: new persistent user data MUST live under an identity-scoped root (`user_run_root()`/`user_measures_root()`), never a process-global path constant; never add a per-user dir to `_SHARED_READ_ROOTS`; validate path args via `is_path_allowed(..., write=…)`. The sandbox covers execution only — see `docs/security-isolation.md`
14. Tool roster has ONE source of truth: `EXPECTED_TOOLS` in `tests/test_skill_registration.py`. Add/remove a tool → edit that set (one line per tool; merges cleanly across branches). `test_tool_count`/`test_tags_coverage` derive from it — never hardcode a tool-count literal in tests. Docs/instructions say "150+ tools", not an exact count

## Architecture
- Each skill lives in `mcp_server/skills/<name>/`
- `tools.py` exports `register(mcp)` — MCP tool definitions only
- `operations.py` — business logic, returns plain dicts, no MCP awareness
- `SKILL.md` — skill definition for LLM context
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

Run specific test file:
```bash
docker run --rm \
  -v "C:/projects/openstudio-mcp:/repo" \
  -v "C:/projects/openstudio-mcp/runs:/runs" \
  -e RUN_OPENSTUDIO_INTEGRATION=1 \
  -e MCP_SERVER_CMD=openstudio-mcp \
  openstudio-mcp:dev bash -lc "cd /repo && pytest -vv tests/test_load_save_model.py"
```

### LLM Tests
- Targeted: `LLM_TESTS_ENABLED=1 pytest tests/llm/test_06_progressive.py -k "thermostat_L1" -v`
- Full suite only for final validation
- Markers: `-m smoke` (12), `-m generic` (10), `-m progressive` (102)
- Benchmark results go in `docs/testing/llm-test-benchmark.md`

### Local Development
- Lint: `ruff check mcp_server/`
- Unit tests (no Docker): `pytest tests/test_skill_registration.py -v`

### Notes
- Integration tests require Docker and OpenStudio
- Use `C:/` Windows-style paths for Docker volume mounts (MSYS `/c/` paths don't resolve dotfile dirs)
- Tests create temporary models in `runs/` (mounted as `/runs` in container)
- After builds, prune dangling images: `docker image prune -f`
