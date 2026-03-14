# CLAUDE.md — Instructions for Claude Code

## Project: openstudio-mcp
MCP server giving AI agents full control of building energy modeling —
create buildings, author measures, configure HVAC, run EnergyPlus sims, extract
results — all through 138 MCP tools backed by the OpenStudio SDK.

## Critical: Use MCP Tools — Do Not Reinvent
Always use openstudio-mcp tools for BEM tasks:
- Never generate raw IDF files
- OSM files are created/modified only through MCP tools (create_typical_building, create_new_building, etc)
- Never write Python/Ruby/others scripts to parse SQL results, create visualizations, build HVAC wiring, or extract data — equivalent MCP tools already exist (extract_*, query_timeseries, view_model, view_simulation_data, add_baseline_system, etc.)
- If a task genuinely cannot be done with existing tools, ASK THE USER before writing any code or scripts
- For workflow guidance, run: `list_skills()` or `get_skill("new-building")`

## Coding Rules
1. Keep files under ~250 lines — don't split artificially just to hit a number
2. Every MCP tool must have an integration test. New behavior, bug fixes, and security hardening need tests too — not just the happy path
3. Integration tests must be added to `.github/workflows/ci.yml` — append to the lightest shard's `FILES=` list (5 shards, keep balanced ~200s each)
4. Operations return `{"ok": True/False, ...}` — never raise through MCP
5. Use `openstudio` Python bindings directly
6. All OpenStudio attribute access must handle `is_initialized()` checks
7. `_extract_*` functions return dicts with `snake_case` keys matching OpenStudio attribute names
8. Tool functions keep `_tool` suffix internally; MCP-visible names strip it via `@mcp.tool(name="...")`
9. Never commit generated/temp files — `.gitignore` covers `__pycache__/`, `*.pyc`, `runs/`, `.claude/`, `.pytest_cache/`. Test artifacts go to `runs/`. Only permanent reference models go in `tests/assets/`
10. Bundled measures get wrapper tools with typed args — don't expose raw `apply_measure` as primary interface
11. No `getattr()` or string-based dispatch — every OpenStudio API method called directly (grepable, lintable, visible in stack traces)
12. MCP clients may send `list[str]` as JSON strings — use `list[str] | str` type annotation + `parse_str_list()` from `osm_helpers.py`

## Architecture
- Each skill lives in `mcp_server/skills/<name>/`
- `tools.py` exports `register(mcp)` — MCP tool definitions only
- `operations.py` — business logic, returns plain dicts, no MCP awareness
- `SKILL.md` — skill definition for LLM context
- Key modules: `model_manager.py` (load/get/save/clear model), `osm_helpers.py` (fetch_object, optional_name, list_all_as_dicts), `skills/__init__.py` (auto-discovers all skills)

## Stdout Suppression
OpenStudio SWIG bindings print memory leak warnings to stdout, breaking MCP JSON-RPC.
- `stdout_suppression.py` — context manager redirects stdout→stderr; atexit handler catches cleanup warnings
- `middleware.py` — wraps all MCP tool calls with suppression automatically
- Already integrated into `model_manager.py` and `model_management/operations.py`
- No action needed for new skills unless they create/load models outside `model_manager`

## Commands

### Docker Build & Test
```bash
docker build -f docker/Dockerfile -t openstudio-mcp:dev .
```

Run all tests (single container, fastest, matches CI):
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
- Benchmark results go in `docs/llm-test-benchmark.md`

### Local Development
- Lint: `ruff check mcp_server/`
- Unit tests (no Docker): `pytest tests/test_skill_registration.py -v`

### Notes
- Integration tests require Docker and OpenStudio
- Use `C:/` Windows-style paths for Docker volume mounts (MSYS `/c/` paths don't resolve dotfile dirs)
- Tests create temporary models in `runs/` (mounted as `/runs` in container)
- After builds, prune dangling images: `docker image prune -f`
