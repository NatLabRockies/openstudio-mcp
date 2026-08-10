# Benchmark session handoff (2026-08-05)

Branch: `feat/llm-benchmark-realism` (pushed; ~20 commits). Plans:
`docs/plans/plan-llm-benchmark-realism.md` (phases 0-3 DONE, 4-10 skipped),
`docs/plans/plan-benchmark-reviewer-response.md` (D1-D7+D9 DONE, D8 pending).

## Next session: do SPIKE-2, then finish the plan

1. **SPIKE-2 (EP-MCP runnable?)** — half-day timebox.
   - Clone EnergyPlus-MCP public repo, pin the commit in the study README.
   - Success criteria: (a) their server starts locally, (b) reachable over
     MCP stdio from our runner backends (claude via `--mcp-config`, codex via
     `-c mcp_servers.*` overrides), (c) the ~10 intersection tasks are
     expressible (load IDF/OSM, inspect zones, modify setpoint/schedule, run
     sim, extract end uses).
   - If yes: build `scripts/epmcp_compare/` (NOT under tests/) — both servers
     driven by the same backend, metrics = completion, tool calls, tokens,
     wall clock; grading = completion + D6-style output checks. If no:
     decline-in-letter + keep feature-level Table 5 (plan D8 has the text).
2. **Merge → tag → matrix**
   - PR `feat/llm-benchmark-realism` → develop (PRs target develop, not main).
   - Tag v1.2.0, `docker build -t openstudio-mcp:v1.2.0 .`, Zenodo-archive the
     tag.
   - Run matrix (all N=3, retries=0, `--image openstudio-mcp:v1.2.0`):
     sonnet full (full suite); haiku + opus + gpt-5.4:codex full
     (progressive); sonnet + gpt-5.4:codex noskills (progressive L1/L2 + NL
     test_03 + workflows test_04/07/08); Arm C codegen
     (`LLM_TESTS_ARM=codegen pytest tests/llm/test_11_codegen_arm.py`, x3).
   - `python scripts/benchmark_aggregate.py results/<sweep>` → table4.md,
     ablation.md, discovery.csv, stability.md, failure_modes.md.
   - `scripts/export_tool_table.py` inside the tagged container → paper
     Table 1 (+ counts JSON).
3. Paper tables + response letter (companion: `paper/revision-plan-2026-07.md`).

## Sweep mechanics

```
python scripts/benchmark_sweep.py --sweep-id <id> --model sonnet:claude \
    --arms full --repeats 3 --image openstudio-mcp:v1.2.0 \
    --pytest-args "tests/llm ..."
```
- Resume-safe: existing `<model>_<arm>_rN.json` files are skipped; run
  repeats via successive invocations if wall-clock caps bite.
- Preflight aborts on dirty tree, nonzero LLM_TESTS_RETRIES, or an image
  older than the last commit touching mcp_server/docker/pyproject
  (`OSMCP_SWEEP_ALLOW_STALE_IMAGE=1` overrides).
- Results land in `results/<sweep-id>/` (gitignored; archive with the paper).

## Hard-won gotchas

- **Rebuild the image after ANY server change before harness runs** — the
  harness mounts only /runs+assets; containers run BAKED code (pilot-1's
  ablation silently no-op'd on a stale image).
- Codex CLI: `%LOCALAPPDATA%/Programs/OpenAI/Codex/bin/codex.exe` (not on
  PATH); model pinned **gpt-5.4** (5.4-mini/5.5/5.6 also allowed; ChatGPT
  auth REJECTS gpt-5.2-codex). `--dangerously-bypass-approvals-and-sandbox`
  is REQUIRED (exec auto-cancels MCP calls otherwise).
- `claude -p` max-turns exhaustion exits rc=1 with EMPTY stderr; runner
  includes stdout tail. 1-2 truly transient rc=1s seen — consider an
  infra-only retry for matrix runs (open decision).
- Paths in prompts must be under `/inputs` (in `_SHARED_READ_ROOTS`), never
  `/test-assets` (mounted but not allowed).
- Background-command cap is 10 min: hard-case legs fit one leg per
  invocation; chain via repeats-resume.
- Bash tool only, no PowerShell (PS 5.1 mangles embedded quotes in args).

## Pilot findings (results/pilot-1..3b, all explainable)

- Ablation mechanism proven live: noskills roster = 187 (knowledge tools
  absent); codex full consults list_skills/get_skill heavily (22-32
  calls/leg), Claude Code makes ~0 knowledge calls but 23-28 ToolSearch
  calls (client discovery substitutes; `select:`-by-name schema fetches).
- First repeatable ablation effect (2/2 vs 0/2 across pilot-3/3b):
  sonnet + `measure_replace_terminals_L1` passes WITH skills (get_skill →
  full author-test-apply chain) and stalls without. ToolSearch substitutes
  for discovery, NOT workflow guidance — the paper's framing.
- `python_ems_control` L2/L3: sonnet fails in BOTH arms (never drives
  create_python_plugin even when named); gpt-5.4 passes. Cross-model
  discriminator, not knowledge-related.
- Scoring rule (a6dd057): with multi-tool accept sets, pass if ANY called
  accepted tool's FIRST call is not ok:false.
- Pinned refs: baseline-hvac+Boston EUI 57.41 kBtu/ft2 (full chains);
  SystemD+Boston 28.21/28.44 (test_07); SystemD 44 zones/328 surfaces;
  eplusout.err asset 261 warnings/0 fatal/0 severe.

## Open items

- Infra-retry for transient claude rc=1 during matrix (decide before matrix).
- test_09 tool-routing still carries its own A/B harness — untouched.
- README/methodology gained arm/provider env docs; D9 metric text rewrite in
  methodology is drafted only as plan text — finalize with paper tables.
