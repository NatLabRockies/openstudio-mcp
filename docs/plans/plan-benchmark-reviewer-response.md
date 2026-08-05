# Plan: Benchmark work for SoftwareX reviewer response

Status: IN PROGRESS (decisions resolved 2026-08-05; see bottom)
Depends on: `docs/plans/plan-llm-benchmark-realism.md` (branch `feat/llm-benchmark-realism`, phases 0-3 = prereq)
Companion: `paper/revision-plan-2026-07.md` (WS-2)

## Issues addressed (from paper/reviewer_feedback.txt)

| ID | Issue | Design section |
|---|---|---|
| B1 | Claude-only; "LLM families" claim unsupported | D4 cross-provider backend |
| B2 | Single run, no variance/CI | D2 repeats + Wilson CI |
| B3 | No knowledge-layer ablation | D3 ablation arm |
| B4 | Not run on immutable artifact | D5 artifact pinning |
| B5 | Pass criteria/scoring undefined | D1 assertion depth + D7 taxonomy |
| B6 | No domain-validity checks | D6 post-hoc verifier |
| B7 | EP-MCP shared-task comparison | D8 (decision-gated) |
| B8 | Metric definitions | D9 formulas |
| B9 | Counts must match artifact | D5 tool-table export |

Non-negotiable honesty rule for all paper runs: `LLM_TESTS_RETRIES=0` (retries mask stochasticity; repeats replace them).

---

## D1. Pass-criteria depth (prereq = realism phases 0-3)

Already designed in `plan-llm-benchmark-realism.md`; not redesigned here. What this plan consumes from it:

- `ClaudeResult.tool_results` — pair assistant `tool_use.id` → `tool_result` content from user messages (JSON-parse text blocks, tolerate non-JSON):

```python
@property
def tool_results(self) -> dict[str, dict]:
    """tool_use id -> parsed tool_result JSON (or {'_raw': text})."""

def tool_ok(self, name: str) -> bool | None:
    """ok flag of FIRST call to `name`; None if never called."""
```

- Progressive pass becomes: expected tool called AND `tool_ok(tool) is not False` AND (where defined) `expected_args` match.
- Workflow/e2e pass gains pinned-reference EUI asserts (rel=0.05).
- Phases 4-7 (goal/clarify/recovery/units tiers) NOT required for the revision — decision-gated.

## D2. Repeats + confidence intervals (B2)

Orchestrate repeats OUTSIDE pytest — each repeat is a full pytest invocation with a fresh `LLM_TESTS_RUNS_DIR` (fresh setup models each repeat = independent trials; suite code untouched).

New `scripts/benchmark_sweep.py` (host-side, stdlib only, no openstudio import):

```python
# CLI: python scripts/benchmark_sweep.py --sweep-id paper-v1 \
#        --model sonnet:claude --model gpt-5:codex --arms full,noskills \
#        --repeats 3 --pytest-args "-m progressive" --image openstudio-mcp:v1.2.0
def main():
    meta = preflight(image)   # git describe --tags; docker image inspect digest;
                              # ABORT if tree dirty (--allow-dirty overrides),
                              # ABORT if LLM_TESTS_RETRIES set nonzero
    for model, provider in models:
        for arm in arms:
            for r in range(1, repeats + 1):
                env = os.environ | {
                    "LLM_TESTS_ENABLED": "1", "LLM_TESTS_RETRIES": "0",
                    "LLM_TESTS_MODEL": model, "LLM_TESTS_PROVIDER": provider,
                    "LLM_TESTS_ARM": arm, "LLM_TESTS_IMAGE": image,
                    "LLM_TESTS_RUNS_DIR": str(runs_root / f"{model}_{arm}_r{r}"),
                    "LLM_TESTS_RUN_META": json.dumps(meta | {"repeat": r}),
                }
                subprocess.run(["pytest", *pytest_args], env=env)  # never raises
                copy(benchmark.json -> results/<sweep_id>/<model>_<arm>_r<r>.json)
```

`tests/llm/conftest.py` change (one block): `summary["run_config"] = json.loads(os.environ.get("LLM_TESTS_RUN_META", "{}")) | {"provider": ..., "arm": ..., "retries": MAX_RETRIES}`.

