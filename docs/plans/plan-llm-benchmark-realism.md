# Plan: LLM Benchmark Realism Rework

Branch: `feat/llm-benchmark-realism` (from `origin/develop`)
Status: Phases 0-3 DONE (2026-08-05). Phases 4-10 SKIPPED for the SoftwareX
revision (decision 2026-08-05 — reviewer issues only; see
plan-benchmark-reviewer-response.md). Deviations: runner `suffix` param
deferred with Phase 8; docs reconcile landed with Phase 3; test_09's
prompt.lower() also removed; full chains additionally gained a weather step +
pinned baseline EUI (sims silently failed without weather); /measures volume
added to harness + my_measure/EMS seeds (fixtures never existed before).

## Problem

Current LLM suite is a good tool-discovery benchmark but a weak user-realism benchmark:

- Prompts scaffolded in ways no user types: `" Use MCP tools only."` suffix, `"using load_osm_model"` LOAD prefix even at L1, run_id handed verbatim, `prompt.lower()` mangles L2/L3 case (`BoilerHotWater` -> `boilerhotwater`) inconsistently (needs_model cases only).
- Pass = expected tool name appeared. Args unchecked, tool `ok` unchecked, answer values unchecked.
- `--allowedTools mcp__openstudio__*` blocks Bash/Write, so the #1 real failure mode (agent scripts around MCP) is structurally impossible in ~129/135 tests.
- L3 is a near-tautology (100% by design), burns ~44 prompts/run.
- Asking for clarification counted as failure even where methodology doc says asking is correct.
- Saturated: 95-96% since Run 10, noise dominates, no discrimination left.
- Stale: `set_weather_file` expected but unregistered; dead `FLAKY_TESTS` entries (extract_errors_L1, validate_model_L1, compare_runs_L1, list_variables_L1); retrofit run_id saved but never consumed; test-count drift across README/methodology/benchmark docs; export_measure in matrix but gone from roster.
- Coverage: 97/180 tools referenced; 83 never touched; analysis (0/20), file_transfer (0/5), simulation_outputs (0/2) fully uncovered.

## Decisions (user)

1. Analysis benchmarks use a REAL OS-server at `localhost:8080`; skip cleanly if unreachable.
2. NO multi-turn tests (dropped from scope).
3. L3 trimmed to most important tools + those most likely to get wrong.
4. Stale-bit fixes folded into this rework (this plan).

## Phases

### Phase 0 — Harness fixes + stale cleanup

Files: `tests/llm/runner.py`, `tests/llm/conftest.py`, `tests/llm/test_06_progressive.py`, `docs/testing/*.md`

- Remove `prompt.lower()` in `test_06_progressive.py::test_progressive` (lines ~482-485). Keep prompt case as authored. NOTE in benchmark run notes: breaks strict comparability with Runs <=15.
- Remove `set_weather_file` from `set_weather` case expected list (unregistered tool).
- Purge dead `FLAKY_TESTS` entries: `extract_errors_L1`, `validate_model_L1`, `compare_runs_L1`, `list_variables_L1` (cases re-land in Phase 3; re-add to flaky only if they actually flake).
- Runner: add `ClaudeResult.tool_results` — pair `tool_use` id -> parsed `tool_result` content (JSON-parse text blocks, tolerate non-JSON). Add helper `tool_ok(name) -> bool | None` (None = tool not called).
- Runner: `run_claude(..., suffix=True)` param so unscaffolded tier (Phase 8) can drop `" Use MCP tools only."` without touching scaffolded tiers.
- Bump `LLM_TESTS_MAX_PROMPTS` default 180 -> 300 (Phase 3-9 net growth, see Budget).
- Docs: reconcile counts (README 132 vs benchmark 129 vs methodology 110), mark export_measure rows as removed-from-roster.
- Verify: `pytest tests/llm --co -q` collects; targeted run of 3 progressive cases confirms no behavior change beyond casing.

### Phase 1 — Assertion depth (args, ok, outcomes)

Files: `tests/llm/test_06_progressive.py`, `tests/llm/test_04_workflows.py`, `tests/llm/runner.py`

