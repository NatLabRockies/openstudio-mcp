# Analysis handoff — prod-2026-08b (outcome-graded production matrix)

Companion to `benchmark-production-brief-2026-08.md` (the RUN spec, now
historical) and `plan-outcome-grading.md` (the grading design). **This file is
the starting point for the analysis/paper-writing session.** It records the run
inventory, verified mechanics, preliminary findings with exact numbers, and the
status of every hypothesis.

Written 2026-08-07 during the run, from live data. Every number below is
reproducible from `results/prod-2026-08b*/` — none is carried over from pilots.

## Provenance (non-negotiables, all satisfied)

- Image: `openstudio-mcp:bench-2026-08`, id
  `sha256:cf9e9f7cb01afeb78e218dca38ac887d55400c51bc54d77eb40759829ee581fd`
  — identical for every leg.
- Harness commit: `e602374` for every leg (rubric 1.1, outcome grading).
- `LLM_TESTS_RETRIES=0`; n=3 repeats per cell; one leg per invocation.
- Case set: the 18-hard-case `-k` for every cell.
- `timeout_base=120` for the whole comparison matrix; the t240 sweep is a
  SEPARATE sweep-id and is never compared against 120s legs of another model.

## Run inventory

| sweep | model | arms | legs |
|---|---|---|---|
| prod-2026-08b | claude-sonnet-4-6 | full, noskills, nodiscovery, nodiscovery-noskills, nohost | 15 |
| prod-2026-08b | claude-haiku-4-5-20251001 | same 5 | 15 |
| prod-2026-08b | gpt-5.4 (codex) | full, noskills | 6 |
| prod-2026-08b | gpt-5.4-mini (codex) | full, noskills | 6 |
| prod-2026-08b-t240 | claude-haiku-4-5-20251001 | full, nodiscovery @240s | 6 |
| prod-2026-08b-t240 | claude-sonnet-4-6 | full, noskills @240s | 6 |
| prod-2026-08b | claude-opus-4-6 | full, noskills, nodiscovery, nohost, nodiscovery-noskills | 15 |

**RUN COMPLETE 2026-08-07: 66/66 legs, all pass the contamination check.**
Anthropic spend $144.62 (54 claude legs); 12 codex legs billed to a ChatGPT
subscription. Aggregated into `results/prod-2026-08b/paper/` and
`results/prod-2026-08b-t240/paper/`.

Opus scope was EXPANDED beyond the brief (user decision 2026-08-07, motivated
by F3): nodiscovery x3 and nohost x3 added. ~~Opus lacks only
nodiscovery-noskills~~ — **completed 2026-08-10** (user request): 3 legs at
the ORIGINAL harness e602374 + image bench-2026-08 via a pinned worktree, so
provenance matches every other prod leg. 53/54 = **98.1% outcome, 98.1%
routing, gap 0.0 — zero outcome mismatches**, the only zero-gap cell in the
run. The 1 miss is a `wrong_tool` on roof L1 (opus edited the construction
via generic get_object_fields/set_object_property — a legitimate alternate
route the accept set doesn't credit; note for the accept-set-design
limitations paragraph). $18.09. Opus 5-arm ladder complete.

### Tool-search penalty scales inversely with capability (F3 completed)

Outcome-pass, full -> nodiscovery: haiku 61.1 -> 77.8 (**+16.7**), sonnet
81.5 -> 87.0 (**+5.5**), opus 92.6 -> **98.1** (**+5.5**). Removing deferred
discovery helps EVERY claude tier; the penalty is largest for the smallest
model but never reverses. Opus nodiscovery is the best cell in the run —
**100% routing, 98.1% outcome, 45.4s mean** (fastest claude cell), legs
18/17/18 with two perfect legs.

`no_mcp_tool` (never called an MCP tool) remains haiku-only: 5/6/4 in its
tool-search arms, 0 in nodiscovery arms; opus and sonnet are 0 everywhere.
Host-tool escape likewise: haiku 2.43 calls/test in full, opus 0.17,
sonnet 0.07.

### Headline table — outcome vs routing pass, per cell (n=3, 18 cases)

