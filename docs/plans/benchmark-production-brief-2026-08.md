# Production benchmark brief (2026-08)

Single source of truth for the production matrix run (new session).
USER DIRECTIVE (2026-08-06): the production run is ENTIRELY data-driven —
every paper claim must cite a leg/test/transcript produced by THIS run.
Nothing from the pilots is carried forward as a finding; pilots inform
hypotheses and run design only. This brief therefore contains NO findings —
only run mechanics, verified condition-facts, and hypotheses to test.

Prior narrative docs (`benchmark-session-handoff-2026-08-05/-06.md`) are
HISTORICAL: several claims in them were later disproven by their own
archived data (see the superseded-claims register below). Do not cite them.

## Run spec — non-negotiables

1. ONE pinned image for every leg: rebuild, tag (e.g.
   `openstudio-mcp:bench-2026-08`), record digest in the archive README.
2. ONE harness commit for every leg: >= cac68d9 (sandbox cwd + utf-8 fix).
3. `LLM_TESTS_RETRIES=0`. Repeats replace retries (sweep preflight aborts
   otherwise).
4. n=3 repeats per (model, arm) cell.
5. One leg per background invocation. NEVER pipe sweep output through
   head/tail (SIGPIPE kills pytest; exit code lies).
6. Archive at the end: results JSONs + transcript/droppings zips +
   escape annotations to docs/benchmarks/ (pattern:
   pilot-archive-2026-08; write a README with image digest + harness sha).

## Matrix

- claude sonnet + haiku x {full, noskills, nodiscovery,
  nodiscovery-noskills, nohost} x3 = 30 legs (~8-25 min each observed)
- codex gpt-5.4 + gpt-5.4-mini x {full, noskills} x3 = 12 legs
- Case set: the 18-hard-case `-k` (setup + import_floorplan, add_hvac,
  python_ems_control, measure_replace_terminals, zone_equipment_priority,
  roof_insulation) unless the scope decision (below) says full suite.

Sweep command shape (per leg; repeats r2/r3 via --repeats 2/3, resume-safe):

    python scripts/benchmark_sweep.py --sweep-id prod-2026-08 \
      --image openstudio-mcp:bench-2026-08 --model haiku:claude \
      --arms full --repeats 1 --pytest-args "tests/llm/test_01_setup.py \
      tests/llm/test_06_progressive.py -k '<18-case expression>'"

## Verified condition-facts (mechanics, not findings)

- Arms plumbing (all live-verified): `noskills` = server hides
  list_skills/get_skill/recommend_tools (OSMCP_DISABLE_KNOWLEDGE_SKILLS=1,
  substring match so composites work); `nodiscovery` = claude-only,
  ENABLE_TOOL_SEARCH=false (all ~190 schemas load up-front); `nohost` =
  claude-only, --disallowedTools strips host tools (works under
  --dangerously-skip-permissions); codex raises on nohost/nodiscovery.
- Structural note for analysis: codex loads ALL MCP schemas up-front
  natively (no deferred discovery) — codex full/noskills is the same
  discovery regime as claude nodiscovery/nodiscovery-noskills.
- Sandbox: every agent invocation runs in a fresh empty cwd under
  <leg-runs>/agent_cwd/. Bash-tool files may land in the C:\tmp mirror
  (Git Bash /tmp asymmetry) — dropped_files scans both.
- Escape metrics in every benchmark.json row: host_tool_counts,
  host_tool_call_count, agent_cwd, dropped_files, toolsearch_queries.
  Escape := mcp calls == 0 AND host calls > 0.
- Token accounting is NOT cross-provider comparable (claude input_tokens
  excludes cache reads; codex counts them). nodiscovery arms roughly
  double cache reads. Report per-provider, footnote.
- The 120s per-test timeout is LOAD-BEARING for L1 rows (multi-step
  workflows measured at 84-120s). Treat it as a benchmark parameter.
- Results are (model x harness) pairs. Ablation contrasts are valid only
  within a harness.

## Hypotheses to test (questions, not claims — each with pilot evidence)

Decision rule for all: claim only what the n=3 matrix shows; cite
prod-run legs, not pilot legs.

