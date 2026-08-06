# Plan: outcome grading for LLM benchmark hard cases

Motivation (2026-08-06, user): current progressive grading = routing +
server acceptance. For authoring cases (measure, python EMS) `ok:true`
means only "syntax-valid artifact created" — never executed, never
behavior-checked. Multi-step cases pass on partial work (roof_insulation
passes on creating a material; zone_equipment_priority without
reordering). Suspected inflation of small-model pass rates. Production
matrix restarts from zero in a NEW session once this lands (2 pilot legs
discarded).

## Principle: two gates, facts + rubric split

- Gate 1 (existing, unchanged): routing — accepted tool called, first
  call ok, pinned args.
- Gate 2 (new): outcome — deterministic grader inspects/executes the
  artifact the agent left. Pass = both gates.
- **Facts vs rubric**: the grader records exhaustive measured FACTS per
  test into the benchmark row (`"outcome"` key). Pass/fail is a pure
  function over facts (`rubric.py`, `RUBRIC_VERSION`). Changing the
  rubric later = re-score recorded facts, NO re-run. This is the answer
  to "how subjective can we be": thresholds are post-hoc revisable;
  only fact COVERAGE is locked at run time, so facts err on the side of
  recording everything measurable.
- Failure mode: existing `outcome_mismatch` (already in taxonomy,
  conftest.py:268; unused by progressive tests until now). Routing-pass
  remains reconstructable: `passed or failure_mode == "outcome_mismatch"`.
- Verdict stays first-call-strict; rows that failed gate 1/2 are not
  outcome-graded (no artifact contract). `recovered` rows ARE graded
  (facts recorded; verdict stays tool_error — honesty rule).
- Grading runs AFTER the agent turn — the 120s budget is untouched.
- No LLM judge anywhere.

## Graded cases (18-case production set only)

| case (levels) | grader mode | facts recorded | rubric v1 pass |
|---|---|---|---|
| create_baseline_model (setup) | inspect | zones, spaces, floor area, thermostat scheds | file exists, zones==10 |
| create_baseline_with_hvac (setup) | inspect | + air loops, terminals, plants | zones==10, 1 loop serving 10, VAVReheat==10, HW+CHW plants |
| import_floorplan (L1,L2) | inspect | spaces, zones, floor area | L2: counts/area match fixture ground truth (validation records it). L1: routing-only (no file named in prompt — no outcome contract) |
| add_hvac (L1,L2) | inspect | air loops, terminals by class, zones served, plants | L1: >=1 loop, all 10 zones served by any HVAC. L2: Sys7 signature — VAVReheat terminals all zones, HW+CHW |
| python_ems_control (L1-L3) | ems_sim | sim_ran, night/day setpoint stats per zone (Zone Thermostat Heating Setpoint Temperature, injected), Schedule Value series stats, plugin objects in OSM | L2/L3: night mean 15.6±0.1 AND day mean 21.1±0.1; L1: night <= day-1.0 K. sim must run |
| measure_replace_terminals (L1-L3) | apply_measure | runner result + messages, measure args from xml, terminal counts by class, zones-on-loop count (from run/in.osm) | Success AND FourPipeBeam==10 AND VAVReheat==0 AND zones_connected==10 |
| zone_equipment_priority (L1-L3) | inspect | per-zone equipment list w/ heating+cooling priorities | baseboard in zone 1; L2/L3: baseboard heating priority == 1; L1: priority explicitly changed (not append-default last) |
| roof_insulation (L1-L3) | inspect (+ fixture baseline compare) | roof surfaces' constructions, layer R-values, assembly R before/after | L1: added-layer R ~= 5.28 m2K/W (R-30, rel 0.15); L2/L3: roof assembly R > baseline |

Other progressive cases (full suite) stay routing-only — out of scope.

## Mechanics

- **Artifact contract (prompt change)**: no autosave exists; agents
  mutate in-memory. Graded model-mutation cases get an appended
  instruction: "Then save the model to /runs/graded_<case>_<level>.osm
  using save_osm_model." Save-as also protects shared fixtures from
  state leaks (pilot-3). Flat path under /runs (no subdir dependence).
  measure_replace_terminals needs NO save (artifact = measure dir on
  /measures). create_baseline*/import_floorplan tools write to disk
  themselves (baseline) or agent saves (floorplan L2 — save instruction
  added). Benchmark parameter: adds one step inside the 120s budget —
  footnote; applies uniformly to all models/arms, restart-from-zero
  makes it clean.