New `scripts/benchmark_aggregate.py` — reads `results/<sweep_id>/*.json`, emits paper artifacts:

```python
def wilson(s: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0: return (0.0, 0.0)
    p = s / n; d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (c - h, c + h)
```

N=3 repeats for first paper run; +2 more MAY be added later — aggregator must merge late-added `_r4/_r5` files into existing sweep dirs without rerun (per-repeat files already support this; assert only digest match, never repeat count).

Reporting per (model, arm, tier): pooled trials `s=Σpasses, n=tasks×repeats` → mean ± Wilson 95%; PLUS task-stability list (tasks passing 0<k<N repeats — the honest "these flip" table). Outputs: `paper/table4.md`, `ablation.md`, `discovery.csv` (L1/L2/L3 per model/arm), `stability.md`, `failure_modes.md`.

Unit tests (CI, no LLM): `tests/test_benchmark_aggregate.py` — Wilson math exact values, aggregation over synthetic benchmark.json fixtures, stability detection. Add to lightest ci.yml shard.

## D3. Ablation arm (B3)

**Mechanism: server-side, not client-side.** `--disallowedTools` would leave the tools visible in the listing (refusals contaminate behavior). Instead the knowledge layer is truly absent:

`mcp_server/skills/__init__.py`:

```python
# Knowledge-layer modules; excluded when OSMCP_DISABLE_KNOWLEDGE_SKILLS=1
# (benchmark ablation arm — see docs/plans/plan-benchmark-reviewer-response.md)
_KNOWLEDGE_SKILLS = {"skill_discovery", "tool_router"}

def register_all_skills(mcp) -> list[str]:
    ablate = os.environ.get("OSMCP_DISABLE_KNOWLEDGE_SKILLS") == "1"
    for importer, modname, ispkg in pkgutil.iter_modules(package.__path__):
        if ablate and modname in _KNOWLEDGE_SKILLS:
            continue
        ...
```

Removes exactly: `list_skills`, `get_skill` (skill_discovery) + `recommend_tools` (tool_router). Everything else identical — same image, same system prompt, same task prompts.

Runner plumbing: when `LLM_TESTS_ARM=noskills`, `_write_mcp_config()` adds `-e OSMCP_DISABLE_KNOWLEDGE_SKILLS=1` to the docker args.

Integration test (mandatory per repo rules, ci.yml lightest shard):

```python
@pytest.mark.integration
def test_knowledge_skills_ablation_flag():
    # Validates: OSMCP_DISABLE_KNOWLEDGE_SKILLS=1 removes exactly the 3 knowledge-layer
    # tools (benchmark ablation arm); default env keeps full roster
    # session started with env → list_tools: list_skills/get_skill/recommend_tools absent,
    # e.g. create_new_building present; count == len(EXPECTED_TOOLS) - 3
```

Ablation scope (arms compared on identical subsets): progressive L1+L2 (`-m progressive -k "not _L3"`) + NL tier (`tests/llm/test_03_eval_cases.py`) + workflow tiers (`test_04`, `test_07`, `test_08` chains — DECIDED IN; this makes D6 verifier wiring mandatory, since workflow grading under ablation relies on outcome checks). L3 excluded by design (tool named → knowledge layer irrelevant). Known leakage to acknowledge in paper: other tools' descriptions may mention skills; system prompt held constant.

Ablation runs on BOTH providers (decided 2026-08-05 after pilot-1): pilot data showed knowledge-layer usage is a client property — codex consulted list_skills/get_skill on 12/16 tasks (no client-side discovery), while Claude Code made 0-1 knowledge calls but 23-26 ToolSearch calls (its own discovery substitutes). The codex ablation is therefore the higher-signal experiment; the paper frames knowledge-layer value as conditional on client discovery affordances.

Arm C ("simpler baseline", R1) — DECIDED BUILD: no MCP config at all; `allowed_tools="Bash,Read,Write,Edit,Glob,Grep"`; prompt directs agent to a long-lived `docker exec` shell in the same image; ~10-15 task subset; graded by D6 verifier only.

## D4. Cross-provider backend (B1)

`tests/llm/runner.py` refactor — backend seam, existing behavior unchanged:

```python
class AgentResult:            # rename of ClaudeResult; alias kept
    # normalized: messages -> tool_calls/tool_results, final_text,
    # usage fields nullable (cost_usd -> float | None; conftest sums `or 0`)

def run_agent(prompt, *, model=None, timeout=120, allowed_tools=..., 
              system_prompt=None, max_turns=None) -> AgentResult:
    provider = os.environ.get("LLM_TESTS_PROVIDER", "claude")
    return _BACKENDS[provider](...)   # claude | codex | gemini

run_claude = ...  # thin wrapper over run_agent(provider="claude") for compat
```

Adapters:
- `_run_claude` — existing code, unchanged.
- `_run_codex` — DECIDED provider — `codex exec --json` with temp `CODEX_HOME/config.toml` declaring `[mcp_servers.openstudio]` (same docker command as `_write_mcp_config`); parse JSONL events → tool calls (`mcp_tool_call` items) + final message; no `--system-prompt` equivalent → system prompt PREPENDED to the user prompt; recorded in run_config and footnoted in paper.
- `_run_gemini` — NOT for revision (codex chosen); seam allows adding later.

**SPIKE-1 (before adapter buildout):** run 3 progressive cases through codex CLI manually; confirm (a) MCP-over-docker-stdio works, (b) tool calls extractable, (c) non-interactive full-auto flag exists. If codex can't expose tool calls, completion-only grading via D6 verifier is the fallback (still answers B1 for workflow tiers).

Unit tests: `tests/test_llm_runner_backends.py` — parse recorded NDJSON/JSONL fixtures per backend (no network, no openstudio import); assert normalized AgentResult fields. CI lightest shard.

## D5. Artifact pinning + counts (B4, B9)

- `_write_mcp_config()`: image name from `LLM_TESTS_IMAGE` (default `openstudio-mcp:dev`).
- Sweep preflight records: git tag/SHA, image tag + digest → `run_config` in every benchmark.json; aggregator refuses to merge files with mismatched digests.
- Paper runs: build image from the tagged release commit (`docker build -t openstudio-mcp:v1.2.0 .`), Zenodo-archive the same commit.
- New `scripts/export_tool_table.py`: runs INSIDE the container at the tag; imports the server, groups registered tools by skill module, cross-checks the total against `EXPECTED_TOOLS`; emits Table 1 md + counts JSON. One counting rule everywhere: `len(EXPECTED_TOOLS)` at the archived tag. Unit-testable mapping logic factored out.

## D6. Post-hoc domain-validity verifier (B6)

New `tests/llm/verify.py` — deterministic non-LLM verification, independent of agent claims (mirrors the integration-test client pattern; same image + same `/runs` volume):

```python
def verify_run(run_id: str, *, image: str, runs_dir: str) -> dict:
    """Direct MCP stdio session (no agent): extract_summary_metrics +
    run_qaqc_checks + extract_simulation_errors for run_id.
    Returns {completed, fatal, severe, eui, unmet_heating, unmet_cooling, qaqc}."""

def assert_sim_valid(v: dict, *, eui_ref: float | None = None,
                     rel: float = 0.05, max_unmet: float = 300.0):
    # 0 fatal / 0 severe; unmet <= max_unmet; EUI within rel of pinned ref
```

MANDATORY (was optional): workflow-tier ablation (D3) and Arm C grading both depend on it. Wired into workflow/e2e tiers (`test_04`, `test_07`, `test_08` chains) after the agent finishes. This is the sentence the paper gets to write: "a workflow pass requires successful EnergyPlus termination and outputs verified within tolerance by a separate non-LLM client." Progressive single-tool cases keep D1 asserts (no run produced). Explicit paper scope-limit: compliance/zoning/design-review NOT checked.

## D7. Failure taxonomy (B5)

Extend conftest's 3 modes (`wrong_tool`, `no_mcp_tool`, `timeout`) with `tool_error` (expected tool called, ok:false), `wrong_args`, `outcome_mismatch` (D6/EUI asserts failed). Mechanism: assertion helpers tag the test before failing —

```python
def fail_with_mode(request, mode: str, msg: str):
    request.node.user_properties.append(("failure_mode", mode))
    pytest.fail(msg)
# conftest.pytest_runtest_logreport: read report.user_properties first,
# fall back to existing _last_result heuristics
```

