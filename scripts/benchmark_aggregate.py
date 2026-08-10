"""Aggregate benchmark sweep results into paper artifacts.

Reads results/<sweep_id>/*.json (written by scripts/benchmark_sweep.py),
pools repeats per (model, arm, tier), and emits under results/<sweep_id>/paper/:

  table4.md        pass rates ± Wilson 95% CI per model/arm/tier
  ablation.md      full vs noskills side-by-side per tier (models present in both)
  discovery.csv    progressive L1/L2/L3 pass rates per model/arm
  stability.md     tasks passing 0<k<N repeats (the honest "these flip" table)
  failure_modes.md failure-mode counts per model/arm
  behavior.md      per model/arm means: knowledge calls, ToolSearch, tool calls,
                   duration, tokens — the ablation *mechanism* evidence
  flips.md         paired full-vs-noskills discordant tasks per model
                   (skill-lift / skill-drag) — where the knowledge layer acts
  outcome.md       gate-2 outcome grading per model/arm/case: routing-passed
                   vs outcome-passed and the mismatch gap

Refuses to merge files whose run_config image identity differs (paper runs
must all come from one pinned artifact) — override with --ignore-digest.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

# The D3 ablation removes exactly these tools; counting their use per arm
# shows the consultation/substitution mechanism, not just pass-rate deltas
KNOWLEDGE_TOOLS = ("list_skills", "get_skill", "recommend_tools")

# List prices per Mtok (input, output, cache_read), checked 2026-08-10.
# opus-4-6 $15/$75 refuted against data: derived would EXCEED CLI-reported,
# impossible while cache writes are missing from the derivation.
PRICES = {
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),
    "claude-haiku-4-5-20251001": (1.00, 5.00, 0.10),
    "claude-opus-4-6": (5.00, 25.00, 0.50),
    "gpt-5.4": (2.50, 15.00, 0.25),
    "gpt-5.4-mini": (0.75, 4.50, 0.075),
}
# codex reports input_tokens INCLUDING cached reads; claude's excludes them
CODEX_INPUT_INCLUDES_CACHED = ("gpt-",)


def derived_cost_usd(model: str, inp: int, out: int, cache_read: int) -> float | None:
    """Cost from recorded tokens at list prices; None for unknown models.

    Claude cache WRITES (1.25x input) are not recorded per test, so claude
    derived cost understates CLI-reported by ~40-60% — behavior.md carries
    both columns and says so. Codex CLI reports cost_usd=0 (subscription);
    derived is the only cross-vendor dollar figure for it.
    """
    prices = PRICES.get(model)
    if prices is None:
        return None
    pi, po, pc = prices
    uncached = inp - cache_read if model.startswith(CODEX_INPUT_INCLUDES_CACHED) else inp
    return (uncached * pi + out * po + cache_read * pc) / 1e6


def wilson(s: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for s successes of n trials."""
    if n == 0:
        return (0.0, 0.0)
    p = s / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def _case_level(test_id: str) -> tuple[str, str] | None:
    """('thermostat', 'L2') from a progressive test id, else None."""
    if "[" not in test_id:
        return None
    short = test_id.rsplit("[", maxsplit=1)[-1].rstrip("]")
    case, _, level = short.rpartition("_")
    if level in ("L1", "L2", "L3") and case:
        return case, level
    return None


def load_results(sweep_dir: Path, ignore_digest: bool,
                 ignore_harness: bool = False) -> list[dict]:
    files = sorted(p for p in sweep_dir.glob("*.json")
                   if p.name != "sweep_meta.json")
    if not files:
        sys.exit(f"No result files in {sweep_dir}")
    runs = []
    identities = set()
    harnesses = set()
    missing_git = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        rc = data.get("run_config", {})
        identities.add((rc.get("image"), rc.get("image_id")))
        git = rc.get("git")
        harnesses.add(git)
        if not git:
            missing_git.append(f.name)
        data["_file"] = f.name
        runs.append(data)
    if len(identities) > 1 and not ignore_digest:
        sys.exit(f"ABORT: mixed image identities across results: {identities} "
                 "— a paper sweep must use one pinned artifact "
                 "(--ignore-digest to override).")
    # The image pins the SERVER code; the grading rubric and test set live in
    # the harness (host-mounted), so legs graded by different harness commits
    # are not comparable even at one image. Reject missing provenance outright.
    if missing_git and not ignore_harness:
        sys.exit(f"ABORT: {len(missing_git)} leg(s) lack run_config.git "
                 f"provenance: {missing_git[:5]} — cannot verify the grading "
                 "harness (--ignore-harness to override).")
    if len(harnesses) > 1 and not ignore_harness:
        sys.exit(f"ABORT: mixed harness commits across results: "
                 f"{sorted(str(h) for h in harnesses)} — the rubric/test set "
                 "may differ between legs (--ignore-harness to override, e.g. "
                 "when the commits differ only in docs).")
    return runs


