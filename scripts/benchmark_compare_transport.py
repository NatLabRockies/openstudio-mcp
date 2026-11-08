"""Pair stdio and HTTP benchmark legs test by test and report the differences.

One run per test cannot separate a transport effect from model randomness, so
each disagreement is listed for rerun and --rerun-* sweeps are tallied per test.

Usage:
  python scripts/benchmark_compare_transport.py results/<stdio> results/<http> \
      [--fix-http results/<z>] [--rerun-stdio results/<x> --rerun-http results/<y>] \
      [--out report.md] [--discordant discordant.json]
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path


def load_legs(sweep: Path) -> dict[str, list[dict]]:
    """model -> legs; ignores _invalid, _meta and sweep_meta.json."""
    legs: dict[str, list[dict]] = {}
    for path in sorted(sweep.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if "tests" in data:
            legs.setdefault(data["model"], []).append(data)
    return legs


def leg_arm(*groups: dict[str, list[dict]]) -> str:
    """The one arm every leg in every group ran under; ValueError when they differ.

    Pass/fail rates across arms (full vs noskills) differ for reasons that have
    nothing to do with transport, so a comparison must never mix them.
    """
    arms = {leg.get("run_config", {}).get("arm", "full")
            for legs in groups for model_legs in legs.values() for leg in model_legs}
    if len(arms) > 1:
        raise ValueError(f"legs mix arms {sorted(arms)}; compare one arm at a time")
    return arms.pop() if arms else "full"


def apply_fix(legs: dict[str, list[dict]], fixes: dict[str, list[dict]]) -> list[str]:
    """Swap each leg's rows for its fix leg's rows, whatever those rows show.

    Outcome-blind on purpose, as in the t600 merge: every test the fix leg ran
    is replaced, so a fix rerun cannot selectively improve a score. Setup rows
    only rebuild fixtures and are kept. Returns the replaced test ids.
    """
    replaced: set[str] = set()
    for model, fix_legs in fixes.items():
        fixed = {r["test_id"]: r for r in fix_legs[0]["tests"]
                 if "test_01_setup" not in r["test_id"]}
        for leg in legs.get(model, []):
            leg["tests"] = [
                fixed[r["test_id"]] | {"substituted_fix": True}
                if r["test_id"] in fixed else r for r in leg["tests"]]
        replaced |= set(fixed)
    return sorted(replaced)


def rows_by_test(leg: dict) -> dict[str, dict]:
    return {r["test_id"]: r for r in leg["tests"]}


def _ran(row: dict | None) -> bool:
    return row is not None and not row.get("skipped")


def classify(stdio: dict | None, http: dict | None) -> str:
    """One pair's bucket; a test that ran on one side only is never a pass/fail diff."""
    if not _ran(stdio) or not _ran(http):
        if not _ran(stdio) and not _ran(http):
            return "both_skipped"
        return "ran_on_one_side"
    if stdio["passed"] and http["passed"]:
        return "both_pass"
    if not stdio["passed"] and not http["passed"]:
        return "both_fail"
    return "stdio_only_pass" if stdio["passed"] else "http_only_pass"


def compare(stdio_leg: dict, http_leg: dict) -> dict:
    a, b = rows_by_test(stdio_leg), rows_by_test(http_leg)
    pairs = {t: classify(a.get(t), b.get(t)) for t in sorted(set(a) | set(b))}
    return {"counts": Counter(pairs.values()), "pairs": pairs}


def discordant(pairs: dict[str, str]) -> list[str]:
    """Tests worth rerunning: passed on one side, or ran on one side only."""
    return [t for t, c in pairs.items()
            if c in ("stdio_only_pass", "http_only_pass", "ran_on_one_side")]


def tally_reruns(legs: list[dict], tests: list[str]) -> dict[str, tuple[int, int]]:
    """test -> (passes, runs) across rerun legs."""
    out = {}
    for test in tests:
        rows = [r for leg in legs if _ran(r := rows_by_test(leg).get(test))]
        out[test] = (sum(1 for r in rows if r["passed"]), len(rows))
    return out


def verdict(stdio: tuple[int, int], http: tuple[int, int]) -> str:
    """A difference stands only if reruns split cleanly the same way."""
    (sp, sn), (hp, hn) = stdio, http
    if not sn or not hn:
        return "no reruns"
    if sp == sn and hp == 0:
        return "confirmed: fails on HTTP"
    if hp == hn and sp == 0:
        return "confirmed: fails on stdio"
    return "noise" if sp and hp else "unclear"


