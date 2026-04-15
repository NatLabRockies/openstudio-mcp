# Changelog

## [Unreleased]

### Added
- **Optional OpenLLMetry tracing**: `pip install 'openstudio-mcp[telemetry]'` + `TRACELOOP_BASE_URL` env var enables distributed tracing via traceloop-sdk. Zero overhead when unset. Key operations (`run_simulation`, `apply_measure`, `create_measure`, `create_*_building`, `run_qaqc_checks`) emit named spans; every FastMCP tool call is auto-instrumented via `McpInstrumentor`.
- **Per-client setup guides**: `docs/clients/` — detailed MCP config examples, tool limits, and performance notes for Claude Code, Claude Desktop, VS Code Copilot, Windsurf, Gemini CLI, and Cursor.
- **Token context performance doc**: `docs/clients/token-context-performance.md` — benchmark of how each client handles the 142-tool surface and context overhead.
- **SECURITY.md**: disclosure policy and supported versions.
- **ECM package example**: `docs/examples/20_deep_retrofit_package.md` — wall insulation + thermostat + window + PV stack with expected EUI ranges.
- **`.mcp.json.example`**: ready-to-use Claude Code MCP config.
- **Docker tracing stack**: `docker/docker-compose.tracing.yml` + `docker/otel-collector-config.yaml` for local Jaeger/OTEL collector.
- **`test_telemetry.py`**: 18 unit tests for telemetry module (no Docker required).
- **`test_stdout_logger_silence.py`**: integration tests verifying Polyhedron/Space Logger warnings are fully suppressed after `silence_openstudio_stdout_logger()`.

### Fixed
- **ECM package example**: window ECM was incorrectly using `create_standard_opaque_material`; now correctly notes that glazing requires `SimpleGlazing` authored via `create_measure`.

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