def _key(run: dict) -> tuple[str, str]:
    rc = run.get("run_config", {})
    return (run.get("model", "?"), rc.get("arm", "full"))


def aggregate(runs: list[dict]) -> dict:
    """Pool trials into the structures every artifact below renders from."""
    tiers = defaultdict(lambda: {"s": 0, "n": 0})        # (model, arm, tier)
    tasks = defaultdict(list)                             # (model, arm, test) -> [bool]
    levels = defaultdict(lambda: {"s": 0, "n": 0})       # (model, arm, level)
    modes = defaultdict(int)                              # (model, arm, mode)
    repeats = defaultdict(int)                            # (model, arm)
    behav = defaultdict(lambda: {"tests": 0, "knowledge": 0, "toolsearch": 0,
                                 "tool_calls": 0, "duration_s": 0.0,
                                 "input_tokens": 0, "output_tokens": 0,
                                 "cache_read_tokens": 0, "cost_usd": 0.0,
                                 "host_calls": 0, "escapes": 0})
    skips = defaultdict(int)                              # (model, arm)
    outcome_pool = defaultdict(lambda: {"graded": 0, "outcome_pass": 0,
                                        "ungradable": 0})  # (model, arm, case)

    for run in runs:
        model, arm = _key(run)
        repeats[(model, arm)] += 1
        for t in run.get("tests", []):
            # Skipped trials (unmet dependency, agent never invoked) are not
            # failures — excluded from every pool, surfaced as a footnote
            if t.get("skipped"):
                skips[(model, arm)] += 1
                continue
            passed = bool(t.get("passed"))
            b = behav[(model, arm)]
            b["tests"] += 1
            b["knowledge"] += sum(1 for c in t.get("tool_calls", [])
                                  if c in KNOWLEDGE_TOOLS)
            b["toolsearch"] += t.get("toolsearch_count", 0)
            b["tool_calls"] += t.get("num_tool_calls", 0)
            b["duration_s"] += t.get("duration_s", 0.0)
            b["input_tokens"] += t.get("input_tokens", 0)
            b["output_tokens"] += t.get("output_tokens", 0)
            b["cache_read_tokens"] += t.get("cache_read_tokens", 0)
            b["cost_usd"] += t.get("cost_usd", 0.0)
            b["host_calls"] += t.get("host_tool_call_count", 0)
            # Escape (F8): the trial used host tools without a single MCP call
            if (t.get("num_tool_calls", 0) == 0
                    and t.get("host_tool_call_count", 0) > 0):
                b["escapes"] += 1
            tiers[(model, arm, t.get("tier", "?"))]["s"] += int(passed)
            tiers[(model, arm, t.get("tier", "?"))]["n"] += 1
            tasks[(model, arm, t["test_id"])].append(passed)
            cl = _case_level(t["test_id"]) if t.get("tier") == "progressive" else None
            if cl:
                levels[(model, arm, cl[1])]["s"] += int(passed)
                levels[(model, arm, cl[1])]["n"] += 1
            if not passed:
                mode = t.get("failure_mode", "unknown")
                # Subclassify no_mcp_tool: escaped to host tools vs produced
                # text only — distinguishable from host_tool_call_count
                if mode == "no_mcp_tool":
                    sub = ("escape" if t.get("host_tool_call_count", 0) > 0
                           else "text-only")
                    mode += f"[{sub}]"
                # First-call-strict verdicts where a later accepted-tool call
                # succeeded — reported separately so strictness is visible
                if t.get("recovered"):
                    mode += " (recovered)"
                modes[(model, arm, mode)] += 1
            # Gate-2 pool: rows that reached outcome grading (routing passed).
            # Recovered rows carry facts but keep their tool_error verdict —
            # excluded here; raw facts stay in benchmark.json for analysis.
            o = t.get("outcome")
            if o is not None and (passed or
                                  t.get("failure_mode") == "outcome_mismatch"):
                case = (cl[0] if cl else t["test_id"].split("::")[-1])
                oc = outcome_pool[(model, arm, case)]
                oc["graded"] += 1
                oc["outcome_pass"] += int(bool(o.get("outcome_pass")))
                if any(str(r).startswith("ungradable")
                       for r in o.get("reasons", [])):
                    oc["ungradable"] += 1

    unstable = {}
    for (model, arm, test_id), outcomes in tasks.items():
        k, n = sum(outcomes), len(outcomes)
        if 0 < k < n:
            unstable[(model, arm, test_id)] = (k, n)

    return {"tiers": dict(tiers), "levels": dict(levels), "modes": dict(modes),
            "unstable": unstable, "repeats": dict(repeats),
            "behavior": dict(behav), "tasks": dict(tasks), "skips": dict(skips),
            "outcomes": dict(outcome_pool)}


