"""Build the 600s-budget merged benchmark dataset (censored-row substitution).

A 120s-timeout row is a CENSORED observation: the run did not finish, so
we know it was slow, not that it was wrong. Rows that completed under the
cap (pass or graded fail) are valid observations under any larger budget.
This builder merges each base sweep with its 600s rerun sweep:

  kept row         passed, or failed with is_timeout falsy -> copied
                   unchanged, `exceeded_120s: false`.
  substituted row  failed AND is_timeout -> replaced by the 600s rerun row
                   at the same (model, arm, task, repeat), OUTCOME-BLIND:
                   the rerun's verdict stands even if it failed grading or
                   timed out again (`exceeded_600s: true`). Cherry-picking
                   in either direction is p-hacking.
  missing rerun    original timeout kept, `substitution_missing: true`,
                   reported loudly; exit 1 unless --allow-missing.

Source legs are NEVER edited (run_config signs them). Derived legs keep
the base leg's run_config so the aggregator pools them, plus a `derived`
block naming both source sweeps. Also emits MERGE_MANIFEST.md (every
substitution: cell, old->new duration and verdict) and LATENCY.md
(>120s count, share of rows, median substituted duration per model).

Usage:
  python scripts/benchmark_build_t600_dataset.py --out results/paper-v1.2.1-merged \
    --pair results/paper-v1.2.1=results/paper-v1.2.1-t600fix \
    --pair <worktree>/results/opus48-v1.2.1=<worktree>/results/opus48-v1.2.1-t600
"""
from __future__ import annotations

import argparse
import copy
import json
import statistics
import sys
from pathlib import Path


def _task(test_id: str) -> str:
    """'measure_replace_terminals_L1' from a progressive id, else the raw id."""
    if "[" in test_id:
        return test_id.rsplit("[", maxsplit=1)[-1].rstrip("]")
    return test_id.rsplit("::", maxsplit=1)[-1]


def _recount(leg: dict) -> None:
    """Recompute leg-level summaries from rows (harness convention:
    passed + failed == total_tests; pass_rate over all rows)."""
    rows = leg["tests"]
    n_pass = sum(1 for r in rows if r.get("passed"))
    n_skip = sum(1 for r in rows if r.get("skipped"))
    leg["total_tests"] = len(rows)
    leg["passed"] = n_pass
    leg["failed"] = len(rows) - n_pass - n_skip
    leg["pass_rate"] = round(n_pass / len(rows) * 100, 1) if rows else 0.0
    tiers: dict = {}
    for r in rows:
        if r.get("skipped"):
            continue
        t = tiers.setdefault(r.get("tier", "?"),
                             {"total": 0, "passed": 0, "duration_s": 0.0})
        t["total"] += 1
        t["passed"] += int(bool(r.get("passed")))
        t["duration_s"] += r.get("duration_s") or 0.0
    for t in tiers.values():
        t["duration_s"] = round(t["duration_s"], 1)
        t["pass_rate"] = round(t["passed"] / t["total"] * 100, 1)
    leg["tiers"] = tiers
    for key, field in (("total_duration_s", "duration_s"),
                       ("total_input_tokens", "input_tokens"),
                       ("total_output_tokens", "output_tokens"),
                       ("total_cache_read_tokens", "cache_read_tokens"),
                       ("total_cost_usd", "cost_usd")):
        total = sum(r.get(field) or 0 for r in rows if not r.get("skipped"))
        leg[key] = round(total, 4) if isinstance(total, float) else total


def merge_leg(base_leg: dict, rerun_leg: dict | None,
              pair_label: str) -> tuple[dict, list[dict], list[str], list[str]]:
    """Apply the substitution rules to one leg. Pure — no filesystem.

    Returns (derived_leg, substitutions, problems, warnings). Problems are
    data gaps (missing rerun row — nonzero exit); warnings are informational
    (passed-but-timed-out rows kept with a latency flag; 5 exist in the
    opus48 collection: artifact complete and graded pass, CLI killed at the
    cap mid-summary). Each substitution dict: model/arm/repeat/task/
    old_duration_s/new_duration_s/old/new verdicts.
    """
    rerun_rows = {}
    if rerun_leg is not None:
        for r in rerun_leg["tests"]:
            if not r.get("skipped"):
                rerun_rows[r["test_id"]] = r

    derived = copy.deepcopy(base_leg)
    rc = derived.get("run_config", {})
    model, arm, rep = derived.get("model", "?"), rc.get("arm", "?"), rc.get("repeat", 0)
    subs: list[dict] = []
    problems: list[str] = []
    warnings: list[str] = []
    out_rows = []
    for row in derived["tests"]:
        if row.get("skipped"):
            out_rows.append(row)
            continue
        cell = f"{model}/{arm}/r{rep}/{_task(row['test_id'])}"
        if row.get("passed") or not row.get("is_timeout"):
            if row.get("passed") and row.get("is_timeout"):
                # Passed despite hitting the cap: artifact was complete when
                # the CLI was killed. A valid pass at any budget — keep it,
                # but it DID need >120s, so it carries the latency flag.
                row["exceeded_120s"] = True
                warnings.append(f"WARN passed-but-timeout kept: {cell}")
            else:
                row["exceeded_120s"] = False
            out_rows.append(row)
            continue
        # failed AND is_timeout — censored; substitute outcome-blind
        rerun = rerun_rows.get(row["test_id"])
        if rerun is None:
            row["exceeded_120s"] = True
            row["substitution_missing"] = True
            problems.append(f"MISSING rerun row: {cell} ({pair_label})")
            out_rows.append(row)
            continue
        new = copy.deepcopy(rerun)
        new["substituted_t600"] = True
        new["original_duration_s"] = row.get("duration_s")
        new["exceeded_120s"] = True
        if not new.get("passed") and new.get("is_timeout"):
            new["exceeded_600s"] = True
        out_rows.append(new)
        subs.append({
            "model": model, "arm": arm, "repeat": rep,
            "task": _task(row["test_id"]),
            "old_duration_s": row.get("duration_s"),
            "new_duration_s": new.get("duration_s"),
            "old": "timeout@120s",
            "new": ("pass" if new.get("passed")
                    else "timeout@600s" if new.get("exceeded_600s")
                    else new.get("failure_mode") or "fail"),
        })
    derived["tests"] = out_rows
    _recount(derived)
    derived["derived"] = {
        "builder": "benchmark_build_t600_dataset.py",
        "sources": pair_label,
        "budget_s": 600,
        "substituted": len(subs),
    }
    return derived, subs, problems, warnings