Aggregator emits `failure_modes.md` (counts per model/arm) → paper's failure-categorization sentence + response to R2.

## D8. EP-MCP shared-task comparison (B7) — DECIDED BUILD

`scripts/epmcp_compare/` — ~10 intersection tasks (load IDF/OSM, inspect zones, modify setpoint/schedule, run sim, extract end uses), both servers driven by the SAME provider backend (D4), metrics = completion, tool calls, tokens, wall-clock. EP-MCP from its public repo, pinned commit. Grading: completion + D6-style output checks where both produce runs. Kept out of `tests/` (not part of our suite; one-off study dir with its own README). Fallback if EP-MCP proves unrunnable after a timeboxed setup spike (SPIKE-2, ~half day): response-letter rationale + feature-level Table 5.

## D9. Metric definitions (B8) — paper + docs text

- **Tool-discovery accuracy** (per level ℓ ∈ {L1,L2,L3}): fraction of progressive operations where the agent's session at level ℓ calls any tool from the case's accepted set. Discovery failure = never reaches an accepted tool.
- **Task-completion accuracy** (per tier): fraction of tasks where ALL assertions pass — accepted tool called, its result `ok: true`, argument checks (where defined), and outcome checks (D6, where a run is produced).
- Relationship: discovery is a necessary condition for completion; completion failures partition by D7 taxonomy into discovery (`wrong_tool`/`no_mcp_tool`), use (`wrong_args`/`tool_error`), and outcome (`outcome_mismatch`) failures.
- Scoring is 100% deterministic pytest assertions (no human, no LLM judge); implementation public in `tests/llm/`.

Docs: rewrite `docs/testing/llm-testing-methodology.md` metric section; new comparability epoch noted in `docs/testing/llm-test-benchmark.md`.

## Run matrix (paper numbers; all on v1.2.0 image, retries=0)

| Arm | Provider/model | Scope | Repeats | ~Prompts |
|---|---|---|---|---|
| full | claude/sonnet | full suite | 3 | ~540-660 |
| full | claude/haiku | progressive | 3 | ~230-300 |
| full | claude/opus | progressive | 3 | ~230-300 |
| full | codex (gpt-5.4) | progressive | 3 | ~230-300 |
| noskills | claude/sonnet | progressive L1/L2 + NL + workflows | 3 | ~290-380 |
| noskills | codex (gpt-5.4) | progressive L1/L2 + NL + workflows | 3 | ~290-380 |
| codegen (Arm C) | claude/sonnet | 10-15 subset | 3 | ~30-45 |
| epmcp-compare (D8) | both servers, 1 provider | ~10 tasks | 3 | ~60 |

Total ~1,600-2,100 prompts, ~20-30 h wall (sequential, overnight), rough $200-450 API. Repeats may later extend to N=5 for arms with wide CIs (aggregator merges `_r4/_r5` without rerunning r1-r3). Post-trim counts depend on realism Phase 2/3 landing.

## Sequencing (commit-sized steps, on feat/llm-benchmark-realism)

1. Realism phases 0-3 (existing plan; own commits). Phases 4-7 SKIPPED for revision.
2. Runner: AgentResult + tool_results/tool_ok + LLM_TESTS_IMAGE + arm plumbing; conftest run_config + taxonomy hooks. Unit tests.
3. Server ablation flag + integration test (+ ci.yml shard entry).
4. Sweep + aggregator scripts + unit tests.
5. D6 verifier wiring (mandatory — workflow ablation + Arm C grading depend on it).
6. SPIKE-1 → codex adapter + fixture tests.
7. Arm C codegen harness (10-15 task subset).
8. SPIKE-2 (EP-MCP runnable?) → D8 study dir.
9. Merge → tag v1.2.0 → build image → run matrix → aggregate → paper tables.

## Decisions (resolved 2026-08-05)

1. Non-Anthropic provider: **codex** (GPT-5.x). Gemini seam kept, not built.
2. Repeats: **N=3** now; may extend to 5 later — aggregator merges added repeats.
3. Arm C codegen baseline: **build**.
4. D8 EP-MCP comparison: **build** (SPIKE-2 timebox; fallback decline-in-letter).
5. Realism phases 4-7: **skip** — reviewer issues only.
6. Ablation scope: **includes workflow tiers** (makes D6 mandatory).