| model | arm | outcome | routing | gap |
|---|---|---|---|---|
| opus-4-6 | full | 92.6% | 96.3% | 3.7 |
| opus-4-6 | noskills | 83.3% | 92.6% | 9.3 |
| opus-4-6 | nodiscovery | **98.1%** | **100.0%** | 1.9 |
| opus-4-6 | nodiscovery-noskills | **98.1%** | 98.1% | **0.0** |
| opus-4-6 | nohost | 87.0% | 98.1% | 11.1 |
| sonnet-4-6 | full | 81.5% | 96.3% | 14.8 |
| sonnet-4-6 | noskills | 74.1% | 87.0% | 13.0 |
| sonnet-4-6 | nodiscovery | 87.0% | 90.7% | 3.7 |
| sonnet-4-6 | nodiscovery-noskills | 85.2% | 94.4% | 9.3 |
| sonnet-4-6 | nohost | 77.8% | 85.2% | 7.4 |
| haiku-4.5 | full | 61.1% | 83.3% | 22.2 |
| haiku-4.5 | noskills | 62.5% | 79.2% | 16.7 |
| haiku-4.5 | nodiscovery | 77.8% | 92.6% | 14.8 |
| haiku-4.5 | nodiscovery-noskills | 79.6% | 92.6% | 13.0 |
| haiku-4.5 | nohost | 63.0% | 83.3% | 20.4 |
| gpt-5.4 | full | 81.5% | 96.3% | 14.8 |
| gpt-5.4 | noskills | 75.9% | 96.3% | 20.4 |
| gpt-5.4-mini | full | 74.1% | 92.6% | 18.5 |
| gpt-5.4-mini | noskills | 77.8% | 96.3% | 18.5 |
| sonnet-4-6 | full@240 | 87.0% | 98.1% | 11.1 |
| sonnet-4-6 | noskills@240 | 87.0% | 96.3% | 9.3 |
| haiku-4.5 | full@240 | **61.1%** | 85.2% | 24.1 |
| haiku-4.5 | nodiscovery@240 | 81.5% | 94.4% | 13.0 |

**H6 confirmed on the full arm, monotonically**: routing-to-outcome gap 3.7
(opus) < 14.8 (sonnet) < 22.2 (haiku). Routing alone would rank these
96.3 / 96.3 / 83.3 — nearly flat. Gate 2 is what separates the tiers.

Opus per-case (full arm): measure authoring 8/9, EMS 8/9, zone priority 9/9,
add_hvac + floorplan + baselines perfect, roof_insulation 7/9. Opus has ZERO
outcome mismatches outside roof_insulation — its 2 other misses are
`wrong_tool` (gate 1), i.e. tool choice, not broken artifacts. Opus at reduced
scope (full + noskills only) per the locked 2026-08-06 decision.

Pass counts per leg (routing+outcome, denominator = attempted):

- sonnet full 14/16/14 · noskills 14/12/14 · nodiscovery 15/16/16 ·
  nodiscovery-noskills 14/17/15 · nohost 15/14/13
- haiku full 11/11/11 · noskills 12/**7 of 12**/11 · nodiscovery 14/14/14 ·
  nodiscovery-noskills 15/15/13 · nohost 12/10/12
- gpt-5.4 full 13/15/16 · noskills 15/13/13
- gpt-5.4-mini full 15/13/12 · noskills 15/14/13
- haiku @240s: full 13/11/9 · nodiscovery 15/14/15

Anthropic spend for the 42 claude legs above: $72.39. Codex legs bill to a
ChatGPT subscription and report `cost_usd = 0`.

## Data locations

- Leg results: `results/prod-2026-08b/*.json`, `results/prod-2026-08b-t240/*.json`
  (gitignored). Every row carries the `outcome` dict (facts + rubric verdict).
- `results/<sweep>/_meta/` — `preflight.json`, `sweep_meta.json`. **Kept out of
  the sweep root on purpose**: the aggregator globs `*.json` and aborts on mixed
  image identity if a file without `run_config` sits beside the legs.
