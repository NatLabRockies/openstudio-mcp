"""Leg contamination detector — flags rate-limit-corrupted benchmark rows.

When the CLI fails hard, runner.py raises before recording per-test
metrics. Two observed signatures:

A. Carried-over metrics (HTTP 429 mid-stream): the row inherits the
   PREVIOUS test's cost/tokens/tool list and is misclassified wrong_tool.
   Tiny pytest wall-clock (duration_s) paired with a large carried-over
   CLI duration_ms. Found 1 bad leg in 48 during prod-2026-08b.
B. No metrics at all (subscription usage cap / hard CLI rc=1): the CLI
   returns an error message for every call, so the failed row has
   num_turns/duration_ms/cost all None and failure_mode None. Found 9
   bad legs in opus48-v1.2.1 (session limit), which signature A missed.

Zero false positives across the 75-leg paper-v1.2.1 collection — run after
EVERY leg; quarantine flagged legs to results/<sweep>/_invalid/ and re-run.

Usage:
  python scripts/benchmark_check_leg.py results/<sweep>/<leg>.json [...]
  python scripts/benchmark_check_leg.py results/<sweep>   # checks all legs

Exit 1 if any row is flagged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def suspicious_rows(leg: dict) -> list[dict]:
    flagged = []
    for row in leg.get("tests", []):
        if row.get("skipped"):
            continue
        if row.get("passed"):
            continue
        duration_s = row.get("duration_s") or 0
        duration_ms = row.get("duration_ms") or 0
        # Signature A — carried-over CLI metrics from the previous test;
        # Signature B — CLI errored before any metrics were recorded
        if (duration_s < 15 and duration_ms / 1000 > 2 * duration_s) or (
                row.get("num_turns") is None
                and row.get("duration_ms") is None):
            flagged.append(row)
    return flagged


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    paths: list[Path] = []
    for arg in sys.argv[1:]:
        p = Path(arg)
        if p.is_dir():
            # legs only — _meta/ and _invalid/ subdirs are excluded by glob
            paths.extend(sorted(p.glob("*.json")))
        else:
            paths.append(p)

    bad = 0
    for path in paths:
        leg = json.loads(path.read_text(encoding="utf-8"))
        if "tests" not in leg:
            print(f"[skip] {path} — no 'tests' key (not a leg file)")
            continue
        flagged = suspicious_rows(leg)
        if flagged:
            bad += 1
            print(f"[BAD ] {path}")
            for row in flagged:
                print(f"        {row['test_id']}: duration_s={row['duration_s']} "
                      f"duration_ms={row.get('duration_ms')} — likely API-error "
                      f"contamination, quarantine this leg and re-run")
        else:
            print(f"[ok  ] {path}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