- **Not saved => outcome_mismatch** with fact `saved:false` (its own
  reason string, separable post-hoc).
- **Grader vehicle**: `docker run --rm` on the SAME pinned image, mounts:
  leg runs dir -> /runs (rw: staging under /runs/grading_*), measures
  dir -> /measures:ro, repo tests/llm/grading -> /grading:ro. Runs
  `/opt/venv/bin/python /grading/container_grader.py --mode ... --out json`.
  SDK direct (`import openstudio`), no MCP server, no mcp_server imports.
- **ems_sim recipe**: copy saved OSM + sibling files/ to staging; inject
  via SDK: Boston EPW (comstock path, .ddy sibling if present), RunPeriod
  Jan 1-14, Output:Variable "Zone Thermostat Heating Setpoint
  Temperature" (*, Timestep); `openstudio run -w`; read eplusout.sql
  run-period environment only (design-day row gotcha, issue #87); night
  = hours [0,6)+[18,24), day = [6,18).
- **apply_measure recipe**: stage authored measure (name taken from the
  agent's create_measure call input) + fixture HVAC osm; OSW with one
  measure step (default args); `openstudio run --measures_only -w`;
  parse out.osw step result; inspect run/in.osm.
- **Grader infra failure** (docker error/timeout): facts
  `{grader_error: ...}`, verdict = outcome_mismatch with reason
  `ungradable` — separable from agent failures in analysis.
- **Row wiring**: test appends `("outcome", facts_dict)` to
  user_properties; conftest whitelist loop (conftest.py:452-456) gets an
  `outcome` branch merging it into the row. Row gains
  `outcome: {facts..., rubric_version, outcome_pass, reasons}`.
- Timing adds ~8-15 min/leg (ems_sim ~1-3 min x3 rows, apply_measure
  ~1 min x3, inspect ~15s x12).

## Files

- `tests/llm/grading/container_grader.py` — in-image script, modes
  inspect | apply_measure | ems_sim; emits one-line JSON on stdout.
- `tests/llm/grading/host.py` — pytest-side: docker invocation, case
  dispatch (case_id+level -> mode+args), rubric application, returns
  outcome dict.
- `tests/llm/grading/rubric.py` — RUBRIC_VERSION, pure functions
  facts->verdict(+reasons). No openstudio import.
- `tests/llm/test_06_progressive.py` — GRADED_CASES set, save-suffix
  injection, grade call after `_assert_expected_args`.
- `tests/llm/test_01_setup.py` — outcome facts for the two baseline
  creation tests.
- `tests/llm/conftest.py` — outcome user_property branch.
- `scripts/benchmark_aggregate.py` — outcome_pass columns beside
  routing pass (both metrics per model x arm; delta table).

## Validation (this session, before handoff)

1. Rubric unit tests — pure dict fixtures, red-green (known-bad facts
   must fail: partial roof, priority-not-1, night==day, VAV remaining).
2. Container-grader integration tests (in-image, CI-shardable): build
   System 7 model via SDK in-test, apply the asset measure
   `replace_terminals_with_four_pipe_beams` -> grader facts assert
   FourPipeBeam==10, VAVReheat==0; do-nothing measure -> counts
   unchanged -> rubric fails. ems_sim: seed schedule_override plugin on
   a baseline+weather model -> night/day stats correct; no-plugin model
   -> flat setpoint -> rubric fails.
3. Live mini-legs: haiku + sonnet, `-k` a 4-case subset (one per grader
   mode), 1 repeat — confirm facts+verdicts land in benchmark.json and
   outcome_mismatch renders in the report.
4. Record import_floorplan fixture ground truth during (2).

## Handoff

Update `benchmark-production-brief-2026-08.md`: new harness sha, rebuilt
pinned image (grading mounts nothing new into the AGENT's path — but
rebuild anyway for one-image-per-run rule), grading design pointer,
both-metrics deliverables, restart-from-zero, new sweep-id
(prod-2026-08b), discard prod-2026-08 results (2 haiku legs,
archived-not-cited), decisions of 2026-08-06 (18 cases, t240 cell,
no dose probe, gemini limitation).

## Unresolved questions

1. ems_sim Jan 1-14 run period enough, or full month? (validation
   timing will decide)
2. L1 import_floorplan routing-only OK, or drop L1 from graded set?
3. apply_measure with default args only — grade required-args-without-
   defaults as fail (v1) — acceptable?
4. Aggregator delta table format — decide at implementation.