- H1 assistance-layer inversion (haiku): does pass rate/speed rise
  monotonically as layers are removed (full -> noskills -> nohost ->
  nodiscovery -> nodiscovery-noskills)? Pilot evidence: 9/14/collapse ->
  13/12/13 -> 16 -> 17 -> 18 (right side n=1; full arm had NO sandboxed
  anchor). Archive: pilot-5.
- H2 consultation propensity moderates knowledge-layer value: measured
  knowledge-calls/test (pilots: gpt-5.4 1.78, sonnet 0.22, mini 0.11,
  haiku 0.00) — does ablation effect track propensity?
- H3 knowledge value = workflow compression vs the time budget, not
  enablement: inv4 showed the historic sonnet "skill lift" was an
  L1-only 120s budget race (archive: inv4-doc-fix-check + pilot-3/3b
  tool_calls). Test: compare durations with/without skills, and pass
  deltas at the timeout margin.
- H4 escape is discovery-regime-dependent and model-specific: pilots saw
  28/28 escapes from haiku only, zero under nodiscovery/nohost. Measure
  escape rate per model x arm from the new host metrics.
- H5 python_ems capability wall is model- AND regime-dependent: sonnet
  failed L2/L3 in ToolSearch arms yet haiku passed under nodiscovery
  (real accepted create_python_plugin calls). D6-outcome-grade a sample —
  routing passes may hide quality differences.

## Superseded-claims register (do NOT carry into the paper)

- "Sonnet measure authoring 2/2-with vs 0/2-without skills, repeatable"
  — FALSE as scoped: L1-only; L2/L3 passed noskills in pilots 3+3b;
  mechanism = 120s budget race; does not reproduce on current stack
  (inv4 9/9).
- "gpt-5.4 noskills is +17% slower" — n=1, reversed in pilot-3b (-4%).
- "haiku noskills = engagement collapse" — superseded: transcripts show
  host-side circumvention, not disengagement.
- "mini measure failure = capability" — was cross-leg contamination
  (shared /measures volume, fixed fb7ed15).
- Any pass-rate from pre-sandbox legs (marked * in
  pilot-archive-2026-08/escape_annotations.md) — condition-contaminated:
  agents ran with cwd = our repo (source + grading tests readable;
  likely also loaded our CLAUDE.md into context).

## Open decisions (ask user before launching)

1. Scope: 18 hard cases vs full progressive suite for full/noskills rows.
2. 120s timeout: keep + footnote, raise, or run a sensitivity cell.
3. ToolSearch dose probe (ENABLE_TOOL_SEARCH=auto:N) as an extra arm?
4. Second non-Anthropic vendor (gemini seam exists, unbuilt) — worth the
   adapter for vendor-generality, or note as limitation?

## Analysis deliverables

- Aggregator output per sweep (table4/ablation/flips/behavior/discovery/
  stability/failure_modes) + wire escape metrics into the tables
  (asterisk any escape-affected row automatically — fields exist in every
  benchmark.json now; no transcript reconstruction needed).
- no_mcp_tool subclassification: {gave up | answered in text | escape}
  from host_tool_counts.
- D6 outcome-grade sample of nodiscovery passes (H5).
- Cost/token table per arm, per provider (separately).

## Operational gotchas (carried forward, still true)

- python3 on this host = MS Store alias popup; use `python`.
- Image freshness: sweep preflight aborts if image predates last commit
  touching mcp_server/docker/pyproject; the pinned tag avoids drift.
- One pilot leg died silently overnight at 17/18 (no error, no
  benchmark.json) — if a leg goes quiet, check before trusting it.
- PS 5.1: keep git commit messages quote-free.
- Claude transcripts before cac68d9 contain cp1252 mojibake (cosmetic).

## Data locations

- Frozen pilot record: docs/benchmarks/pilot-archive-2026-08/ (committed;
  README explains conditions + asterisks; escape_annotations.{json,md};
  transcript/droppings zips; all results JSONs incl. inv4).
- Live results: results/<sweep-id>/ (gitignored) + %TEMP%/llm-sweep/
  (transcripts; volatile — archive promptly).
- Tracking issues: #118 tool descriptions, #119 error-message hints,
  #120 guide language, #121 advertised-path contract (all open with
  sibling-audit checklists).