- `PROGRESSIVE_CASES` gain optional `expected_args`: `{tool: {arg: value | (value, rel_tol)}}`. Assert on first call to that tool when it is the matched expected tool. Start with ~10 cases with unambiguous args: thermostat (`cooling_offset == 2`), set_wwr (`ratio == pytest.approx(0.4)`), create_loads (0.05 people/sqft), create_plant_loop (loop_type heating), replace_terminals (terminal_type CooledBeam/FourPipeBeam), run_period (1/1-12/31), modify_component (0.92 efficiency).
- Assert `tool_ok(expected_matched_tool) is not False` — right tool called AND call succeeded. Applies to all progressive cases (cheap, uses Phase 0 runner support).
- Workflow outcome asserts: for the 4 `measure_*_full_chain` + fourpipe e2e, assert reported EUI within `rel=0.05` (decided) of pinned references (SystemD baseline ~28.21, retrofit ~28.44 kBtu/ft2, unmet 58.5 -> 34.5). One measurement run to pin baseline-model references first. Re-pin policy: on OpenStudio version bump only, noted in benchmark doc.
- Verify: targeted runs `-k "thermostat or set_wwr"` etc.

### Phase 2 — L3 trim

Files: `tests/llm/test_06_progressive.py`

- Add `L3_KEEP` set; flatten loop emits L3 only for members. Keep criteria:
  - Historical L3/near-L3 failures: `edit_measure`, `zone_equipment_priority`, `test_measure`.
  - Complex-arg tools where L3 exercises API shape: `create_measure`, `measure_replace_terminals`, `apply_existing_measure`, `replace_terminals_cooled_beam`, `replace_terminals_four_pipe_beam`, `python_ems_control`, `create_plant_loop`, `create_loads`.
  - Confusion-pair members: `run_qaqc`, `thermostat`.
  - All NEW cases from Phase 3 keep L3 for 3 runs, then trim if 3/3 stable.
- Est. keep ~13-15 of 44, drop ~29-31 prompts/run (~15 min, reallocated below).
- Verify: `pytest tests/llm --co -q | grep _L3` count matches `L3_KEEP`.

### Phase 3 — Missing-coverage progressive cases

Files: `tests/llm/test_06_progressive.py`, `tests/llm/test_01_setup.py` (fixtures), `tests/llm/test_10_confusion_pairs.py`

New cases (L1+L2; L3 per Phase 2 rule). ~15 cases:

| Case | Expected tools | L1 sketch |
|---|---|---|
| sim_errors | extract_simulation_errors, get_run_logs | "My simulation failed. Why?" |
| compare_runs | compare_runs | "Did the retrofit help? Compare the two runs." (consumes retrofit run_id from setup — finally) |
| output_variables | add_output_variable, list_output_variables | "I need hourly zone temperatures in the results." |
| timeseries | query_timeseries | "Plot the hourly cooling energy for July." |
| air_loop_details | get_air_loop_details | "What equipment is on the air handler?" |
| plant_loop_details | get_plant_loop_details | "Trace the chilled water loop." |
| zone_hvac | list_zone_hvac_equipment, get_zone_hvac_details | "What HVAC serves the corner office?" |
| economizer | set_economizer_properties | "Add an airside economizer." |
| setpoint_manager | get/set_setpoint_manager_properties | "Change the supply air temp reset." |
| roof_insulation | create_standard_opaque_material, create_construction, assign_construction_to_surface | "Add R-30 insulation to the roof." |
| infiltration | create_infiltration | "Tighten the envelope to 0.3 ACH." |
| plug_loads | create_electric_equipment | "Add plug loads at 1 W per square foot." |
| shift_schedule | shift_schedule_time | "Occupancy starts at 7 now, not 9." |
| bcl_search | search_bcl_measures, find_measure, list_comstock_measures | "Is there an existing measure that adds daylighting controls?" |
| run_lifecycle | cancel_run, cleanup_runs, pin_run | "Clean up old runs but keep the baseline." |
| ems_edit | get_python_plugin, edit_python_plugin | "My Python plugin crashed at line 12. Fix it." (seeded in test_01_setup via create_python_plugin schedule_override template — existing seed chain, no lazy in-test path) |

