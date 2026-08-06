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

## Late-session additions (after the pilot-4 writeup above)

- **Cross-leg measure contamination found and fixed** (fb7ed15): the sweep
  freshened LLM_TESTS_RUNS_DIR per leg but the /measures volume defaulted to
  the shared %TEMP%/llm-test-measures — gpt-5.4-mini found a PREVIOUS leg's
  authored measure via list_custom_measures and reused it instead of
  authoring (scored wrong_tool). Measures now live under each leg's runs
  dir. CONSEQUENCE: pilot measure_replace results involving
  list_custom_measures are suspect; mini's measure_replace_L1 failure was
  a contamination artifact, NOT capability. Sonnet's skill-lift stands (its
  noskills stall never touched list_custom_measures).
- **Failure-taxonomy revision**: python_ems = genuine capability failure
  (sonnet L3 fetched create_python_plugin's schema FIRST via ToolSearch,
  tool named in prompt, docs available, then explored for 120s and never
  called it; gpt-5.4 passes both arms — the task demands authoring a Python
  EMS plugin program, a generative step weaker models avoid by context-
  gathering until timeout).
- **ToolSearch query capture** (2135005): benchmark.json now records
  toolsearch_queries per test (which schemas Claude Code fetches by name)
  — per-arm discovery-substitution evidence.
- **Claude-side discovery ablation is POSSIBLE**: `ENABLE_TOOL_SEARCH=false
  claude -p ...` disables ToolSearch, loading all schemas up-front
  (docs: code.claude.com/docs/en/agent-sdk/tool-search; default is auto at
  10% of context, `auto:N` tunes it; requires 4.5-gen models). A
  "claude-nodiscovery" arm (noskills + no ToolSearch, and/or full + no
  ToolSearch) would isolate our knowledge layer on Claude models the way
  codex already does. DECISION FOR USER: add this arm to pilot-5/matrix?
  Cost: context grows by ~190 tool schemas per prompt (token cost up).

## Paper narrative: three distinct failure classes (user-approved, keep)

The ablation surfaced three failure classes the paper should narrate
explicitly — they are the difference between "pass rates moved" and
"we know why":

**1. Capability failure (python_ems).** Sonnet's L3 transcript is
conclusive: its FIRST action was a ToolSearch that fetched the
`create_python_plugin` schema — it knew exactly which tool the task needed
(L3 names it in the prompt). It then spent the entire 120 s budget
exploring — `get_schedule_details` twice, `get_object_fields`,
`list_model_objects`, even grepping the test file for hints — and never
called the tool whose schema it was holding. No instruction fix can help:
docs were available (full arm), the schema was loaded, the prompt named the
tool. The blocker is the task itself — writing a Python program against the
EnergyPlus plugin API (calling points, actuator handles, setpoint logic).
That generative step is what weaker models displace with endless
context-gathering. Controls: identical failure in both arms (not
knowledge-related); gpt-5.4 passes in both arms (task, tools, and prompts
are sufficient).

**2. Knowledge-layer effect (measure authoring, sonnet).** Repeatable
2/2-with-skills vs 0/2-without across pilots 3/3b/4: with `get_skill`
available sonnet follows the author→test→apply chain; without it, it
stalls after two exploratory calls. Its consultation is selective (0.22
knowledge calls/test) but lands exactly where it flips the outcome.

**3. Environment/scoring artifacts (measure authoring, mini) — found and
fixed.** Mini's transcript shows textbook exploration (search_wiring_
patterns, search_api for FourPipeBeam classes, list_air_loops), then
`list_custom_measures` found an already-authored measure with the exact
target name — leaked from a previous leg through the shared /measures
volume. It rationally reused it and was scored wrong_tool. Fixed
(fb7ed15: per-leg measures dir). Related artifact class: first-call-strict
scoring rejecting recovered completions, now surfaced via the
`tool_error (recovered)` tag. The paper should note the benchmark caught
its own contamination — that is what the provenance/isolation machinery
is for.

