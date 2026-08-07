# Plan: fix the insulation-upgrade affordance (benchmark finding F7)

**STATUS: DONE 2026-08-07.** Implemented (commits `f9c4b96` + `61675a6`),
re-run complete (sweep `roof-fix-2026-08`, 15 legs, 5 models, all clean).
Results and interpretation in the "Outcome" section at the bottom — read that
before citing this plan. Headline: L2 outcome-pass 1/15 -> 10/15; the residual
failures are a discovery-regime interaction (tool-search models never load the
new tool's schema) plus L3's prompt prescribing the old path verbatim.

## The finding

`roof_insulation` L2/L3 fails for **all 5 models across 2 vendors** at 55-75% of
rows, with a near-identical signature: the roof assembly R-value goes DOWN.
Measured deltas: -0.61, -0.61, -0.54, -0.27 m2K/W against a baseline assembly of
R-4.36. Every other graded case is at or near ceiling for the capable models
(opus 8/9 measure authoring, 8/9 EMS, 9/9 zone priority). Opus 4-6 has **zero**
outcome mismatches outside this case.

Five independent models converging on the same wrong action is not a capability
gap. It is a missing affordance.

## Root cause (from recorded outcome facts, not speculation)

The agents do this, in order:

    load_osm_model
    list_surfaces
    create_standard_opaque_material   # one insulation material, e.g. R-3.75
    create_construction               # NEW construction, that material ONLY
    assign_construction_to_surface    # x5, replaces the roof entirely
    save_osm_model

Result recorded in the facts: construction "Roof Construction with Insulation"
with a single layer `[{"name": "Roof Insulation", "r_si": 3.75}]`,
`assembly_r_si = 3.75` — replacing a multi-layer baseline assembly of R-4.36.
The agent added insulation and made the roof worse.

**Why they do it:** there is no tool that adds a layer to an EXISTING
construction. `mcp_server/skills/constructions/tools.py` exposes
`list_materials`, `get_construction_details`, `create_standard_opaque_material`,
`create_construction`, `assign_construction_to_surface`. The natural BEM
operation — "add R-30 to the existing roof" — has no direct expression, so the
model synthesizes a replacement construction from scratch and silently discards
membrane/decking/existing-insulation layers.

The bundled prompt actively teaches this pattern:
`skills/prompts_resources/tools.py:78-84` walks through
`create_standard_opaque_material` -> `create_construction(material_names=[...])`
-> assign, with a hand-typed layer list. It works only if the model happens to
re-list every original layer.

## Fix (three parts, in order)

1. **New tool `add_layer_to_construction`** (constructions skill) — takes an
   existing construction, a material, and an insert position (default: after
   the outermost layer / before the innermost, whichever matches BEM
   convention); clones the construction with all original layers preserved and
   the new layer inserted. Returns before/after `assembly_r_si` in the response
   so the agent can self-check. This is the primary fix — it makes the correct
   operation the easy one.
2. **Guard/hint on `assign_construction_to_surface`** — when the incoming
   construction's assembly R is LOWER than the construction being replaced,
   include a warning in the `ok:True` response
   (e.g. `"warning": "assembly R decreased 4.36 -> 3.75 m2K/W; did you mean to
   add a layer to the existing construction? see add_layer_to_construction"`).
   Same pattern as tracking issue #119 (error-message hints). Do NOT hard-fail:
   lowering R is legitimate for some studies.
3. **Fix the prompt** at `skills/prompts_resources/tools.py:70-86` to lead with
   `get_construction_details` + `add_layer_to_construction` instead of
   building a construction from a hand-typed material list.

Rules that apply: every new tool needs an integration test and an entry in
`EXPECTED_TOOLS` (tests/test_skill_registration.py); add the test file to the
lightest CI shard; `_extract_*` returns snake_case dicts; no getattr dispatch.

## Verification (re-run just this case)

The sweep is resume-safe and `-k` can select a single case. After the fix,
re-run `roof_insulation` across models into a NEW sweep-id (do not mix with
prod-2026-08b — different harness):

    python scripts/benchmark_sweep.py --sweep-id roof-fix-2026-08 \
      --image <rebuilt image> \
      --model claude-haiku-4-5-20251001:claude --arms full --repeats 1 \
      --pytest-args "tests/llm/test_01_setup.py tests/llm/test_06_progressive.py -k 'create_baseline_model or create_baseline_with_hvac or roof_insulation'"

Setup cases must stay in `-k` (roof cases depend on the baseline fixture).
3 models x 3 repeats is ~9 legs at roughly 6-8 min each (3 graded rows + setup).

Success criterion: roof_insulation L2/L3 outcome-pass rate rises from ~30% to
>80% for sonnet/opus, and the assembly-R-decrease signature disappears from the
recorded facts. Rubric needs NO change — it already measures the right thing,
which is why the bug was visible at all.

## Paper angle

This is the strongest "benchmark found a real product defect" story in the run:
outcome grading (gate 2) detected an affordance gap that routing-only grading
could never see, because every one of these runs called an accepted tool with
valid arguments and got `ok: True`. Worth a short subsection.

---

## Outcome (2026-08-07, post-implementation)

### What shipped

All three parts, plus two additions the re-run itself forced:

1. `add_layer_to_construction` (commit `f9c4b96`) — copies the construction
   with all original layers plus the inserted layer, returns
   `assembly_r_si_before/after`. 5 integration tests
   (`tests/test_add_layer_construction.py`, CI shard 4).
2. R-decrease warning on `assign_construction_to_surface` — fires correctly
   (verified in transcripts) but see finding 3 below.
3. Knowledge layer — envelope_retrofit MCP prompt, tool-workflows / retrofit /
   openstudio-patterns skills, example 05, and the mirror workflow test all
   teach the additive path now.
4. **v2 (commit `61675a6`): selection-time steering.** Two v1 sonnet legs
   (quarantined in `results/roof-fix-2026-08/_invalid/`) showed the agent
   pre-selects the old tool triple by exact name via ToolSearch and batches
   all assigns — the response warning was delivered 5x and read 0x. The
   additive-path hint was added to the create_construction and
   assign_construction_to_surface DESCRIPTIONS, which agents read at plan time.
5. Benchmark case: `add_layer_to_construction` added to the roof_insulation
   accept set. **Prompts and rubric unchanged** — roof-fix legs are directly
   comparable to prod-2026-08b.

### Results — roof_insulation outcome-pass, full arm, n=3 per cell

| model | pre L1/L2/L3 | post L1/L2/L3 | pre total | post total | new-tool rows |
|---|---|---|---|---|---|
| opus-4-6 | 3/1/3 | 3/3/3 | 7/9 | **9/9** | 5/9 |
| sonnet-4-6 | 3/0/1 | 2/1/1 | 4/9 | 4/9 | 1/9 |
| haiku-4.5 | 3/0/0 | 3/0/0 | 3/9 | 3/9 | 3/9 (all L1) |
| gpt-5.4 | 3/0/0 | 3/3/0 | 3/9 | 6/9 | 6/9 |
| gpt-5.4-mini | 2/0/0 | 3/3/2 | 2/9 | **8/9** | 6/9 |
| **all** | L2: 1/15 | L2: **10/15** | 19/45 | **30/45** | 21/45 |

Sweep `results/roof-fix-2026-08/` (aggregated `paper/`), image
`openstudio-mcp:roof-fix-2026-08` (046142d6fc79), harness `61675a6`, all 15
legs pass `scripts/benchmark_check_leg.py` (detector's permanent home now).

### Three findings

1. **The affordance fix works wherever the model actually sees the tool.**
   Codex loads all schemas up front: both GPT tiers went from 0/6 to 6/6 on
   L1+L2 via the new tool, mini 2/9 -> 8/9 overall. Opus (which searches
   thoroughly) hit 9/9. This is F3/F9's discovery-regime split, reproduced on
   a product fix instead of an ablation.
2. **Under deferred tool search, sonnet/haiku never load the new schema at
   L2/L3** — they select the familiar triple by exact name from prior
   knowledge, so both the new tool and the description steering are invisible
   to them, and their totals are unchanged. The fix's remaining gap is not the
   tool, it is tool DISCOVERY for mid/small tiers (same lever as F3's
   nodiscovery arms; a nodiscovery re-run would likely close it — untested).
3. **Response-time warnings lose to plan momentum; L3 prompts lose to
   compliance.** The v1 legs proved warnings in tool responses go unread when
   agents batch calls. And L3 ("Use create_standard_opaque_material, then
   create_construction, then assign...") prescribes the anti-pattern verbatim:
   post-fix L3 is still 6/15 because compliant agents follow it and only
   strong models preserve the original layers while complying. L2's wording
   ("create ... and assign") pushes the same way, which makes the 1/15 -> 10/15
   L2 jump the cleanest measure of the fix.

### Success criterion vs plan

Plan target: L2/L3 >80% for sonnet/opus, R-decrease signature gone. Opus:
100% (met). Sonnet: 33% (NOT met — finding 2). The R-decrease signature is
gone from every row where the new tool was used (21/45) and from all codex
L2 rows; it persists in sonnet/haiku L2/L3 replacement rows. Do NOT cite this
as "fixed everywhere"; cite the L2 line and the discovery-regime split.

### Data hygiene

- `results/roof-fix-2026-08/_invalid/` — 2 v1 sonnet legs (different image),
  keep for the selection-time-vs-response-time evidence; never pool.
- `_meta/` holds `sweep_meta.json` + copied preflight (aggregator hygiene).
- Anthropic spend $6.80 total (9 sweep legs $5.51 + 2 quarantined v1 legs
  $1.31, rounding); codex legs on subscription ($0 recorded).