- Confusion pair added to test_10: `search_bcl_measures` vs `create_measure` ("I need a measure that does X" should search before authoring).
- Fixture needs: `sim_errors`/`compare_runs` reuse existing sim + retrofit run_ids; `ems_edit` seeded in existing test_01_setup step.
- Verify: targeted per-case runs; new cases start in `FLAKY_TESTS` quarantine until 3 stable runs.

### Phase 4 — L0 goal tier (outcome-graded)

Files: new `tests/llm/test_11_goal_outcomes.py`

- ~12 cases. Outcome-first prompts, operation NOT named, multiple valid tool paths. Grade = (a) any tool from accept-set called with `ok` true, (b) arg direction correct where checkable (LPD decreased, setpoint moved right way), (c) final text contains quantitative evidence — v1 check is number+unit regex (decided; admittedly weak, revisit against Run 17 NDJSON logs). NOT tool-identity.
- Case sketches: "Cut lighting energy about 20%" / "The building is too cold on winter mornings" / "Reduce summer peak demand" / "Windows are leaking energy, improve them" / "Is the HVAC oversized?" / "Make this building use less energy overall" (accept top-N retrofit paths) / "Why is heating the biggest end use?" / "Get this closer to code minimum lighting".
- Marker `goal`. All start quarantined flaky.
- Verify: 2 targeted runs per case during authoring; expect lower pass rate than L1 — that is the point, restores discrimination.

### Phase 5 — Clarification-pass tier

Files: new `tests/llm/test_12_clarification.py`

- ~6 cases where asking IS the pass: import floorplan (no path), apply measure (no name), delete zone (ambiguous which), set weather (no location), "change the schedule" (which one), "make the boiler bigger" (no size).
- Assert: NO mutating tool called (per-case denylist) AND final text asks a question (contains `?` + interrogative heuristic). Read-only inspection calls allowed.
- Reclassify `import_floorplan_L1` intent here; keep the L2/L3 rows in test_06.
- Marker `clarify`.

### Phase 6 — Error-recovery tier

Files: new `tests/llm/test_13_error_recovery.py`, fixture using `tests/assets/eplusout.err`

- ~6-8 cases:
  - Bad EPW path: "Set weather to /weather/bostn.epw" — pass = agent reports file missing or asks, <=8 tool calls (no loop), no fabricated success.
  - Zone name typo: "Raise the cooling setpoint in zone 'Ofice 1'" — pass = agent lists zones or asks, then correct zone or question; no silent no-op.
  - Failed-run diagnosis: seed a run dir under `/runs` containing `eplusout.err` (copy asset in fixture); "Run <id> failed, what happened?" — pass = get_run_logs/extract_simulation_errors called AND final text states the fatal root cause. Feasibility check first: extract_simulation_errors run_id/dir contract vs seeded dir.
  - Tool returns ok:false mid-chain (bad measure path): pass = agent surfaces the error, does not retry >2x identical args.
- Marker `recovery`. Methodology doc lists error recovery as a known gap; this closes it.

### Phase 7 — Unit traps + persona variants

Files: `tests/llm/test_06_progressive.py` (variant lists), markers `units`, `persona`

- Units (~8 prompts): IP-unit phrasing, assert SI/native-converted args via Phase 1 `expected_args`: "raise cooling 2F", "R-30 roof" (RSI ~5.28), "55F supply air" (12.8C), "1 W/ft2 plug loads" (10.76 W/m2), "0.4 WWR as 40%". PRE-STEP: audit each target tool signature for native units (e.g. adjust_thermostat_setpoints offset unit) — traps must assert the correct converted value, not assume.
- Personas (~10 cases x 2 variants = 20 prompts): modeler jargon ("Sys 7 VAV w/ HW reheat", "RTU", "econo", "LPD") + owner/layman ("the AC bill is huge", "rooms feel stuffy"). Same expected sets as the base case. Marker `persona`, EXCLUDED from default full run; run on demand only (decided).

### Phase 8 — Unscaffolded guardrail run (report-only)

