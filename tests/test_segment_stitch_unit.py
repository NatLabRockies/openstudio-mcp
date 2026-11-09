"""stitch_segment_results: summing time-segment results (parallel-annual skill, issue #247)."""
import json
import sys

import pytest

from mcp_server.skills.results import segments

pytestmark = pytest.mark.unit


def _seg(days: dict[str, float], monthly: dict, peaks: dict) -> dict:
    keys = sorted(days)
    return {
        "keep_begin": keys[0], "keep_end": keys[-1], "kept_days": len(keys),
        "daily_electricity_kwh": days, "monthly_end_uses_kwh": monthly,
        "monthly_peak_electricity_w": peaks,
    }


# Segment A keeps Jan 30-31, segment B keeps Feb 1-2 (passed out of order on purpose).
SEG_A = _seg({"01-30": 10.0, "01-31": 12.0},
             {"01": {"Electricity": {"Total": 22.0, "Heating": 5.0}, "NaturalGas": {"Total": 3.0}}},
             {"01": 900.0})
SEG_B = _seg({"02-01": 20.0, "02-02": 30.0},
             {"02": {"Electricity": {"Total": 50.0, "Heating": 8.0}}},
             {"02": 1500.0})


def test_stitch_sums_months_and_keeps_peak_max():
    # Validates: monthly energy sums across segments, annual = sum of months per fuel/end use,
    # peak demand is the max (never a sum), and segment order does not matter
    r = segments.stitch([SEG_B, SEG_A])
    assert r["ok"] is True, r
    assert (r["first_day"], r["last_day"], r["kept_days"], r["segment_count"]) == ("01-30", "02-02", 4, 2)
    assert r["annual_electricity_kwh"] == pytest.approx(72.0, abs=1e-9)
    assert r["annual_end_uses_kwh"] == {
        "Electricity": {"Total": pytest.approx(72.0), "Heating": pytest.approx(13.0)},
        "NaturalGas": {"Total": pytest.approx(3.0)},
    }
    assert r["monthly_peak_electricity_w"] == {"01": 900.0, "02": 1500.0}
    assert "reference_check" not in r


def test_month_split_across_segments_is_summed_and_peak_is_max():
    # Validates: two segments sharing a month (e.g. 24 half-month segments) add their energy and
    # keep the higher of their two peaks for that month
    a = _seg({"03-01": 1.0}, {"03": {"Electricity": {"Total": 1.0}}}, {"03": 700.0})
    b = _seg({"03-02": 2.0}, {"03": {"Electricity": {"Total": 2.0}}}, {"03": 650.0})
    r = segments.stitch([a, b])
    assert r["monthly_end_uses_kwh"]["03"]["Electricity"]["Total"] == pytest.approx(3.0, abs=1e-9)
    assert r["monthly_peak_electricity_w"]["03"] == pytest.approx(700.0, abs=1e-9)


def test_overlapping_segments_are_refused():
    # Validates: a day kept by two segments would be double counted, so stitching fails and names it
    dup = _seg({"01-31": 12.0, "02-01": 1.0}, {"02": {"Electricity": {"Total": 1.0}}}, {})
    r = segments.stitch([SEG_A, dup])
    assert r["ok"] is False
    assert "overlap" in r["error"]
    assert r["overlapping_days"] == ["01-31"]


def test_missing_days_are_refused_but_feb_29_is_optional():
    # Validates: a gap between segments fails the stitch; a non-leap run's absent Feb 29 does not
    gap = _seg({"02-03": 1.0}, {"02": {"Electricity": {"Total": 1.0}}}, {})
    r = segments.stitch([SEG_A, gap])
    assert r["ok"] is False
    assert r["missing_days"] == ["02-01", "02-02"]
    feb = _seg({"02-28": 1.0}, {}, {})
    mar = _seg({"03-01": 1.0}, {}, {})
    assert segments.stitch([feb, mar])["ok"] is True


def test_reference_check_reports_bias_cv_rmse_and_first_kept_day():
    # Validates: the error checks the skill relies on are computed against the annual reference
    ref = _seg({"01-30": 10.0, "01-31": 12.0, "02-01": 25.0, "02-02": 25.0}, {}, {})
    c = segments.stitch([SEG_A, SEG_B], ref)["reference_check"]
    assert c["annual_electricity_error_pct"] == pytest.approx(0.0, abs=1e-9)  # 72 vs 72
    assert c["monthly_electricity_bias_pct"] == {"01": pytest.approx(0.0), "02": pytest.approx(0.0)}
    assert c["monthly_cv_rmse_pct"] == pytest.approx(0.0, abs=1e-9)
    # daily errors 0, 0, -5, +5 -> RMSE sqrt(12.5), mean 18
    assert c["daily_cv_rmse_pct"] == pytest.approx(100 * 12.5 ** 0.5 / 18, rel=1e-9)
    assert c["first_kept_day_error_pct"] == [{"day": "02-01", "error_pct": pytest.approx(-20.0)}]


def _run_with_results(root, run_id, payload):
    run = root / run_id / "run"
    run.mkdir(parents=True)
    (run / "segment_results.json").write_text(json.dumps(payload), encoding="utf-8")


def test_op_reads_each_runs_results(tmp_path, monkeypatch):
    # Validates: the tool reads run/segment_results.json from the caller's own run dirs and stitches them
    monkeypatch.setattr(segments, "user_run_root", lambda: tmp_path)
    _run_with_results(tmp_path, "run_a", SEG_A)
    _run_with_results(tmp_path, "run_b", SEG_B)
    r = segments.stitch_segment_results_op(["run_b", "run_a"])
    assert r["ok"] is True, r
    assert r["annual_electricity_kwh"] == pytest.approx(72.0, abs=1e-9)


@pytest.mark.parametrize(("run_ids", "message"), [
    ([], "run_ids is empty"),
    (["run_a", "run_a"], "more than once"),
    (["../escape"], "Run not found"),
    (["run_empty"], "has no run/segment_results.json"),
])
def test_op_errors(tmp_path, monkeypatch, run_ids, message):
    # Validates: bad run lists, traversal ids and runs without the summary step fail with a clear error
    monkeypatch.setattr(segments, "user_run_root", lambda: tmp_path)
    _run_with_results(tmp_path, "run_a", SEG_A)
    (tmp_path / "run_empty" / "run").mkdir(parents=True)
    r = segments.stitch_segment_results_op(run_ids)
    assert r["ok"] is False
    assert message in r["error"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
def test_op_refuses_linked_results_file(tmp_path, monkeypatch):
    # Validates: a segment_results.json planted as a link (e.g. to another tenant's file) is not read
    monkeypatch.setattr(segments, "user_run_root", lambda: tmp_path / "me")
    other = tmp_path / "other.json"
    other.write_text(json.dumps(SEG_A), encoding="utf-8")
    run = tmp_path / "me" / "run_link" / "run"
    run.mkdir(parents=True)
    (run / "segment_results.json").symlink_to(other)
    r = segments.stitch_segment_results_op(["run_link"])
    assert r["ok"] is False
    assert "has no run/segment_results.json" in r["error"]