- `results/prod-2026-08b/_invalid/` — one quarantined rate-limited leg (below).
- Transcripts: `%TEMP%/llm-sweep/<sweep-id>/<leg>/` — volatile, archive promptly.
- Aggregate: `python scripts/benchmark_aggregate.py results/prod-2026-08b`
  (emits `paper/`, incl. **`outcome.md`**, the headline table). Aggregate the
  t240 sweep separately — the aggregator keys on (model, arm) and would
  silently merge 120s and 240s legs of the same cell.

## Run hazards discovered (read before trusting any leg)

1. **Rate-limit contamination — silent and dangerous.** When the claude CLI
   fails hard (HTTP 429 monthly spend limit), `runner.py` raises before
   recording per-test metrics, so the row inherits the PREVIOUS test's cost,
   tokens, and tool-call list and is classified `wrong_tool`. Nothing in the row
   says "API error". Signature: tiny wall-clock `duration_s` (~3s) paired with a
   large carried-over `duration_ms` (~68s). Detector:
   `scratchpad/check_leg.py` (flags `duration_s < 15 and duration_ms/1000 >
   2*duration_s and not passed`). One leg (sonnet nodiscovery-noskills r3) was
   caught, quarantined to `_invalid/`, and re-run clean. **Run the detector after
   every leg; it found 1 bad leg in 48 with zero false positives.**
2. **Skips are not failures.** A failed setup test cascades `pytest.skip` into
   its dependents. The harness records them with `skipped: true` and no stats
   (conftest.py:437), and the aggregator excludes them from every pool. Leg
   `haiku noskills r2` reads 7/18 but is honestly **7 of 12 attempted**. Always
   report the attempted denominator.
3. Bash tool cwd persists between calls — run the sweep from the repo root.
4. `codex` is not on PATH; the harness falls back to
   `%LOCALAPPDATA%\Programs\OpenAI\Codex\bin\codex.exe` (codex-cli 0.146.0).

## Preliminary findings

All n=3, 18 cases/leg. Percentages are per-test over attempted rows.

### F1. Outcome grading is what makes the benchmark discriminate

Routing pass (gate 1) is near ceiling for the capable models; nearly all failure
is at gate 2. gpt-5.4 routed 96.3% and delivered 81.5% (full) / 75.9%
(noskills); outcome mismatches are 8-11 of the ~10-13 failures per cell. Under
the old routing-only grading gpt-5.4 would have scored 96% and the benchmark
would have been uninformative. Zero ungradable rows across all 48 legs.

### F2. H6 (routing-vs-outcome gap larger for smaller models) — TRUE within
claude tiers, NOT reproduced within OpenAI tiers

| model / arm | outcome | routing | gap |
|---|---|---|---|
| sonnet full | 81.5% | 96.3% | 14.8 |
| haiku full | 61.1% | 83.3% | 22.2 |
| gpt-5.4 full | 81.5% | 96.3% | 14.8 |
| gpt-5.4-mini full | 74.1% | 92.6% | 18.5 |

Claude tiers are 20 points apart on outcome; OpenAI tiers only 7. Caveat: vendor
tier labels are not a controlled variable — mini may not be as small relative to
gpt-5.4 as haiku is to sonnet. **State H6 as a claude-tier result.**

Sharpest single instance: measure authoring, haiku full — 8 rows routed
correctly, only 2 produced a working measure. Sonnet full: 9 routed, 9 worked.

### F3. Haiku's assistance-layer inversion is driven by tool search alone

Per-test means, haiku:

| arm | quality | time | cost | timeouts | no_mcp_tool |
|---|---|---|---|---|---|
| full | 61.1% | 64.7s | $0.071 | 8 | 5 |
| noskills | 62.5% | 56.6s | $0.060 | 6 | 6 |
| nohost | 63.0% | 47.4s | $0.053 | 3 | 4 |
| nodiscovery | 77.8% | 31.9s | $0.071 | 1 | 0 |
| nodiscovery-noskills | 79.6% | 33.8s | $0.078 | 0 | 0 |

Removing skills: +1.4pp. Removing host tools: +1.9pp. Removing tool search:
**+16.7pp**. `no_mcp_tool` (never called any MCP tool) occurs 5/6/4 times in the
tool-search arms and **0** without it. `outcome_mismatch` is flat across all
arms (12/8/8/7/11) — capability is unchanged; only tool *acquisition* changes.