def _median(rows: list[dict], key: str, scale: float = 1.0) -> float | None:
    values = [r[key] * scale for r in rows if isinstance(r.get(key), (int, float))]
    return round(statistics.median(values), 3) if values else None


def _sum(rows: list[dict], key: str) -> float:
    return sum(r[key] for r in rows if isinstance(r.get(key), (int, float)))


def leg_summary(leg: dict) -> dict:
    """Pass rate plus effort. Time is CLI duration_ms: duration_s includes cap waits."""
    rows = [r for r in leg["tests"] if _ran(r)]
    passed = sum(1 for r in rows if r["passed"])
    return {
        "ran": len(rows), "passed": passed,
        "rate": round(100 * passed / len(rows), 1) if rows else 0.0,
        "median_s": _median(rows, "duration_ms", 0.001),
        "median_tool_calls": _median(rows, "num_tool_calls"),
        "median_turns": _median(rows, "num_turns"),
        "cost_usd": round(_sum(rows, "cost_usd"), 2),
        "timeouts": sum(1 for r in rows if r.get("is_timeout")),
        "failure_modes": dict(Counter(
            r.get("failure_mode") or "unknown" for r in rows if not r["passed"])),
    }


def render(stdio: dict, http: dict, rerun_stdio: dict, rerun_http: dict) -> tuple[str, dict]:
    lines = ["## Results by model", "",
             "| Model | Transport | Passed | Rate | Median s | Median tool calls "
             "| Median turns | Cost | Timeouts |",
             "|---|---|---|---|---|---|---|---|---|"]
    detail: list[str] = []
    to_rerun: dict[str, list[str]] = {}
    for model in sorted(set(stdio) & set(http)):
        s_leg, h_leg = stdio[model][0], http[model][0]
        for name, leg in (("stdio", s_leg), ("HTTP", h_leg)):
            m = leg_summary(leg)
            lines.append(
                f"| {model} | {name} | {m['passed']}/{m['ran']} | {m['rate']}% "
                f"| {m['median_s']} | {m['median_tool_calls']} | {m['median_turns']} "
                f"| ${m['cost_usd']} | {m['timeouts']} |")
        result = compare(s_leg, h_leg)
        tests = discordant(result["pairs"])
        to_rerun[model] = tests
        counts = result["counts"]
        detail += ["", f"### {model}", "",
                   f"Both pass {counts['both_pass']}, both fail {counts['both_fail']}, "
                   f"stdio only {counts['stdio_only_pass']}, "
                   f"HTTP only {counts['http_only_pass']}, "
                   f"ran on one side {counts['ran_on_one_side']}."]
        if tests:
            s_tally = tally_reruns(rerun_stdio.get(model, []), tests)
            h_tally = tally_reruns(rerun_http.get(model, []), tests)
            detail += ["", "| Test | First run | Reruns stdio | Reruns HTTP | Verdict |",
                       "|---|---|---|---|---|"]
            for t in tests:
                sp, sn = s_tally[t]
                hp, hn = h_tally[t]
                detail.append(f"| `{t.split('::')[-1]}` | {result['pairs'][t]} "
                              f"| {sp}/{sn} | {hp}/{hn} "
                              f"| {verdict((sp, sn), (hp, hn))} |")
    lines += ["", "## Differences", *detail, ""]
    return "\n".join(lines), to_rerun


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stdio", type=Path)
    ap.add_argument("http", type=Path)
    ap.add_argument("--fix-http", type=Path, help="sweep whose rows replace HTTP rows")
    ap.add_argument("--rerun-stdio", type=Path)
    ap.add_argument("--rerun-http", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--discordant", type=Path, help="write model -> tests JSON")
    args = ap.parse_args()

    http_legs = load_legs(args.http)
    if args.fix_http:
        apply_fix(http_legs, load_legs(args.fix_http))
    stdio_legs = load_legs(args.stdio)
    rerun_stdio = load_legs(args.rerun_stdio) if args.rerun_stdio else {}
    rerun_http = load_legs(args.rerun_http) if args.rerun_http else {}
    try:
        leg_arm(stdio_legs, http_legs, rerun_stdio, rerun_http)
    except ValueError as e:
        return f"ABORT: {e}"
    text, to_rerun = render(stdio_legs, http_legs, rerun_stdio, rerun_http)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.discordant:
        args.discordant.write_text(json.dumps(to_rerun, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
