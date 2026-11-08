# LLM benchmarking: HTTP vs stdio transport (v1.3.0)

Does an agent do as well against the shared HTTP server as against the local
stdio server? Same suite, same image, same models, same prompts apart from the
user-area path; only the transport changes.

**Answer: yes.** Across three models and 344 tests, no pass-rate difference
between the transports survived reruns except one test that is stricter than
its question. The differences that do exist are in how agents get there: more
schema lookups over HTTP for Sonnet and Haiku, more cost and time for Opus, and
one server tool (`get_building_info`) that fails far more often over HTTP.

## Setup

| | |
|---|---|
| Server image | `nrel/openstudio-mcp:v1.3.0` (digest `sha256:26b18fde6392…`) |
| Harness | branch `feat/llm-http-transport-bench` off v1.3.0 (`9f8b6bd`); full legs at `24fa0e0`, fix and rerun legs at `d2c496a` (verifier fix only, see below) |
| Models | `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5` via Claude Code CLI 2.1.319 |
| Suite | `tests/llm`, 344 tests (`test_11_codegen_arm.py` excluded: it uses no MCP server) |
| Budget | 600 s per test (`LLM_TESTS_TIMEOUT_FLOOR=600`, `LLM_TESTS_TIMEOUT_BASE=600`) |
| Retries | 0; one run per test, then 3 reruns per transport for tests that disagree |
| Date | 2026-11-07 to 2026-11-08 |

**stdio** is the existing harness: one `docker run` per prompt, owning all of `/runs`.

**HTTP** is one server per leg, started by `scripts/benchmark_sweep.py --transport http`
with the same mounts and env as the stdio container plus `MCP_TRANSPORT=http`,
`MCP_AUTH=token` and a random per-leg token for user `bench`. Each prompt is a new
Claude Code session, so a new MCP session, against the same server process.

### What differs between the arms besides transport

1. **Paths in prompts.** A token user can reach only `/runs/bench` and
   `/measures/bench`, so `tests/llm/transport.py` rewrites `/runs/` and
   `/measures/local/` in prompts. Everything else in the prompt is identical.
2. **Server instructions and path hints.** In HTTP mode the server tells agents
   it is remote and that a file the user names is usually on their own machine.
   This is part of what is measured, not a confound.
3. **Process lifetime.** stdio starts a server per prompt; HTTP keeps one server
   for the leg (sessions, caches and any leaked state persist across prompts).
4. **`/test-assets` prompts.** A few tests name `/test-assets/...`, which the
   HTTP instructions do not list as a server path, so HTTP agents first look on
   the host with `Bash`. A real deployment has no `/test-assets`; this is a
   harness artifact that affects a handful of tests.

## Harness defects found during the run

- **Verifier used stdio on HTTP legs (fixed in `d2c496a`).** `tests/llm/verify.py`
  checked simulation runs through a fresh stdio server over the same folder,
  which answers `Unknown run_id` for runs an HTTP user produced. Every HTTP test
  that verifies a run failed "EnergyPlus did not terminate successfully" whatever
  the simulation did: the four `measure_*_full_chain` workflows,
  `test_fourpipe_beam_retrofit_e2e` and `test_hvac_only_swap_e2e`. Proven on a
  real HTTP run before and after the fix (after: completed, 0 fatal, 0 severe,
  EUI 57.41 = pin). Repair: those 6 tests were rerun once over HTTP per model
  (`transport-v130-fix-http`) and their rows replaced **outcome-blind**, as in
  the paper's 600 s merge (rows that came back failing replace too). Setup rows
  of the fix legs are not substituted.
- **Usage caps.** The account hit its usage cap four times (about 2 h or 3.5 h
  each). The harness sleeps and
  retries a capped prompt (`LLM_TESTS_CAP_WAIT_S`) instead of failing it, so no
  leg was invalidated. Rows that waited carry the wait in `duration_s`; all
  timings below use the CLI's `duration_ms`.

## Results

First run per test, after the verifier repair above. Times are median CLI time
per test; cost is the CLI's reported list-price cost for the leg. Timed-out
rows record no CLI time or cost, so HTTP medians and cost are very slightly
understated.

