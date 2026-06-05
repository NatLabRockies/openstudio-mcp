# Changelog

## [1.0.0-beta] - 2026-06-05

First major release (beta): openstudio-mcp can now run as a shared, multi-user
remote server while the original single-container stdio workflow is unchanged.
This release also adds native arm64 (Apple Silicon) Docker support.

### Added
- **Remote multi-user server** over Streamable HTTP (`MCP_TRANSPORT=http`),
  alongside the default stdio transport. Works for Claude Code, Cursor, and VS Code.
- **Authentication**: bearer-token (`MCP_AUTH=token`, `MCP_TOKENS`) and JWT/IdP
  (`MCP_AUTH=jwt`, `MCP_JWT_*`); HTTP defaults to fail-closed token auth.
- **Per-session isolation**: each connection gets its own loaded model, with an
  LRU cap (`OSMCP_MAX_SESSIONS`) and idle-TTL eviction (`OSMCP_SESSION_TTL`).
- **Per-user run dirs, path scoping, and run ownership**: a user can't read,
  write, or query another user's runs/files.
- **Simulation queue**: global FIFO with a concurrency cap (`OSMCP_MAX_CONCURRENCY`)
  and optional per-user fairness cap; excess runs queue and start as slots free.
- **Audit logging**: one structured JSON line per tool call plus the full sim
  lifecycle and retention events, to stderr and optional `MCP_AUDIT_FILE`.
- **Run retention / disk GC** (off by default): opt-in background sweeper via
  `--gc` / `--gc-days N` / `OSMCP_RUN_RETENTION_DAYS`, containment-hardened
  (no symlink escape, no system roots, run-dirs only); plus `cleanup_runs`,
  `delete_run`, `pin_run`, `unpin_run` tools (146 tools total).
- Docs: `docs/remote-multi-user.md`, `docs/run-retention.md`; stress harness
  `scripts/stress_remote.py`; CI shards for HTTP transport, isolation, auth,
  eviction, sim queue, audit, and retention.
- **Native arm64 (Apple Silicon)** — `docker/Dockerfile.arm64` builds from NREL's
  arm64 `.deb` with `/var/oscli` bundled gems; arm64 CI build + sanity checks +
  a real-EnergyPlus shard-1 test job (#55, #56, #57).
- **stdio single-user workflow restored**: stdio resolves to one "local" user
  owning all of `/runs` (FastMCP's per-connection session id had splintered it
  into `/runs/<uuid>/` and broken direct `/runs/*.osm` saves).
- **`run_simulation`** no longer leaves orphan `sim_*` staging dirs — it stages
  in an ephemeral temp dir, so only the real run dir persists.
- **`cancel_run`** now persists the `cancelled` status, and `_refresh_status` no
  longer reclassifies a cancelled run as failed — cancelled runs stay terminal
  (and reclaimable) across restarts and status polls.
- **OpenStudio stdout Logger pollution** — silence the `[utilities.Polyhedron]` /
  `[openstudio.model.Space]` warnings that could corrupt the JSON-RPC stdio
  stream on imperfect geometry (#49).
- **Measure authoring: Python at parity with Ruby** — the measure-authoring skill
  now documents Python `run_body` patterns and gotchas (was Ruby-only, framed
  Python as "less common"); `create_measure(language="Python")` was already
  supported and tested (#60).

### Changed
- Tool count 142 → 146 (4 run-retention tools).

## [0.9.0] - 2026-04-10

### Added
- **Geometry tools**: `create_bar_building`, `create_new_building`, `import_floorspacejs` for model creation from DOE prototypes and FloorSpaceJS JSON
- **Generic object access**: `get_object_fields`, `set_object_property`, dynamic `list_model_objects` for any OpenStudio type
- **Measure authoring skill**: `create_measure`, `edit_measure`, `test_measure` with ReportingMeasure support
- **Tool routing**: `search_api` (OpenStudio SDK search), `recommend_tools`, `search_wiring_patterns` (24 HVAC wiring recipes)
- **HVAC components**: FourPipeBeam and CooledBeam air terminals, `set_zone_equipment_priority`
- **LLM test suite**: 170+ tests across 5 tiers with progressive difficulty (L1 vague / L2 moderate / L3 explicit), cross-model benchmark sweeps (sonnet/opus/haiku), CodeMode A/B comparison
- **Concurrent tool regression test**: validates MCP responses under concurrent tool calls
- **Stdout purity test**: validates no C-level pollution on complex 44-zone models
- **Response-size guardrails**: `max_results` + filters on all list tools, brief mode for large responses
- **Agent guardrails**: anti-loop instructions in MCP server, tool-bypass prevention
- Tags on all 142 tools for ToolSearch discovery
- Enriched tool descriptions for better LLM tool selection
- `list_weather_files` tool, `validate_model` tool, `extract_simulation_errors` tool
- `compare_runs` tool for two-simulation comparison
- CI expanded to 5 shards, ~450+ integration tests

### Fixed
- **Concurrent tool timeout (issue #42)**: permanent fd redirect replaces racy global middleware — C stdout goes to stderr once at startup, Python sys.stdout gets private fd to MCP client
- **Polyhedron stdout leak**: OpenStudio geometry engine C++ diagnostics no longer corrupt JSON-RPC stream
- SWIG memory leak warnings fully suppressed across all callsites
- Measure XML stale checksums causing OS App rejection
- Choice-type measure argument validation in wrappers
- JSON-string list params across 9 affected tools (`parse_str_list()`)
- `conditioned_floor_area` computed from model instead of hardcoded
- EUI units now report MJ/m2 + kBtu/ft2 alongside GJ/m2

### Changed
- `list_files` hardened to `/inputs` + `/runs` only
- `change_building_location` preferred over `set_weather_file` (sets EPW+DDY+CZ in one call)
- Consolidated 4 HVAC validation test files into single `test_hvac_validation.py`
- Consolidated integration tests: -8 files, -57 Docker sessions

## [0.8.2] - 2026-03-28

### Added
- Tool description enrichment for all 142 tools
- CodeMode toggle (default off) with LLM harness support

## [0.8.0] - 2026-03-13

### Added
- Measure authoring skill with test framework
- SWIG stdout suppression middleware (replaced in 0.9.0)
- Phase 10 results tools: `extract_simulation_errors`, `list_output_variables`, `compare_runs`

## [0.7.0] - 2026-03-07

### Added
- LLM agent test suite (170+ tests, local-only)
- Geometry workflows (FloorSpaceJS import, bar building)

## [0.6.0] - 2026-02-28

### Added
- Response-size guardrails on all list tools
- Generic object access (Phase C)

## [0.5.0] - 2026-02-21

### Added
- Agent guardrails (anti-loop, tool-bypass prevention)
- Weather file improvements

## [0.4.0] - 2026-02-14

### Added
- Common measures integration (20 measures, 11 wrapper tools)
- Context reduction (auto-load, brief mode, batch removal)

## [0.3.0] - 2026-02-07

### Added
- Initial skills architecture (22 skills, 126 tools)
- 5-shard CI pipeline
- OpenStudio SDK 3.11.0 integration