Tier-specific: sonnet gains only +5.5pp from the same ablation and has **zero**
`no_mcp_tool` failures in every arm. Same for both GPT models.

### F4. The inversion is NOT a budget race (t240 result)

| haiku cell | pass | mean dur | timeouts | no_mcp_tool |
|---|---|---|---|---|
| full @120s | 61.1% | 64.7s | 8 | 5 |
| full @240s | **61.1%** | 61.1s | **0** | 3 |
| nodiscovery @120s | 77.8% | 31.9s | 1 | 0 |
| nodiscovery @240s | 81.5% | 34.5s | 0 | 1 |

Doubling the budget eliminated every timeout (8 → 0) and left the pass rate
**exactly unchanged**. Mean duration did not rise (64.7 → 61.1s) — haiku was
finishing, and finishing wrong. The 16-20pt gap to nodiscovery survives at
double the clock. **Timeouts were a symptom, not the cause.** This supersedes
the H3-style "budget race" reading for discovery (it may still hold for the
pilot-era *skills* finding, which is a different ablation).

### F5. Tool search trades tokens for turns — and only the big model banks it

| | quality | time | cost/test |
|---|---|---|---|
| haiku full | 61.1% | 64.7s | $0.071 |
| haiku nodiscovery | 77.8% | 31.9s | $0.071 |
| sonnet full | 81.5% | 62.3s | $0.151 |
| sonnet nodiscovery | 87.0% | 55.9s | $0.237 |

For haiku, disabling tool search is better on quality, 2x faster, and **the same
cost** — a strict improvement, not a tradeoff. Haiku spends the token savings
back on discovery turns (full arm: half the cache reads, 33% more output
tokens). For sonnet it is a real tradeoff: tool search costs 5.5pp of quality
but makes each test **37% cheaper**. NOT the classic time/cost/quality triangle.

This is in tension with Anthropic's published tool-search numbers (Opus 4
49%→74%, Opus 4.5 79.5%→88.1% tool-selection accuracy, ~85% token reduction).
Likely reconciliation, to argue in the paper: their metric is tool-SELECTION
accuracy in isolation on large models with large catalogs; ours is end-to-end
task completion at ~190 tools under a fixed wall-clock budget. Both can hold.
Refs: platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool,
anthropic.com/engineering/advanced-tool-use.

### F6. H2 (consultation propensity moderates knowledge-layer value) — SUPPORTED

Knowledge-tool calls per test: gpt-5.4 **1.83** (pilot measured 1.78 — good
stability), sonnet 0.33, gpt-5.4-mini 0.22, haiku 0.00. The ablation effect
tracks propensity: removing skills costs gpt-5.4 5.6pp (81.5 → 75.9), while mini
*gains* 3.7pp and haiku is flat. Caveat: measure authoring drives most of
gpt-5.4's delta (8/9 → 5/9) at n=3.

### F7. roof_insulation fails for every model, vendor, and arm

Outcome-pass counts out of 9: sonnet full 4, haiku full 3, gpt-5.4 full 3,
gpt-5.4 noskills 2, mini full 2, mini noskills 4 — with 5-6 outcome mismatches
in nearly every cell. Both tiers of both vendors replace the roof assembly with
a bare insulation slab (worse than the baseline R-4.36). Every other case is at
or near ceiling for the capable models. **This is a tool-affordance/prompt
problem, not a capability gap** — and the single biggest product lever the
benchmark surfaced. Cross-reference tracking issues #118-#121.
**FIXED + RE-RUN 2026-08-07** — these numbers are now the PRE-fix baseline;
post-fix numbers live in sweep `roof-fix-2026-08` (see NEXT ACTION below and
`plan-roof-insulation-affordance.md` Outcome).

### F8. Escape behavior is haiku-specific (H4)

Host-tool calls per test: haiku full **2.43** (156 Bash calls, 29 sub-agent
spawns across its legs), mini 0.41, gpt-5.4 0.09, sonnet 0.07. Escapes (zero MCP
calls + host calls > 0): haiku 2, mini 1, others 0. Not a general small-model
behavior.