| Model | Transport | Passed | Rate | Median s | Median tool calls | Cost | Timeouts |
|---|---|---|---|---|---|---|---|
| Opus 5.5 | stdio | 317/344 | 92.2% | 19.4 | 4 | $147 | 0 |
| Opus 5.5 | HTTP | 323/344 | 93.9% | 22.3 | 5 | $170 | 2 |
| Sonnet 5.5 | stdio | 304/344 | 88.4% | 11.3 | 4 | $38 | 0 |
| Sonnet 5.5 | HTTP | 314/344 | 91.3% | 11.0 | 3 | $39 | 0 |
| Haiku 5.5 | stdio | 296/344 | 86.0% | 11.9 | 5 | $14 | 0 |
| Haiku 5.5 | HTTP | 290/344 | 84.3% | 11.5 | 4 | $10 | 1 |

The first-run gaps (+1.7, +2.9, -1.7 points) point in different directions per
model and are within run-to-run noise:

| Model | Agree | Pass only on stdio | Pass only on HTTP | Sign test p |
|---|---|---|---|---|
| Opus 5.5 | 324 | 7 | 13 | 0.26 |
| Sonnet 5.5 | 318 | 8 | 18 | 0.08 |
| Haiku 5.5 | 316 | 17 | 11 | 0.35 |

Every disagreeing test was then run 3 more times on each transport, each repeat
a fresh leg with fresh fixtures. Pooled over those reruns the transports are
level:

| Model | Disagreeing tests | stdio reruns passed | HTTP reruns passed |
|---|---|---|---|
| Opus 5.5 | 20 | 29/60 | 28/60 |
| Sonnet 5.5 | 26 | 47/78 | 49/78 |
| Haiku 5.5 | 28 | 61/84 | 61/84 |

The three timeouts (600 s) are open-ended `test_eval_tool_selection` prompts
(Opus HTTP `energy-report: Detailed analysis of results` and
`measure-authoring: Build a custom reporting measure`, Haiku HTTP
`retrofit: Do a retrofit analysis`). The agent picked the expected tool early
and kept working; these tests grade tool choice, so all three passed, as they
did on stdio without hitting the limit.

## Differences that held up under reruns

Verdicts per disagreeing test: **confirmed** = passed every rerun on one
transport and none on the other; **noise** = passed at least one rerun on both
transports; **unclear** = never passed on at least one side without a clean
split (mostly 0/3 on both, a few 1/3 vs 0/3, one 2/3 vs 0/3). Unclear tests are ones the model
usually fails anywhere; the single first-run pass was the outlier, not a
transport effect.

| Model | Confirmed | Noise | Unclear |
|---|---|---|---|
| Opus 5.5 | 0 | 9 | 11 |
| Sonnet 5.5 | 1 | 21 | 4 |
| Haiku 5.5 | 0 | 25 | 3 |

The one confirmed difference is Sonnet's `test_progressive[thermal_zones_L1]`:
0/4 on stdio (first run plus reruns), 4/4 on HTTP. Over stdio Sonnet answers
"how many zones?" from the zone count `load_osm_model` already returned, which
is correct; the test requires a `list_thermal_zones` call (issue 5 below). It
is a suite strictness issue, not a server defect on either transport. Opus
passed it once on stdio and failed all 6 reruns, for the same reason.

Opus's 11 unclear tests are mostly `test_03_eval_cases` routing cases where the
agent consistently picks a different tool from the one the eval expects; the
single first-run pass was the outlier.

## Behaviour differences (all tests, from tool transcripts)

Counted over every tool call in the first-run legs. "Bad arguments" is a
pydantic validation error from calling a deferred MCP tool before loading its
schema with `ToolSearch`.

| | Opus stdio | Opus HTTP | Sonnet stdio | Sonnet HTTP | Haiku stdio | Haiku HTTP |
|---|---|---|---|---|---|---|
| Tool calls (all) | 3508 | 3828 | 2010 | 1976 | 2642 | 2610 |
| MCP tool calls | 2865 | 3144 | 1907 | 1762 | 2402 | 2267 |
| `ToolSearch` calls | 632 | 659 | 100 | 199 | 228 | 321 |
| Host tool calls (Bash, Read, ...) | 11 | 25 | 3 | 15 | 12 | 22 |
| Tool errors | 129 | 184 | 330 | 287 | 538 | 450 |
| - bad arguments | 5 | 6 | 180 | 134 | 321 | 227 |
| - "exception set" (issue 1) | 4 | 45 | 7 | 13 | 9 | 25 |
| - path not allowed | 4 | 10 | 10 | 9 | 4 | 5 |
| - no model loaded | 24 | 25 | 25 | 28 | 63 | 57 |
| - other | 92 | 98 | 108 | 103 | 141 | 136 |

