# §3.2 rewrite — DRAFT v2 for iteration (do not touch the .docx)

Replaces the submitted §3.2 prose + Table 4 entirely. The 2026-03-28 sweep
numbers (88.9/94.4/94.4, 180 tasks) are routing-era and are dropped per the
superseded-claims register; never compared against the new numbers.

Style rules applied in v2: opens with motivation (what is benchmarked and
why), academic register, no em-dashes, "versus" spelled out, % throughout.

Reviewer mapping: motivation + scoring (R2-Q1/Q2, R3-C3) -> paras 1-2;
repeats/CI (R1, R2-Q3, R3-C3) -> para 2 + Table 4; model independence
(R1, R2-Q3) -> paras 3-4; ablation (R1, R2-Q4) -> para 4; simpler baseline
(R1) -> para 5; domain validity (R1, R2-Q7) -> para 2 (artifact facts).

---

## Proposed text (~590 words prose)

**3.2 LLM agent benchmark**

The demonstration in Section 3.1 establishes that an agent can drive the
server; it does not establish reliability. The practical question for
deployment is whether an LLM agent can select the correct tools from a
catalog of more than 150, chain them into multi-step modeling workflows,
and produce models that are physically correct, and how much of that
ability comes from the server's assistance layers (the knowledge-skill
tools and deferred tool discovery) rather than from the model itself. The
benchmark therefore measures task completion of the combined agent and
server system on a fixed set of difficult BEM tasks, across five models
from two vendors, under controlled ablations of each assistance layer, and
against an unscaffolded baseline in which the same agents script the SDK
directly with no server at all.

Each task is scored by two deterministic gates. Gate 1 (routing) checks
that the agent called a tool from the task's accept set and that the first
such call succeeded. Gate 2 (outcome) inspects the artifact the agent
saved: the model is reloaded offline and physical facts, such as assembly
R-values, HVAC loop membership, and EnergyPlus results compared with
pinned references, are checked against a versioned rubric. No LLM judging
is involved; scoring consists of deterministic assertions over recorded
facts and can be re-scored after the fact without re-running an agent
(implementation in `tests/llm/grading/`). Each cell of the test matrix
comprises 18 tasks: two model-construction setup tasks and 16 tasks across
six operation families, each posed at up to three prompt-specificity
levels, from L1 (a vague goal) to L3 (the tool named explicitly). Every
cell is run three times with retries disabled, against one pinned Docker
image and harness commit. Table 4 reports pooled pass rates with Wilson
95% intervals over attempted tasks; tasks skipped because a prerequisite
failed are excluded rather than counted as failures.

Routing and outcome disagree, and the disagreement grows as the model gets
smaller. Within the Claude tiers, routing pass is nearly flat (96.3, 96.3,
and 83.3% for Opus, Sonnet, and Haiku) while outcome pass separates the
tiers by more than 30 points (92.6, 81.5, and 61.1%; gaps of 3.7, 14.8,
and 22.2 points). The same direction holds for the OpenAI models (GPT-5.4
gap 14.8, GPT-5.4-mini 18.5). Measure authoring provides the sharpest
instance: Haiku routed eight of nine attempts to the correct tool but
produced a working measure in only two. Tool-selection accuracy alone,
which is what routing-only evaluations report, would have concealed nearly
all of this failure.

Ablations locate the dominant assistance-layer effect in tool discovery
rather than the knowledge layer. Loading all tool schemas up front instead
of using deferred tool search raises outcome pass by 16.7 points for Haiku
and by 5.5 points for both Sonnet and Opus; doubling the wall-clock budget
changes nothing (timeouts fall from eight to zero while the pass rate is
unchanged), which rules out time pressure as the mechanism. Removing the
knowledge-skill layer costs GPT-5.4, the only model that consults it
heavily (1.83 skill reads per task), 5.6 points, and has no effect on
models that never consult it. Because the Codex CLI loads all schemas
natively, the cross-vendor comparison is made in that matched regime:
Sonnet 87.0 versus GPT-5.4 81.5%, and Haiku 77.8 versus GPT-5.4-mini
74.1%, with fewer agent turns (7.8 versus 10.5). With discovery and skills
both removed, Opus reaches 98.1% with a routing-outcome gap of zero.

A final baseline addresses whether the tool layer is needed at all. The
same agents receive shell access to a container holding the OpenStudio
SDK, CLI, and EnergyPlus, with no MCP server, and must script every
operation. On six outcome-graded tasks, Sonnet completed 13 of 18 trials
and GPT-5.4 15 of 18: inspection, modification, simulation, and format
conversion largely succeed, but constructing a model from scratch exceeded
the time budget in two of three Sonnet trials, and an exact log-parsing
task failed for both models in all six trials. The tool layer's
contribution is concentrated in model creation and exactness rather than
in raw capability.

