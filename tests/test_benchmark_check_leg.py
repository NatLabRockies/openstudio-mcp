"""Unit tests for scripts/benchmark_check_leg.py — contamination signatures.
Stdlib only, no openstudio import.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_check_leg import suspicious_rows

pytestmark = pytest.mark.unit

PROG = "tests/llm/test_06_progressive.py::test_progressive"


def _row(**kw):
    base = {"test_id": f"{PROG}[roof_insulation_L1]", "passed": False,
            "tier": "progressive"}
    base.update(kw)
    return base


def test_carried_over_metrics_signature_flagged():
    # Regression: 429-contaminated rows inherit the previous test's CLI
    # duration_ms while pytest wall-clock is tiny (prod-2026-08b bad leg)
    leg = {"tests": [_row(duration_s=3.0, duration_ms=120000,
                          num_turns=7, cost_usd=0.2)]}
    assert len(suspicious_rows(leg)) == 1


def test_usage_cap_rows_with_no_cli_metrics_flagged():
    # Regression: opus48-v1.2.1 sweep hit the subscription session limit;
    # runner raised RuntimeError before recording metrics, so rows carried
    # failure_mode=None and NO num_turns/duration_ms/cost — check_leg
    # passed all 9 garbage legs (exit 0) and they polluted the aggregate
    leg = {"tests": [
        _row(duration_s=4.7, duration_ms=None, num_turns=None,
             cost_usd=None, output_tokens=None, failure_mode=None),
    ]}
    flagged = suspicious_rows(leg)
    assert len(flagged) == 1, (
        "hard CLI failure (rate limit / usage cap) row must be flagged"
    )


def test_recorded_failure_rows_not_flagged():
    # Validates: genuine graded failures carry CLI metrics and must NOT be
    # flagged — zero false positives across the 75-leg paper-v1.2.1 rerun
    leg = {"tests": [
        _row(duration_s=45.0, duration_ms=41000, num_turns=9,
             cost_usd=0.21, output_tokens=1500,
             failure_mode="outcome_mismatch"),
        _row(test_id=f"{PROG}[add_hvac_L1]", passed=True, duration_s=30.0,
             duration_ms=28000, num_turns=6, cost_usd=0.1,
             output_tokens=900),
    ]}
    assert suspicious_rows(leg) == []


def test_skipped_rows_ignored():
    # Validates: prerequisite-skip rows have no metrics by design and are
    # not contamination
    leg = {"tests": [_row(skipped=True, duration_s=0.0, duration_ms=None,
                          num_turns=None)]}
    assert suspicious_rows(leg) == []