## Nodiscovery arm: LIVE-VERIFIED (smoke, 2026-08-06)

One-case smoke (sonnet, create_building_L2, LLM_TESTS_ARM=nodiscovery):
toolsearch_count=0, zero queries, cache-read ~764k (up-front schemas ~10x
normal) — the CLI honors ENABLE_TOOL_SEARCH=false. And the mechanism
datapoint appeared IMMEDIATELY: sonnet's first action was
get_skill("new-building") — a Claude model consulting the knowledge layer,
which effectively never happens in ToolSearch arms (0.22 calls/test).
Client discovery really does substitute for the knowledge layer.

The smoke also caught a NEW server contract bug (#121, fixed 9cee2e9):
list_weather_files advertised openstudio-standards gem EPW paths
(/var/oscli/...) that the EPW allowlist rejected — sonnet picked an
advertised EPW, failed first-call ("EPW path not allowed"), recovered via
/inputs, completed the full chain, scored tool_error. Gem weather dirs now
in _SHARED_READ_ROOTS (integration test end-to-end). REBUILD REQUIRED
before pilot-5 (kicked off at session end — verify image postdates 9cee2e9).

## Contamination blast radius (empirical, all pilot legs scanned)

Measure-tool calls appear ONLY in measure_replace_terminals rows (+1 benign
roof_insulation_L1/gpt list_measure_arguments, passed). Within the family:
mini full L1 = the one contaminated-behavior failure (reused leftover);
gpt listed leftovers but authored anyway (passed); sonnet + haiku never
touched leftover state — the sonnet skill-lift is CLEAN on both sides.
Pilot-5c therefore reruns the measure family for sonnet + gpt-5.4 + mini
(both arms) on the fixed sweep; haiku's rows regenerate via 5a.

## Pilot-5 design (user approved nodiscovery 2026-08-06)

Arms available: full | noskills (server flag) | nodiscovery
(ENABLE_TOOL_SEARCH=false, claude only, 9931c9e) | nodiscovery-noskills
(both). The claude-side 2x2 finally isolates the knowledge layer the way
codex does natively:

| arm | client discovery | server knowledge | question answered |
|---|---|---|---|
| full | ToolSearch | yes | production behavior |
| noskills | ToolSearch | no | does knowledge matter when client discovery substitutes? |
| nodiscovery | none | yes | does the model consult skills when its own discovery is gone? |
| nodiscovery-noskills | none | no | floor: tool schemas alone |

Note: nodiscovery loads ~190 schemas up-front — higher tokens/prompt and
input_tokens not comparable to ToolSearch arms; report separately.

## Next session, in order

1. Rebuild check: image `openstudio-mcp:dev` must postdate b92bc8c
   (a rebuild was kicked off at session end — verify with
   `docker image inspect openstudio-mcp:dev --format '{{.Created}}'`;
   sweep preflight enforces this anyway).
2. **Pilot-5** (same 18-case `-k`; ONE leg per background invocation,
   NEVER pipe the sweep through head/tail — SIGPIPE kills it):
   a. haiku ×3 × {full, noskills} — settle variance; test engagement-
      collapse hypothesis via no_mcp_tool counts.
   b. haiku + sonnet ×1 × {nodiscovery, nodiscovery-noskills} — first look
      at the claude 2x2 (scale to ×3 if the deltas look real).
   c. measure_replace-only reruns on the FIXED sweep (contamination):
      sonnet + mini, both arms, `-k measure_replace_terminals` + setup —
      revalidates the sonnet skill-lift claim and mini's true capability
      on clean state. Cheap (~5 min/leg).
   d. Optional: gpt/mini import_floorplan rerun on the post-#118/#119
      image — before/after validation of the tool-ergonomics fixes
      (paper anecdote: the benchmark found and fixed real UX bugs).
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