### F9. Matched discovery regime: claude edges GPT at both tiers

Codex loads all schemas up front natively, so codex `full` is the analogue of
claude `nodiscovery`, NOT claude `full`. On that basis: gpt-5.4 81.5% vs sonnet
nodiscovery 87.0%; mini 74.1% vs haiku nodiscovery 77.8%. Claude also uses fewer
turns (7.8 vs 10.5) and fewer tool calls (7.4 vs 10.4).

## NEXT ACTION (before analysis write-up)

~~**Fix the insulation-upgrade affordance and re-run `roof_insulation` across
models**~~ — **DONE 2026-08-07.** Fix shipped in two commits (`f9c4b96` tool +
warning + knowledge layer; `61675a6` selection-time description steering after
v1 legs showed response warnings go unread) and re-run across all 5 models
into sweep `roof-fix-2026-08` (15 legs, all clean, $6.80 Anthropic). Full
results + interpretation: `plan-roof-insulation-affordance.md` "Outcome"
section. Summary for the paper:

- roof_insulation L2 outcome-pass 1/15 -> **10/15**; totals 19/45 -> 30/45.
- mini 2/9 -> 8/9, gpt-5.4 3/9 -> 6/9, opus 7/9 -> 9/9; sonnet and haiku
  UNCHANGED (4/9, 3/9) — under deferred tool search they select the old tool
  triple by exact name and never load the new tool's schema, so the fix is
  invisible to them. F3/F9's discovery-regime split reproduced on a product
  fix instead of an ablation.
- L3 remains 6/15: its prompt prescribes the old sequence verbatim and
  compliant agents follow it — a benchmark-design fact, not a product gap.
- Benchmark comparability preserved: prompts + rubric untouched; only the
  accept set gained the new tool. The prod-2026-08b F7 numbers stay valid as
  the pre-fix baseline.
- v1-vs-v2 evidence (2 quarantined legs in `results/roof-fix-2026-08/_invalid/`):
  warnings delivered in tool responses were read 0/5 times; moving the same
  hint into tool descriptions is what changed behavior. Paper-worthy point
  about WHERE affordance guidance must live.

~~Second: opus nodiscovery x3~~ — **DONE 2026-08-07** (plus nohost x3). See
the tool-search section above: the penalty does NOT vanish at the top; opus
gains the same +5.5pp as sonnet and reaches 98.1% outcome / 100% routing.
Remaining gap in the design: opus has no `nodiscovery-noskills` cell (3 legs,
~$18) if a complete 5-arm opus ladder is wanted.

## Analysis tasks still to do

1. **Derive API-equivalent cost for codex from recorded tokens.** Tokens ARE
   recorded (`input_tokens`, `cache_read_tokens`, `output_tokens`); only
   `cost_usd` is 0 and `duration_ms` is 0 (use pytest `duration_s`). Gotcha:
   codex `input_tokens` INCLUDES cached tokens, claude's EXCLUDES them — derive
   uncached = `input_tokens - cache_read_tokens` for codex. Prototype numbers at
   published list prices ($2.50/$15.00 per Mtok gpt-5.4; $0.75/$4.50 mini; 90%
   cached discount): gpt-5.4 full $0.137/test, noskills $0.148, mini full
   $0.039. Re-verify prices at write-up. For symmetry recompute the claude side
   from tokens too, rather than mixing CLI-reported with derived dollars.
   Implement in `scripts/benchmark_aggregate.py` (deferred during the run to
   keep one harness sha across all legs).
2. Wire escape metrics into the tables (auto-asterisk affected rows).
3. `no_mcp_tool` subclassification: {gave up | answered in text | escape} from
   `host_tool_counts`.
4. Archive to `docs/benchmarks/prod-archive-2026-08b/` with a README recording
   image digest, harness sha, and each leg's resolved model id from its ndjson;
   include transcript/droppings zips and the quarantined `_invalid/` leg.
5. Re-score check: rubric is versioned per row (`RUBRIC_VERSION`), so any
   threshold change re-scores from recorded facts with NO re-run.