- **Sonnet and Haiku look up schemas more over HTTP** (ToolSearch +99 and +93)
  and make about 25 to 30% fewer bad-argument calls. Opus already looks up
  almost every schema on both. Why the HTTP arm triggers more lookups is not
  established; the server instructions differ between the arms (see above).
- **Opus does more work over HTTP:** +10% MCP calls, +15% median time, +16%
  cost, for the same pass rate.
- **Host tools rise over HTTP** on all models, from small bases (Opus 11 to
  25, Sonnet 3 to 15, Haiku 12 to 22):
  agents look for named files on the user's machine first, as the HTTP
  instructions tell them to (including the `/test-assets` prompts, issue 4).
- **Path-denied errors on HTTP** are mostly `openstudio_analysis_create_osa_json`
  writing outside `/runs/bench` (issue 2): Opus 6 calls, none on stdio.

## Server and suite issues found

Ranked by how much they matter to a user of the HTTP server.

1. **`get_building_info` fails on most HTTP calls.** The SWIG call
   `Building.floorAreaPerPerson()` leaves a Python error pending ("returned a
   result with an exception set"). Over stdio the tool's own `try` catches it
   and returns `ok: false`; over HTTP it surfaces later, inside FastMCP's
   argument validation (`pydantic_core ... validate_python`), so the agent gets
   a raw `ToolError`. Failure rate per call, full legs:

   | Model | stdio | HTTP |
   |---|---|---|
   | Opus 5.5 | 4/47 (9%) | 39/52 (75%) |
   | Sonnet 5.5 | 7/12 (58%) | 13/16 (81%) |
   | Haiku 5.5 | 9/39 (23%) | 25/31 (81%) |

   `get_object_fields` shows the same error, rarely: Opus 2/97 stdio, 7/165 HTTP.
   Five of the seven HTTP cases came after a failed `get_building_info` in the
   same session, which suggests (not proven) that the pending error leaks into
   the next tool call in the long-lived process.

   Same root cause on both transports, much higher rate over HTTP. Why HTTP is
   worse is not established (one long-lived process and worker threads are the
   obvious suspects). Agents usually recover with other tools, which is why
   pass rates barely move. Worth its own issue with a reproduction.
2. **HTTP path hints do not name the user's writable area.** Agents asked to
   write a file (e.g. `openstudio_analysis_create_osa_json`) guessed a relative
   path (resolves to `/repo`) or `/runs/...`; both are denied for a token user,
   whose area is `/runs/<user>`. `path_denied_hint` names `RUN_ROOT`, not the
   caller's area. HTTP only.
3. **Agents can overwrite shared suite fixtures.** `save_osm_model` with no
   path saves over the loaded model, so one test that loads the shared
   `llm-test-baseline-hvac` model and saves can change it for every later test
   in the leg. Sonnet's stdio leg lost its reheat coils this way (1 heating coil
   vs Haiku's 11); its four `measure_*_full_chain` tests then failed the
   baseline EUI pin (40.84 vs 57.41) and passed 3/3 on rerun with fresh
   fixtures. Suite weakness on either transport.
4. **Suite prompts name `/test-assets`.** On HTTP this sends agents to the
   host first (see above); the same mount is also `/inputs`, which the HTTP
   instructions do recognise. Rewriting those prompts to `/inputs` would remove
   the artifact.
5. **`thermal_zones_L1` is stricter than its question.** "How many zones does
   the building have?" requires a `list_thermal_zones` call, but
   `load_osm_model` already returns the zone count; agents that answer from it
   are right and fail the test.

## Reproducing

```bash
# from the harness worktree; results land in <results-root>/<sweep-id>
export LLM_TESTS_TIMEOUT_BASE=600 LLM_TESTS_TIMEOUT_FLOOR=600
export LLM_TESTS_MAX_PROMPTS=2000 LLM_TESTS_CAP_WAIT_S=86400
for t in stdio http; do
  python scripts/benchmark_sweep.py --sweep-id transport-v130-$t \
    --image nrel/openstudio-mcp:v1.3.0 --transport $t --arms full --repeats 1 \
    --pytest-args "tests/llm --ignore=tests/llm/test_11_codegen_arm.py" \
    --model claude-sonnet-5-5:claude --model claude-haiku-5-5:claude \
    --model claude-opus-5-5:claude
done
python scripts/benchmark_check_leg.py results/transport-v130-stdio results/transport-v130-http
python scripts/benchmark_compare_transport.py results/transport-v130-stdio \
  results/transport-v130-http --discordant discordant.json
```

Raw leg JSONs, server logs and transcripts stay outside git (`results/`,
`%TEMP%/llm-sweep`).