Files: new `tests/llm/test_14_unscaffolded.py`, `tests/llm/runner.py` (Phase 0 param), benchmark writer in `conftest.py`

- ~15 representative case ids from test_06, run with: no `" Use MCP tools only."` suffix, `allowed_tools="mcp__openstudio__*,Bash,Read,Write,Edit,Glob,Grep"`.
- Metric: bypass rate = fraction where agent used Bash/Write/Edit to do BEM work instead of MCP (heuristic: Bash invoking python/ruby/energyplus, or Write of .py/.rb/.idf). Recorded in `benchmark.md` new section; NOT a pass/fail gate initially — measure first, gate later if stable.
- Gated by `LLM_TESTS_UNSCAFFOLDED=1` (off by default; doubles cost of those 15 prompts).
- This is the only place the real-world #1 failure mode is measurable.

### Phase 9 — Analysis-skill benchmarks (real OS-server)

Files: new `tests/llm/test_15_analysis_server.py`, `tests/llm/runner.py` (mcp config)

- Skip condition: TCP probe `localhost:8080` at module collection; unreachable -> `pytest.skip` whole file with clear reason.
- Docker networking: MCP server runs in container; OS-server URL from inside = `host.docker.internal:8080`. Runner mcp-config gains `--add-host=host.docker.internal:host-gateway` (no-op on Docker Desktop Windows, required on Linux). Prompts pass the server URL explicitly.
- ~4 cases, long timeouts (600-900s), marker `analysis`:
  1. "Check the analysis server is reachable" -> openstudio_analysis_test_server_config.
  2. "Set up a parametric study varying WWR 20-50% on this model" -> create_project/create_osa_json(_from_measures) + validate.
  3. "Run a small 2-sample study and download results" (decided: 2 samples for speed) -> submit_wait_download or start_sampled_run + wait + download_data (assert results file exists in /runs).
  4. "Which sample had the lowest EUI?" -> results_json (+ final text names a sample).
- Excluded from default full run (server dependency); run explicitly with `-m analysis`.

### Phase 10 — Freeze realistic-20 + docs + baseline run

Files: `tests/llm/conftest.py` (marker), `docs/testing/llm-test-benchmark.md`, `docs/testing/llm-testing-methodology.md`

- Tag 20 cases spanning tiers (progressive L1/L2, goal, clarify, recovery) with marker `realistic20`. FROZEN: prompts never edited after tagging; benchmark_history tracks its pass rate as the headline comparability number.
- Full-suite baseline run (Run 17) after Phases 0-7 land; record as new comparability epoch (casing + assert-depth changes break old comparability). Update benchmark + methodology docs: new tiers, new metrics (arg-correctness rate, bypass rate, recovery rate), corrected counts.

## Budget / runtime

| Change | Prompts |
|---|---|
| Current full suite | ~180 |
| L3 trim | -29 |
| Coverage cases (L1+L2+temp L3) | +38 |
| Goal tier | +12 |
| Clarification | +6 |
| Recovery | +7 |
| Units | +8 |
| Default total | ~222 (~120-140 min) |
| Persona (opt-in) | +20 |
| Unscaffolded (opt-in) | +15 |
| Analysis (opt-in, needs server) | +4 |

`LLM_TESTS_MAX_PROMPTS` -> 300 covers default + one opt-in group with retries.

## Ordering / dependencies

0 -> 1 -> 2 (harness before asserts before trim), then 3-7 in any order (3 before 2's "new cases keep L3" fully settles), 8-9 independent, 10 last. Each phase is a separate commit; LLM validation per-phase is targeted runs only, full suite once at Phase 10 (quota).

## Out of scope

- Multi-turn / session-resume tests (user decision).
- CI integration (LLM suite stays manual).
- Gating on bypass rate (measure first).

## Resolved decisions (2026-07-21)

1. EUI refs: rel=0.05.
2. Persona tier: on demand only.
3. ems_edit plugin: seeded in existing test_01_setup chain.
4. Analysis study: 2 samples.
5. Goal-tier evidence: number+unit regex as v1, revisit after Run 17.

## Unresolved questions

None.
