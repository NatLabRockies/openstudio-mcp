# Changelog

## [Unreleased]

### Fixed
- Every `model.save()` into a run dir, a model dir or a measure test snapshot (`save_osm_model`,
  `create_example_osm`, `create_baseline_osm`, `import_gbxml`, `import_floorspacejs`,
  `apply_measure`, `test_measure`, the ReportingMeasure test, EMS actuator discovery and the
  weather strip of a staged seed) goes through `model_save.save_model_confined`: the SDK writes
  the model to a private temp file and the server copies it to the destination through directory
  descriptors, so a symlink planted at the destination name or at a component above it is
  refused instead of written through, and a save the SDK refuses is a tool error. Each save now
  writes the model twice. (#190)
- The OSAF package zip (`openstudio_analysis_prepare_package`) is written through directory
  descriptors at both ends: the output zip is created from the tenant root and every member is
  enumerated and opened relative to its directory's descriptor, so a package component swapped
  for a symlink after the check is an error instead of another tenant's file under the caller's
  arcname; members are bounded (1 GiB each, 8 GiB in total), and a package zip the server reads
  (validation, the measure smoke test) is opened the same way. The analysis skill's JSON reads and
  writes (OSA JSON, results, a caller-supplied schema), the seed and weather hashes in the
  preflight manifest and the package upload read are anchored the same way, as are the measure
  script reads in measure authoring, the test log files, the actuator discovery outputs and a
  plugin's source returned by `get_python_plugin`. (#190)
- `read_file` opens a file under a tenant-writable tree by descriptor from the tenant root and
  `get_run_artifacts` lists a run dir the same way, so a directory component swapped for a
  symlink after the server's check is a tool error (`read_failed`) or an empty listing instead
  of another tenant's file or artifact names; files under the shared read-only roots are read
  as before. Every server-side `shutil.rmtree` of a directory under a tenant root (run and
  upload deletion, retention sweeps, measure re-creation, staging cleanups, the session
  workspace) removes it through the parent directory's descriptor; `delete_run` and
  `delete_upload` report a removal that fails instead of claiming success. (#190)
- Directory copies into and out of tenant-writable trees (`apply_measure` and `test_measure`
  staging a measure into a run dir, the ReportingMeasure test, `measure -u` staging, the OSAF
  package's foundational measures, `run_osw`'s staging of the OSW directory and seed, gbXML
  measure staging and `copy_file` of a directory) no longer use `shutil.copytree` /
  `shutil.rmtree` by pathname: `confined_copy.copy_tree_confined` walks both trees by directory
  descriptor from a server-owned root, copies regular files only (permission bits kept,
  modification times not), keeps a link only when its relative target stays inside the copied
  tree, refuses FIFOs and other special files, bounds the copy, and removes a stale destination
  through its parent's descriptor. A directory component swapped for a symlink after the
  server's check now fails the copy instead of copying another tenant's tree or writing into
  it; each site reports that as a tool error. `run_osw` no longer resolves the OSW's directory
  again after authorizing it, authorizes the seed path it actually stages, and reports a seed,
  weather or EPW that cannot be staged as a tool error instead of raising. (#190)
- Result extraction (`extract_summary_metrics`, `extract_end_use_breakdown`, `query_timeseries`
  and the other `eplusout.sql` readers) no longer lets SQLite open a file in the tenant's run
  dir: the file is opened by descriptor from the tenant root and copied into a private
  temporary file that SQLite reads read-only and that is unlinked at once, so a run-dir
  component swapped for a symlink at any moment cannot serve another tenant's database (one
  copy per extraction call). The result-file search walks the run dir by descriptor. A result
  file that cannot be opened or read is a tool error (`sql_unreadable` / `sql_error`) on every
  extraction path, including `extract_summary_metrics` and `compare_runs`, instead of an
  exception or a success with null metrics. (#190)
- Server-side reads, writes and copies under tenant-writable trees (run dirs, the session
  workspace, model companion folders, OSAF package dirs, measure dirs, temp staging) open
  every directory component by descriptor from a server-owned root instead of resolving
  the path at open time, so a directory replaced by a symlink after the server's check can
  no longer redirect the access into another tenant's tree. The shared file primitives in
  `util.py`, `copy_resources` and the workspace move into a saved model's `files/` are
  covered; `copy_file`, the ReportingMeasure test paths and `test_measure`'s model copies
  use the same copier (file metadata is no longer preserved on those copies). Remaining
  pathname sites are listed on the issue. (#190)
- A model's resources (its companion folder `<model>/files/`: Schedule:File CSVs, Python
  EMS plugin scripts, custom EPWs) now travel with it wherever the server moves or
  snapshots the OSM: `request_download(path=<model.osm>, bundle=True)` zips the model
  in the OpenStudio Application layout, `copy_file` writes the companion folder beside
  the copy, `test_measure` stages the resources where the test workflow searches (and
  always tests a private copy, copying `tests/test_model.osm` back and regenerating
  `measure.xml` in your own measure dir), the ReportingMeasure test gets the run's `files/`, and actuator
  discovery stages them for its sizing run. (#198)
- OSAF packaging carries the seed's resources: `openstudio_analysis_prepare_package` copies an
  external `seed_path` into `seeds/` (refusing a second seed or anything else under `seeds/`)
  and its companion resources flat into `lib/`, where every datapoint searches; a same-named
  `lib/` file with different bytes is an error. The seed preflight cache is keyed on the seed,
  its effective weather file (the model's own when none is passed, as `run_simulation` stages
  it) and a digest of its resources: `run_simulation` records the three hashes of what it
  staged in `run_record.json` at launch and the preflight reuses a run or manifest only on all
  three, so an edited Schedule:File CSV reruns the seed instead of reusing stale QA/QC
  evidence; nothing in the run dir is rehashed. `openstudio_analysis_validate_package` checks
  the zip's `lib/` resources against the manifest and requires exactly the one seed the
  manifest names. Manifests from before this change are rerun once. (#198)

### Security
- **Breaking (`MCP_AUTH=jwt`):** `MCP_JWT_ISSUER` and `MCP_JWT_AUDIENCE` are now required; the
  server refuses to start without both, naming the missing variable. Without them any token
  signed by the same IdP for another service was accepted. `MCP_JWT_ALLOW_UNSCOPED=true` is
  the explicit opt-out (logged, not recommended). A plain-`http` `MCP_JWT_VERIFY_URL` to a
  non-loopback host logs a warning at startup, since the bearer token is sent to it. (#172)
- **Breaking (HTTP mode):** the server refuses to start (exit status 3) unless the full
  sandbox tier is configured (`OSMCP_SANDBOX=auto`, `OSMCP_SANDBOX_NET=deny`, Linux); set
  `OSMCP_ALLOW_UNSANDBOXED=true` to accept the risk. `OSMCP_ENABLE_CODE_TOOLS=false` (any
  transport) leaves the code-authoring tools (`create_measure`, `edit_measure`,
  `create_python_plugin`, `edit_python_plugin`, `install_plugin_packages`) unregistered for
  deployments that must not let agents write code; the default keeps them on, and the
  server instructions and `list_skills` say when they are off instead of steering the
  agent to them.
  New `OSMCP_TOOLS_ALLOW` / `OSMCP_TOOLS_DENY` lists limit the roster on any transport;
  entries are case-insensitive, deny wins, an unknown name or an empty allow-list refuses
  startup rather than failing open, and under `OSMCP_CODE_MODE=1` the synthetic
  `search`/`get_schema`/`execute` tools follow the same policy. Tool output is declared
  untrusted data in the server instructions. (#180)
- Run directories and `run_record.json` are written by the tenant's sandboxed process and are
  now treated as untrusted: run logs, `eplusout.err`, `out.osw`, result files (`eplusout.sql`,
  `eplustbl.htm*`) and the record itself are read without following symlinks (`get_run_logs`
  returns `ok: false` on a refused log instead of empty text); the persisted `run_dir`,
  `osw_path` and `pid` are no longer trusted (a run's pid is only kept when that process runs
  in the run dir, so `cancel_run` cannot be aimed at another process); the record is written
  atomically so a planted symlink is replaced, not followed. Oversize err files are parsed
  from the head and flagged `truncated` instead of silently dropping the error summary.
- Analysis tools (`openstudio_analysis_*`): a tenant-supplied OSA schema can no longer make the
  server fetch remote `$ref`s (jsonschema's own urllib bypassed every URL gate); `schema_path`
  must lie inside the caller's roots; `analysis_id`/`project_id` are fully URL-quoted so they
  cannot traverse the server's path space with the operator token; `file_format` is limited to
  `csv`/`rdata`; downloads check the output directory before fetching and never write through
  a symlink; `measure.xml`, package zip members and the package `measures/` dir are refused
  when they are symlinks. Behaviour changes: a
  bad `server_url` now returns `{"ok": false}` instead of raising through MCP;
  `openstudio_analysis_test_server_config` no longer defaults to `http://localhost:8080` and
  works again in HTTP mode; with `OPENSTUDIO_API_TOKEN` set but no `OPENSTUDIO_SERVER_URL`,
  calls fail with an explicit message instead of silently sending no token; allowlist entries
  are compared as origins (`osa` matches `osa:80`).
- `guarded_extract` (measure downloads and file-transfer uploads) now accepts only stored or
  deflated zip members. bzip2/lzma members are decompressed without an output bound by
  Python's `zipfile`, so a 1.7 KB archive could drive the server past 4 GB of RAM before the
  uncompressed-size cap applied. Oversize archives are also refused from their declared sizes
  before anything is written. A measure re-download now replaces the measure directory
  wholesale (promoted by rename from a staging dir, so a failed or measure-less archive leaves
  the existing measure untouched and nothing partial behind).
- Principal directory keys now preserve distinct identities, including case and punctuation,
  and reserve local storage names. Authenticated tokens with missing principals or FastMCP's
  `unknown` sentinel are refused and audited as `principal_rejected`. Tenant run and
  measures roots reject paths resolving outside their direct directory, and queued
  simulations use their recorded owner's sandbox uid/gid.
- **Operator migration required:** changed principal keys move run and measure storage and
  change sandbox ownership; existing data is not migrated automatically. See
  [principal-key migration](docs/security-isolation.md#principal-key-migration) before upgrading.

### Fixed
- `run_simulation` warns (`warnings` + `user_message`) when the session model loaded from
  or saved to that path has edits that are not saved, including after a measure reloaded
  the model; it simulated the stale file on disk silently. `set_run_period` rejects days
  that do not exist in the month for the model's calendar year (February 30 was accepted
  and failed in EnergyPlus). Load, save and `run_simulation` now take a content digest of
  the model, about 0.3 s per 5,000 objects. (#177)
- The report tools (`view_model`, `view_simulation_data`, `generate_results_report`,
  `run_qaqc_checks`) and the oversized-response spill now give a hint that matches the
  transport: `copy_file` over stdio, `request_download` over HTTP. The old text named a
  host path (`runs/exports/...`) that HTTP agents cannot reach. Download URLs get their
  own `OSMCP_DOWNLOAD_URL_TTL` (default 900 s) instead of the 300 s upload TTL, which
  expired before a relayed link was clicked. (#167)
- Signed upload/download tokens no longer appear in the HTTP access log: the query
  string of `/files/` request lines is replaced by `[redacted]`. Anyone who could read
  the log could replay a download until the token expired. (#170)
- A simulation that was still queued when the server died is reported as `failed`
  ("server restarted before this run started; resubmit it") after the restart instead of
  staying `queued` forever, and is reclaimable by run retention. Queued runs are now
  written to disk at enqueue time, so a restart can find them at all. (#175)

### Added
- **`set_ground_temperatures`** (weather skill): applies an EPW header's `GROUND TEMPERATURES`
  record to the model's four `Site:GroundTemperature:*` objects. A gbXML translation sets none of
  them, so EnergyPlus silently assumes 18 °C every month on every `Ground` surface. Shallow, Deep
  and FCfactorMethod take the raw EPW values at the nearest available depths to 0.5 m and 4.0 m;
  BuildingSurface takes a value derived from the model's heating setpoints instead, because EPW
  ground temperatures are undisturbed soil and the EPW's own `.stat` warns they "should NOT BE
  USED ... to compute building floor losses". `building_surface_method` selects
  `setpoint_offset` (default), `epw_raw`, `constant` or `none`.
- **`repair_and_validate_gbxml_geometry`** now reports `ground_temperatures_missing` (report-only;
  `ok` is unaffected, matching `ground_contact_missing_count`), with a four-state
  absent/defaulted/partial/set breakdown per object.
- **`get_weather_info`** now returns a `ground_temperatures` read-back, including on models with
  no weather file attached.
- `import_gbxml` stashes the staged EPW alongside the staged gbXML, so `set_ground_temperatures`
  needs no argument after an import.
- **`set_kiva_foundation` and `get_foundation_options`** (geometry skill): EnergyPlus Kiva, a 2D
  finite-difference foundation model, as the detailed alternative to monthly ground temperatures.
  A `Foundation` surface ignores `Site:GroundTemperature:BuildingSurface` and gets a solved soil
  domain including slab-edge losses and insulation geometry. Driven by an archetype menu
  (slab on grade uninsulated / perimeter-insulated, heated or unheated basement, vented crawlspace)
  so the workflow can ask the user one question instead of ten; every applied value reports its
  provenance. **The insulation R-values are conventional starting points, not code-derived** — there
  is no vendored source for Kiva insulation geometry, so the ASHRAE 90.1 F-factor/C-factor target for
  the model's climate zone is reported alongside as a cross-check rather than used as a derivation.
  Exposed perimeter is computed from the joined building footprint.
- `set_surface_boundary_conditions` now refuses `"Foundation"`, which produced a model that failed
  fatally in EnergyPlus for want of the two companion objects; it points at `set_kiva_foundation`,
  which writes all three together.
- `find_missing_ground_temperatures()` reports `kiva_foundation_surface_count`; once every
  ground-coupled surface uses Kiva, `Site:GroundTemperature:BuildingSurface` moves from
  `ground_temperatures_missing_objects` to `ground_temperatures_superseded_by_kiva`
- New `foundation-modeling` skill and worked example
  `docs/examples/25_ground_and_foundation_heat_transfer.md` covering both methods.

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
