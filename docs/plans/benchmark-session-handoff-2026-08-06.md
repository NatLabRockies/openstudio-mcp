# Benchmark session handoff (2026-08-06) — knowledge-layer ablation deep-dive

Supersedes `benchmark-session-handoff-2026-08-05.md` (still valid for sweep
mechanics, codex CLI flags, pinned refs — read it too). Branch:
`feat/llm-benchmark-realism`. SPIKE-2 is ON HOLD (user decision) until the
knowledge-layer ablation is fully understood.

## What happened this session

1. **Pilot-4** (results/pilot-4, 18 hard cases, n=1 per arm, image
   `openstudio-mcp:dev`): haiku full 13/18 vs noskills 8/18;
   gpt-5.4-mini 13/18 in BOTH arms. Pooled with pilot-3b (sonnet 16/15,
   gpt-5.4 17/18 full / 18/18 noskills). Aggregated view (all 8 legs,
   `--ignore-digest`): scratchpad pilot-all, regenerate anytime with
   `python scripts/benchmark_aggregate.py <dir> --ignore-digest`.
2. **New metrics** (commit 04302ba): `behavior.md` (knowledge-call /
   ToolSearch / token means per model+arm), `flips.md` (paired per-task
   full-vs-noskills discordance, skill-lift/skill-drag),
   `tool_error (recovered)` tagging (first call failed, later accepted-tool
   call succeeded — 3 such across pilot-4).
3. **Recorder bug fixed** (3ed9a16): call-phase skips (failed setup →
   needs_model cascade) were logged as failures carrying the PREVIOUS test's
   stats/tool_calls. Now `skipped: true`, excluded from rates, footnoted.
4. **Fixes landed from the failure audit** (each linked to a tracking issue,
   issues left OPEN for sibling audits):
   - f38cc1f (#118) import_floorspacejs description: server-side paths,
     /inputs, list_files.
   - b92bc8c (#119) `path_denied_hint()` in config.py appended to both
     not-found and not-allowed errors; wired into import_floorspacejs;
     unit + integration tests. Other call sites = #119 checklist.
   - 88ee3be (#120) new-building "ask for path" → "list_files('/inputs')
     first"; file_transfer upload-first framing + request_upload description.

## THE central finding: consultation propensity

Knowledge calls per test (full arm): gpt-5.4 **1.78**, sonnet **0.22**,
gpt-5.4-mini **0.11**, haiku **0.00**. Interpretation:

- gpt-5.4: heavy consulter, at ceiling → skills cost tokens/latency, no lift.
- sonnet: selective consulter — its few get_skill calls land exactly on the
  multi-step case they flip (`measure_replace_terminals_L1`, repeatable
  2/2-with vs 0/2-without across pilots 3/3b/4).
- gpt-5.4-mini: ignores the knowledge layer → ablation is behaviorally a
  no-op (13/18 == 13/18, 4/5 identical failures). Its failures are
  capability failures.
- haiku: NEVER consulted skills, so its +5 full-vs-noskills delta cannot be
  consultation-mediated. 11/18 tasks flipped direction between its arms =
  high per-run variance. Hypothesis worth testing (NOT a claim): noskills
  had 6× `no_mcp_tool` (zero MCP calls — gave up/asked questions) vs 3×
  with skills present → "engagement collapse without discoverable entry
  points". Needs haiku ×3 repeats both arms.

Paper framing: knowledge-layer value = f(consultation propensity × headroom),
and a pass-rate-only ablation is uninterpretable without the consultation
metric (this answers reviewer B3 more deeply than they asked).

## Role of the harness (claude code vs codex) — must be in the paper

The harness is the agent runtime driving the model: `claude -p` (Claude
Code non-interactive) for Anthropic models, `codex exec` for GPT models.
It supplies the system prompt, the turn loop, the MCP client that connects
to our server container, AND client-side affordances that confound results:

- **Tool discovery**: Claude Code exposes ToolSearch (haiku 4.9, sonnet 2.4
  calls/test — schema fetches by name) — a client-side substitute for our
  knowledge layer. Codex has none, so codex models lean on our
  list_skills/get_skill (or nothing, in noskills).
- **Filesystem/shell access**: both harnesses let agents stat/ls the HOST,
  which caused the server-vs-host path trap (gpt statted the local file and
  passed C:\...; haiku distrusted the correct /inputs path after host `ls`
  failed and read our server source to debug it).
- **Token accounting differs**: claude CLI input_tokens excludes cache
  reads (~12/test) vs codex full counts (~270k/test) — behavior.md token
  columns are NOT cross-provider comparable; footnote this.

So every result is a (model × harness) pair, not a pure model property.
Ablation comparisons are valid because both arms share a harness.

## Next session, in order

1. Rebuild check: image `openstudio-mcp:dev` must postdate b92bc8c
   (a rebuild was kicked off at session end — verify with
   `docker image inspect openstudio-mcp:dev --format '{{.Created}}'`;
   sweep preflight enforces this anyway).
2. **Pilot-5: haiku ×3 repeats, both arms**, same 18-case `-k` (in
   handoff-05 / results/pilot-4 sweep commands; use
   `--model haiku:claude --arms full,noskills --repeats 3`, ONE leg per
   background invocation, NEVER pipe the sweep through head/tail —
   SIGPIPE kills it). Purpose: settle haiku variance; test engagement-
   collapse hypothesis via no_mcp_tool counts in failure_modes.md.
   Optionally rerun mini/gpt legs on the fixed image to see if the path
   fixes (#118/#119) recover import_floorplan (expected: yes — that's a
   nice before/after paper anecdote: "the benchmark found and validated
   tool-ergonomics fixes").
3. Decide with user: SPIKE-2 resume → then PR to develop → tag v1.2.0 →
   matrix (see handoff-05 for the full matrix; ADD haiku-noskills +
   gpt-5.4-mini full+noskills rows per user decision 2026-08-06).
4. Open items: infra-retry for transient claude rc=1; D9 metric text;
   #118/#119/#120 sibling audits (checklists on the issues).

## Gotchas added this session

- NEVER pipe a background sweep through `head`/`tail` — head exits, pipe
  closes, SIGPIPE kills pytest mid-leg, pipeline exit code lies (0).
- `openstudio-mcp:dev` was rebuilt mid-pilot by something outside the
  session (b982eaf → eaf9c63d, same mcp_server tree). Aggregator's digest
  guard caught it; `--ignore-digest` was justified ONLY because no server
  commits landed between builds. The matrix uses the pinned tag.
- One mini-full leg died silently overnight at 17/18 (output stopped,
  no error, no benchmark.json) — unexplained; if it recurs, investigate
  before trusting long unattended legs.
- results/pilot-4/haiku_noskills_r1.json.corrupt = pre-fix recorder output,
  kept for the record; don't aggregate it.

## Where everything lives

- Results: results/pilot-{1,2,3,3b,4}/ (gitignored) + per-leg runs dirs
  with ndjson transcripts under %TEMP%/llm-sweep/<sweep>/<leg>/ndjson_logs/.
- Aggregate artifacts: <sweep>/paper/ (table4, ablation, flips, behavior,
  discovery, stability, failure_modes).
- Memory: project_llm_benchmark_rework.md (updated with pilot-4 findings).
- Issues: #118 (tool descriptions), #119 (error messages), #120 (guide
  language) — commits f38cc1f / b92bc8c / 88ee3be.