def latency_stats(legs: list[dict]) -> dict:
    """Per-model: >120s row count, share of non-skipped rows, median
    substituted duration — the three latency metrics the paper reports."""
    per: dict = {}
    for leg in legs:
        m = per.setdefault(leg.get("model", "?"),
                           {"rows": 0, "exceeded_120s": 0, "sub_durations": []})
        for r in leg["tests"]:
            if r.get("skipped"):
                continue
            m["rows"] += 1
            if r.get("exceeded_120s"):
                m["exceeded_120s"] += 1
            if r.get("substituted_t600"):
                m["sub_durations"].append(r.get("duration_s") or 0.0)
    for m in per.values():
        m["share_pct"] = round(m["exceeded_120s"] / m["rows"] * 100, 1)
        m["median_sub_duration_s"] = (
            round(statistics.median(m["sub_durations"]), 1)
            if m["sub_durations"] else None)
        del m["sub_durations"]
    return per


def _write_reports(out: Path, legs: list[dict], subs: list[dict]) -> None:
    lines = ["# Merge manifest — 120s timeout rows substituted by 600s reruns",
             "", "Outcome-blind rule: every substitution recorded here kept the",
             "rerun verdict, pass or fail. Kept rows are not listed.", "",
             "| Model | Arm | r | Task | Old dur s | New dur s | Old | New |",
             "|---|---|---|---|---|---|---|---|"]
    for s in sorted(subs, key=lambda s: (s["model"], s["arm"], s["repeat"], s["task"])):
        lines.append(f"| {s['model']} | {s['arm']} | {s['repeat']} | {s['task']} "
                     f"| {s['old_duration_s']} | {s['new_duration_s']} "
                     f"| {s['old']} | {s['new']} |")
    lines += ["", f"Total substitutions: {len(subs)}"]
    (out / "MERGE_MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    lines = ["# Latency — tasks needing more than 120 s (reported instead of",
             "timeout failures; correctness is graded at the 600 s budget)", "",
             "| Model | Rows | >120s rows | Share % | Median substituted dur s |",
             "|---|---|---|---|---|"]
    for model, m in sorted(latency_stats(legs).items()):
        med = m["median_sub_duration_s"]
        lines.append(f"| {model} | {m['rows']} | {m['exceeded_120s']} "
                     f"| {m['share_pct']} | {med if med is not None else '—'} |")
    (out / "LATENCY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pair", action="append", required=True,
                    metavar="BASE_DIR=RERUN_DIR",
                    help="base sweep dir = its 600s rerun sweep dir (repeatable)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--allow-missing", action="store_true",
                    help="exit 0 even when a timeout row has no rerun row")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    all_legs, all_subs, all_problems, all_warnings = [], [], [], []
    identities = set()
    for pair in args.pair:
        base_s, sep, rerun_s = pair.rpartition("=")
        if not sep:
            sys.exit(f"--pair must be BASE_DIR=RERUN_DIR, got: {pair}")
        base_dir, rerun_dir = Path(base_s), Path(rerun_s)
        label = f"{base_dir.name} + {rerun_dir.name}"
        for f in sorted(base_dir.glob("*.json")):
            if f.name == "sweep_meta.json":
                continue
            base_leg = json.loads(f.read_text(encoding="utf-8"))
            rerun_path = rerun_dir / f.name
            rerun_leg = (json.loads(rerun_path.read_text(encoding="utf-8"))
                         if rerun_path.exists() else None)
            derived, subs, problems, warnings = merge_leg(base_leg, rerun_leg,
                                                          label)
            if len(derived["tests"]) != len(base_leg["tests"]):
                sys.exit(f"BUG: row count changed for {f.name}")
            rc = derived.get("run_config", {})
            identities.add((rc.get("git"), rc.get("image_id")))
            (out / f.name).write_text(json.dumps(derived, indent=1),
                                      encoding="utf-8")
            all_legs.append(derived)
            all_subs.extend(subs)
            all_problems.extend(problems)
            all_warnings.extend(warnings)
            print(f"[leg ] {f.name}: {len(subs)} substituted"
                  + (f", {len(problems)} problem(s)" if problems else ""))
    if len(identities) > 1:
        sys.exit(f"ABORT: mixed provenance across merged legs: {identities}")
    _write_reports(out, all_legs, all_subs)
    print(f"Merged {len(all_legs)} leg(s), {len(all_subs)} substitution(s) "
          f"-> {out}")
    for w in all_warnings:
        print(w)
    for p in all_problems:
        print(p)
    if all_problems and not args.allow_missing:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
