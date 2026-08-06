# Pilot benchmark archive (2026-08, SoftwareX reviewer response)

Frozen raw data for pilots 1-5 of the LLM benchmark
(branch `feat/llm-benchmark-realism`). Preserved here because the live
copies are volatile: `results/` is gitignored and per-test transcripts live
under `%TEMP%\llm-sweep\` (Windows may clean it).

## Contents

- `results/pilot-*/` — every leg's `benchmark.json` (per-test pass/fail,
  failure modes, token/tool stats, `run_config` with git + image identity)
  plus `sweep_meta.json` (NOTE: sweep_meta is overwritten per invocation;
  per-leg truth is each json's `run_config`).
- `transcripts/pilot-N-evidence.zip` — per-leg `ndjson_logs/` (full agent
  transcripts, every tool call and result) and, for sandboxed-harness legs,
  `agent_cwd/` sandbox droppings (files the agent left behind — e.g.
  haiku's `call_baseline.py`/`create_baseline.sh` out-of-band client
  attempt in pilot-5 `haiku_noskills_r3`).
- `escape_annotations.{json,md}` — host-side activity per test,
  reconstructed from transcripts for ALL legs (pre-sandbox legs lack
  `host_tool_counts` in benchmark.json). `escape=True` = host tools used
  with ZERO MCP calls.

## How to read the asterisks

Legs whose `run_config.git` predates commit `16b3485` ran the OLD harness:
the agent CLI's working directory was the server repo itself, with full
shell access — agents could read server source and the grading tests, and
drop artifacts on the host. All `escape=True` rows on those legs are
untrustworthy as capability measurements (see `haiku_full_r3`
`test_create_baseline_model`: haiku authored its own stdio MCP client from
our source, ran it out-of-band, and reported success citing the sanctioned
tool it never called).

Escapes are EXCLUSIVELY haiku (28 rows across pilots 4-5). sonnet /
gpt-5.4 / gpt-5.4-mini used host tools only alongside MCP calls, never as
a replacement.

## Harness conditions

| condition | legs | agent cwd | escape possible |
|---|---|---|---|
| pre-sandbox | all pilots 1-4; pilot-5 haiku full r1-r3, noskills r1-r2 | server repo | yes |
| sandboxed (>= 16b3485) | pilot-5 noskills r3, nohost, nodiscovery*, sonnet legs | empty per-test dir | contained + measured |

Key pilot-5 haiku ladder (18 hard cases): full 9/14/setup-collapse,
noskills 13/12/13, nohost 16, nodiscovery 17, nodiscovery-noskills 18.
Caveat for the inversion claim: the full arm has NO sandboxed anchor yet —
comes with the clean full re-run. Within-sandbox ladder (13 → 16 → 17 → 18)
is uncontaminated.

Do not edit files here — this is an archive. Analysis belongs in
`scripts/benchmark_aggregate.py` output or the paper repo.