## Addendum 2026-08-10 — three run batches (user request)

All contamination-checked, n=3 per cell. Claude spend this session $29.00
(opus nd-ns $18.09 + roof-nd $9.25 + codegen $1.66); codex $0 (subscription).

### 1. Opus nodiscovery-noskills (into prod-2026-08b)

See the F3 section above — 98.1% outcome / 98.1% routing / gap 0.0, zero
outcome mismatches. Completes the opus 5-arm ladder.

### 2. Roof-case nodiscovery arms (into roof-fix-2026-08, post-fix image)

Roof rows out of 9, full (tool search) vs nodiscovery (schemas up front):

| model | full | nodiscovery |
|---|---|---|
| sonnet-4-6 | 4/9 | **8/9** |
| haiku-4.5 | 3/9 | **8/9** |
| opus-4-6 | 9/9 | 7/9 |

The F7-fix finding 2 is now CAUSAL, not inferred: give sonnet/haiku the
schemas and they adopt the additive path (sonnet L1 even used
add_layer_to_construction; its L2/L3 passed via a rebuilt-but-complete
construction — the description steering works once the description is seen).
Opus's 2 nodiscovery misses are both roof L1 and are genuine physics slips
caught by outcome grading: it added a layer NAMED "R-30 Upgrade" built ~1
inch thick (r_si 0.98, not 5.28). n=3 — report as an observation, not a
regression.

### 3. Arm C codegen baseline (sweep codegen-2026-08) — R1's "is MCP needed"

`tests/llm/test_11_codegen_arm.py`: no MCP server; agent gets shell + a
container with the SDK/CLI/E+ and scripts everything. 6 outcome-only tasks.
First-ever execution of this arm; final harness `ac238d6`, image
roof-fix-2026-08 (stale-image override documented in `_meta/` — the delta
since its build is host-side grading only).

| task | sonnet-4-6 | gpt-5.4 |
|---|---|---|
| create 2-story 4-zone OSM from scratch | 1/3 (2x 300s timeout) | 3/3 (~84s) |
| count zones in 44-zone OSM | 3/3 | 3/3 |
| load-modify-save | 3/3 | 3/3 |
| count err warnings (261) | 0/3 (says 263) | 0/3 (says 0) |
| annual sim + EUI vs 28.21 pin | 3/3 | 3/3 |
| OSM -> IDF | 3/3 | 3/3 |
| **total** | **13/18** | **15/18** |

Reading for the paper: unscaffolded agents are decent at inspect / modify /
simulate / convert, but creation-from-scratch is unreliable under a time
budget (sonnet 1/3 at 300s vs near-ceiling with MCP tools at 120s) and
exact parsing fails for BOTH vendors (sonnet counts the 2 banner-recap
`** Warning **` lines; gpt answers 0). MCP's value = creation + reliability,
not raw capability. Caveats: 6 simpler tasks, not the 18-case set; codex
always has native shell (allowed_tools no-op) — footnote both.

**Shakedown found a second real product defect**: `extract_eui`
(mcp_server/skills/results/sql_extract.py) read the E+ tabular Units strings
but assumed SI — gpt-5.4's self-authored OSW produced an InchPound sql and
its CORRECT sim (28.23 kBtu/ft2) graded as 2485 kBtu/ft2 (~88x). Fixed +
regression tests in `ac238d6` (IP-rewritten fixture must equal the SI
fixture's EUI; unknown units yield None, never a guess). The MCP arms never
hit this because the server's own OSW always requests SI. Second instance of
"outcome grading found a defect routing grading could not see" — this time
in the GRADER'S own extraction path, i.e., in product code. Quarantine
history (7 legs incl. one lost file): `results/codegen-2026-08/_invalid/README.md`.

## Claims that must NOT be carried into the paper

Everything in the brief's superseded-claims register, plus:

- Pilot pass rates and the 2 discarded `prod-2026-08` legs are routing-only —
  never compare them to prod-2026-08b numbers, even informally.
- The val-grading legs (`results/val-grading/`) are n=1 machinery validation,
  not findings.
- "Haiku's inversion is a 120s budget race" — **disproven by F4**.
