"""Unit tests for scripts/benchmark_build_t600_dataset.py — the censored-row
substitution rules behind the 600s-budget merged dataset. Stdlib only.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_build_t600_dataset import latency_stats, merge_leg

pytestmark = pytest.mark.unit

PROG = "tests/llm/test_06_progressive.py::test_progressive"


def _row(task="measure_replace_terminals_L1", **kw):
    base = {"test_id": f"{PROG}[{task}]", "passed": True, "is_timeout": False,
            "tier": "progressive", "duration_s": 60.0, "duration_ms": 55000,
            "num_turns": 8, "cost_usd": 0.2, "input_tokens": 10,
            "output_tokens": 900, "cache_read_tokens": 1000}
    base.update(kw)
    return base


def _leg(rows, model="claude-sonnet-4-6", arm="full", repeat=1):
    return {"model": model, "tests": rows,
            "run_config": {"git": "v1.2.1", "image_id": "sha256:eff",
                           "arm": arm, "repeat": repeat,
                           "timeout_base": 120}}


def test_completed_rows_kept_unchanged():
    # Validates: passes AND graded failures completed under 120s are valid
    # observations at any larger budget — never re-run, never substituted
    base = _leg([_row(), _row(task="roof_insulation_L2", passed=False,
                              failure_mode="outcome_mismatch")])
    rerun = _leg([_row(passed=False, failure_mode="wrong_tool"),
                  _row(task="roof_insulation_L2", passed=True)])
    derived, subs, problems, warnings = merge_leg(base, rerun, "t")
    assert subs == [] and problems == [] and warnings == []
    assert derived["tests"][0]["passed"] is True
    assert derived["tests"][1]["failure_mode"] == "outcome_mismatch"
    assert all(r["exceeded_120s"] is False for r in derived["tests"])
    assert "substituted_t600" not in derived["tests"][0]


def test_passed_but_timed_out_row_kept_with_latency_flag():
    # Regression: 5 rows in the opus48-v1.2.1 collection are passed=True AND
    # is_timeout=True (artifact complete and graded pass, CLI killed at the
    # cap) — they must be KEPT (valid pass at any budget), latency-flagged,
    # and reported as a warning, not a data-gap problem (exit stays 0)
    base = _leg([_row(passed=True, is_timeout=True, duration_s=120.4)])
    rerun = _leg([_row(passed=False, failure_mode="wrong_tool")])
    derived, subs, problems, warnings = merge_leg(base, rerun, "t")
    row = derived["tests"][0]
    assert row["passed"] is True
    assert row["exceeded_120s"] is True
    assert "substituted_t600" not in row
    assert subs == [] and problems == []
    assert len(warnings) == 1 and "passed-but-timeout" in warnings[0]


def test_timeout_row_substituted_outcome_blind():
    # Validates: THE rule — a timed-out row takes its 600s rerun verdict even
    # when the rerun FAILED grading; keeping the better row is p-hacking
    base = _leg([_row(passed=False, is_timeout=True, duration_s=120.2,
                      num_turns=0, cost_usd=0.0)])
    rerun = _leg([_row(passed=False, is_timeout=False, duration_s=310.0,
                       failure_mode="outcome_mismatch", cost_usd=0.5)])
    derived, subs, problems, warnings = merge_leg(base, rerun, "t")
    assert warnings == []
    row = derived["tests"][0]
    assert row["passed"] is False
    assert row["failure_mode"] == "outcome_mismatch"
    assert row["substituted_t600"] is True
    assert row["exceeded_120s"] is True
    assert row["original_duration_s"] == pytest.approx(120.2)
    assert row["duration_s"] == pytest.approx(310.0)
    assert "exceeded_600s" not in row
    assert len(subs) == 1 and problems == []
    assert subs[0]["old"] == "timeout@120s" and subs[0]["new"] == "outcome_mismatch"


def test_rerun_timeout_at_600_stays_a_failure():
    # Validates: a row still hitting the 600s ceiling IS a correctness
    # failure in the merged set, flagged exceeded_600s
    base = _leg([_row(passed=False, is_timeout=True, duration_s=120.1)])
    rerun = _leg([_row(passed=False, is_timeout=True, duration_s=600.3)])
    derived, subs, _, _ = merge_leg(base, rerun, "t")
    row = derived["tests"][0]
    assert row["passed"] is False and row["exceeded_600s"] is True
    assert subs[0]["new"] == "timeout@600s"


def test_missing_rerun_row_keeps_original_and_reports():
    # Validates: a rerun gap keeps the original timeout failure and is
    # reported loudly (builder exits nonzero without --allow-missing)
    base = _leg([_row(passed=False, is_timeout=True, duration_s=120.0)])
    rerun = _leg([_row(task="python_ems_control_L2", passed=True)])
    derived, subs, problems, warnings = merge_leg(base, rerun, "t")
    assert warnings == []
    row = derived["tests"][0]
    assert row["passed"] is False and row["substitution_missing"] is True
    assert row["exceeded_120s"] is True
    assert subs == []
    assert len(problems) == 1 and "measure_replace_terminals_L1" in problems[0]


def test_summary_recounted_after_substitution():
    # Validates: leg-level pass counts/rate/cost reflect the substituted
    # rows (harness convention passed+failed==total, rate over all rows)
    base = _leg([_row(cost_usd=0.2),
                 _row(task="python_ems_control_L2", passed=False,
                      is_timeout=True, duration_s=120.0, cost_usd=0.0)])
    rerun = _leg([_row(task="python_ems_control_L2", passed=True,
                       duration_s=250.0, cost_usd=0.6)])
    derived, _, _, _ = merge_leg(base, rerun, "t")
    assert derived["passed"] == 2 and derived["failed"] == 0
    assert derived["total_tests"] == 2
    assert derived["pass_rate"] == pytest.approx(100.0)
    assert derived["total_cost_usd"] == pytest.approx(0.8)
    assert derived["tiers"]["progressive"]["passed"] == 2
    assert derived["derived"]["substituted"] == 1


def test_latency_stats_three_metrics():
    # Validates: the paper's three latency metrics — >120s count, share of
    # rows, median substituted duration — computed per model
    base = _leg([_row(),
                 _row(task="python_ems_control_L2", passed=False,
                      is_timeout=True, duration_s=120.0),
                 _row(task="python_ems_control_L3", passed=False,
                      is_timeout=True, duration_s=120.0)])
    rerun = _leg([_row(task="python_ems_control_L2", passed=True,
                       duration_s=200.0),
                  _row(task="python_ems_control_L3", passed=True,
                       duration_s=400.0)])
    derived, _, _, _ = merge_leg(base, rerun, "t")
    stats = latency_stats([derived])
    m = stats["claude-sonnet-4-6"]
    assert m["rows"] == 3 and m["exceeded_120s"] == 2
    assert m["share_pct"] == pytest.approx(66.7)
    assert m["median_sub_duration_s"] == pytest.approx(300.0)