**Configuration note (end of section):** The per-task wall-clock budget is
120 s; a 240 s control arm is included in the archived data. The Codex CLI
lacks a system-prompt option, so the system prompt is prepended to the
user prompt. Exact model identifiers, arm definitions, and per-leg
provenance are published with the archived benchmark data.

---

## Proposed Table 4 (replaces the tier table)

Table 4. Outcome-graded pass rates (Wilson 95% CI) versus routing-only
pass, 18 tasks x 3 repeats per cell, over attempted tasks.

| Model | Assistance arm | Outcome pass | Routing pass |
|---|---|---|---|
| Opus 4.6 | full | 92.6% [82.4, 97.1] | 96.3% |
| Opus 4.6 | no tool search | 98.1% [90.2, 99.7] | 100.0% |
| Opus 4.6 | no search, no skills | 98.1% [90.2, 99.7] | 98.1% |
| Sonnet 4.6 | full | 81.5% [69.2, 89.6] | 96.3% |
| Sonnet 4.6 | no tool search | 87.0% [75.6, 93.6] | 90.7% |
| Sonnet 4.6 | no skills | 74.1% [61.1, 83.9] | 87.0% |
| Haiku 4.5 | full | 61.1% [47.8, 73.0] | 83.3% |
| Haiku 4.5 | no tool search | 77.8% [65.1, 86.8] | 92.6% |
| Haiku 4.5 | no skills | 62.5% [48.4, 74.8] | 79.2% |
| GPT-5.4 | full (native schema load) | 81.5% [69.2, 89.6] | 96.3% |
| GPT-5.4 | no skills | 75.9% [63.1, 85.4] | 96.3% |
| GPT-5.4-mini | full (native schema load) | 74.1% [61.1, 83.9] | 92.6% |
| GPT-5.4-mini | no skills | 77.8% [65.1, 86.8] | 96.3% |

(Haiku no-skills denominator is 48 attempted; one leg's failed setup
cascaded six skips, and skips are excluded rather than failed. Opus
no-skills 83.3% [71.3, 91.0] and the nohost arms exist in the archive;
trimmed here for space.)

## Figure 4 v2 (BUILT — review images)

- `paper/figures/fig4_benchmark_v2.png` / `.svg` — (a) routing (hatched)
  versus outcome (solid) per model with Wilson CIs and the gap annotated;
  (b) outcome pass by prompt level L1/L2/L3, full arm.
- `paper/figures/table4_v2.png` — Table 4 rendered for review (adds an n
  column; Haiku no-skills n=48 is visible there).
- Rebuild with `python paper/build_fig4_v2.py`; all numbers are computed
  live from `results/prod-2026-08b/*.json`, never hand-typed.

Proposed caption: "Figure 4. Agent benchmark, full configuration: (a)
routing-gate versus outcome-graded pass rates per model (Wilson 95%
intervals on outcome; the annotated gap is the share of runs that called
the right tools but produced a wrong artifact); (b) outcome-graded pass by
prompt-specificity level."

## What was deliberately left out

- Defect-discovery framing (F7 roof affordance, extract_eui units) as a
  contribution, per the 2026-08-10 ruling. The generalizable residue is in
  paras 3-4 (routing-only grading hides failure; discovery-regime effects).
- Old 180-task routing-era rates (superseded-claims register).
- Cost/token economics (F5); one sentence can be added if wanted, and
  behavior.md now carries $/test CLI + derived columns.
- t240, nohost, and sonnet/haiku nodiscovery-noskills cells: archived,
  cited as control arms in the archived data.

## Known grading boundaries (state honestly, do not overclaim)

- "HVAC loop membership" in para 2 refers to the add_hvac (System 7) case,
  where gate 2 checks zones-on-air-loops and the presence of hot-water +
  chilled-water plant loops. It is accurate for that case. Do NOT imply the
  four-pipe-beam MEASURE case grades full coil-to-plant wiring: rubric 1.2
  grades beam terminal type/count and air-loop reconnection but not each
  beam's coil->plant-loop connection (deferred to rubric 2.0, needs a re-run
  to populate the fact). If a reviewer probes measure-case wiring, say this
  plainly rather than widening the claim.
- Rubric was hardened to 1.2 after the PR#126 review (per-surface roof
  criterion instead of an average; EMS requires the setback on all 10 zones).
  Re-scoring the recorded facts under 1.2 changed zero of 391 roof+EMS
  verdicts, so every number above is stable across the tightening — a point
  worth one sentence if the methodology is questioned.