def _pct_ci(s: int, n: int) -> str:
    if n == 0:
        return "—"
    lo, hi = wilson(s, n)
    return f"{s / n * 100:.1f}% [{lo * 100:.1f}, {hi * 100:.1f}] ({s}/{n})"


def write_artifacts(agg: dict, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)

    combos = sorted({(m, a) for (m, a, _t) in agg["tiers"]})
    tier_names = sorted({t for (_m, _a, t) in agg["tiers"]})

    lines = ["# Pass rates ± Wilson 95% CI (pooled trials: tasks x repeats)", "",
             "| Model | Arm | " + " | ".join(tier_names) + " |",
             "|" + "---|" * (2 + len(tier_names))]
    escaped_combos = []
    for model, arm in combos:
        cells = []
        for t in tier_names:
            c = agg["tiers"].get((model, arm, t), {"s": 0, "n": 0})
            cells.append(_pct_ci(c["s"], c["n"]))
        esc = agg["behavior"].get((model, arm), {}).get("escapes", 0)
        mark = ""
        if esc:
            mark = " \\*"
            escaped_combos.append((model, arm, esc))
        lines.append(f"| {model} | {arm}{mark} | " + " | ".join(cells) + " |")
    if escaped_combos:
        lines += ["", "\\* includes escape trials (zero MCP calls, host tools "
                      "used instead):"]
        for model, arm, esc in escaped_combos:
            lines.append(f"- {model}/{arm}: {esc}")
    if agg["skips"]:
        lines += ["", "Skipped trials (unmet dependency, excluded from rates):"]
        for (model, arm), n in sorted(agg["skips"].items()):
            lines.append(f"- {model}/{arm}: {n}")
    (out / "table4.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    models_both = sorted({m for (m, a) in combos if a == "full"}
                         & {m for (m, a) in combos if a == "noskills"})
    lines = ["# Knowledge-layer ablation (full vs noskills)", ""]
    for model in models_both:
        lines += [f"## {model}", "", "| Tier | full | noskills |", "|---|---|---|"]
        for t in tier_names:
            f_ = agg["tiers"].get((model, "full", t))
            n_ = agg["tiers"].get((model, "noskills", t))
            if not (f_ or n_):
                continue
            fc = _pct_ci(f_["s"], f_["n"]) if f_ else "—"
            nc = _pct_ci(n_["s"], n_["n"]) if n_ else "—"
            lines.append(f"| {t} | {fc} | {nc} |")
        lines.append("")
    if not models_both:
        lines.append("(no model present in both arms)")
    (out / "ablation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# Agent behavior — means per test, per model/arm", "",
             "| Model | Arm | Tests | Knowledge calls | ToolSearch | Tool calls "
             "| Host calls | Escapes | Duration s | Input tok | Output tok "
             "| $/test CLI | $/test derived |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for (model, arm), b in sorted(agg["behavior"].items()):
        n = b["tests"] or 1
        dc = derived_cost_usd(model, b["input_tokens"], b["output_tokens"],
                              b["cache_read_tokens"])
        dc_cell = f"{dc / n:.3f}" if dc is not None else "—"
        lines.append(
            f"| {model} | {arm} | {b['tests']} | {b['knowledge'] / n:.2f} "
            f"| {b['toolsearch'] / n:.2f} | {b['tool_calls'] / n:.2f} "
            f"| {b['host_calls'] / n:.2f} | {b['escapes']} "
            f"| {b['duration_s'] / n:.1f} | {b['input_tokens'] / n:.0f} "
            f"| {b['output_tokens'] / n:.0f} | {b['cost_usd'] / n:.3f} "
            f"| {dc_cell} |")
    lines += ["",
              "$/test CLI: as reported by the agent CLI (codex reports 0 — "
              "subscription).",
              "$/test derived: recorded tokens x list prices (PRICES in "
              "benchmark_aggregate.py). Codex input_tokens includes cached "
              "reads (subtracted before pricing); claude cache WRITES are "
              "unrecorded, so claude derived understates CLI-reported by "
              "~40-60% — compare vendors on derived, claude tiers on CLI."]
    (out / "behavior.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# Paired task flips — full vs noskills discordance per model", "",
             "| Model | Task | full | noskills | Direction |",
             "|---|---|---|---|---|"]
    n_flips = 0
    for model in models_both:
        per_task = defaultdict(dict)
        for (m, arm, test_id), outcomes in agg["tasks"].items():
            if m == model and arm in ("full", "noskills"):
                per_task[test_id][arm] = (sum(outcomes), len(outcomes))
        for test_id, by_arm in sorted(per_task.items()):
            if "full" not in by_arm or "noskills" not in by_arm:
                continue
            (fk, fn), (nk, nn) = by_arm["full"], by_arm["noskills"]
            if fk / fn == nk / nn:
                continue
            n_flips += 1
            direction = "skill-lift" if fk / fn > nk / nn else "skill-drag"
            short = test_id.split("::")[-1]
            lines.append(f"| {model} | {short} | {fk}/{fn} | {nk}/{nn} "
                         f"| {direction} |")
    if not n_flips:
        lines.append("| (no discordant tasks) | | | | |")
    (out / "flips.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (out / "discovery.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["model", "arm", "level", "passed", "total", "rate",
                    "wilson_lo", "wilson_hi"])
        for (model, arm, level), c in sorted(agg["levels"].items()):
            lo, hi = wilson(c["s"], c["n"])
            rate = c["s"] / c["n"] if c["n"] else 0.0
            w.writerow([model, arm, level, c["s"], c["n"],
                        f"{rate:.4f}", f"{lo:.4f}", f"{hi:.4f}"])

    lines = ["# Task stability — tasks that flip across repeats (0 < k < N)", "",
             "| Model | Arm | Test | Passed |", "|---|---|---|---|"]
    for (model, arm, test_id), (k, n) in sorted(agg["unstable"].items()):
        lines.append(f"| {model} | {arm} | {test_id} | {k}/{n} |")
    if not agg["unstable"]:
        lines.append("| (none) | | | |")
    (out / "stability.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# Outcome grading (gate 2) — routing-passed rows only", "",
             "Routing pass = accepted tool called + first call ok. Outcome",
             "pass = the artifact did the job (rubric v1 over recorded facts;",
             "re-scorable post-hoc — plan-outcome-grading.md). Mismatch is the",
             "routing-passed-but-wrong-artifact gap per model/arm/case.", "",
             "| Model | Arm | Case | Routing-passed | Outcome-passed "
             "| Mismatch | Ungradable |",
             "|---|---|---|---|---|---|---|"]
    for (model, arm, case), c in sorted(agg["outcomes"].items()):
        lines.append(
            f"| {model} | {arm} | {case} | {c['graded']} "
            f"| {c['outcome_pass']} | {c['graded'] - c['outcome_pass']} "
            f"| {c['ungradable']} |")
    if not agg["outcomes"]:
        lines.append("| (no graded rows) | | | | | | |")
    (out / "outcome.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# Failure modes per model/arm", "",
             "| Model | Arm | Mode | Count |", "|---|---|---|---|"]
    for (model, arm, mode), count in sorted(agg["modes"].items(),
                                            key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {model} | {arm} | {mode} | {count} |")
    if not agg["modes"]:
        lines.append("| (no failures) | | | |")
    (out / "failure_modes.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sweep_dir", help="results/<sweep_id> directory")
    ap.add_argument("--out", default=None,
                    help="output dir (default <sweep_dir>/paper)")
    ap.add_argument("--ignore-digest", action="store_true",
                    help="pool legs built from different Docker images")
    ap.add_argument("--ignore-harness", action="store_true",
                    help="pool legs from different harness commits (use only "
                         "when the commits differ in docs, not rubric/tests)")
    args = ap.parse_args()

    sweep_dir = Path(args.sweep_dir)
    runs = load_results(sweep_dir, args.ignore_digest, args.ignore_harness)
    agg = aggregate(runs)
    out = Path(args.out) if args.out else sweep_dir / "paper"
    write_artifacts(agg, out)
    print(f"Aggregated {len(runs)} result file(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
