"""Pairing logic for the stdio-vs-HTTP benchmark comparison."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from benchmark_compare_transport import (
    apply_fix,
    classify,
    compare,
    discordant,
    leg_summary,
    tally_reruns,
    verdict,
)

pytestmark = pytest.mark.unit

PASS = {"passed": True}
FAIL = {"passed": False}
SKIP = {"passed": True, "skipped": True}


def _leg(**results) -> dict:
    return {"tests": [{"test_id": t, **r} for t, r in results.items()]}


@pytest.mark.parametrize(("stdio", "http", "expected"), [
    (PASS, PASS, "both_pass"),
    (FAIL, FAIL, "both_fail"),
    (PASS, FAIL, "stdio_only_pass"),
    (FAIL, PASS, "http_only_pass"),
    (SKIP, FAIL, "ran_on_one_side"),
    (None, PASS, "ran_on_one_side"),
    (SKIP, SKIP, "both_skipped"),
])
def test_classify(stdio, http, expected):
    # Validates: a skip must never count as a pass, or a broken HTTP fixture
    # would hide every test depending on it
    assert classify(stdio, http) == expected


def test_only_real_disagreements_are_rerun():
    # Validates: reruns cost usage, so tests that agree must stay out of the list
    result = compare(_leg(a=PASS, b=FAIL, c=PASS, d=FAIL),
                     _leg(a=PASS, b=FAIL, c=FAIL, d=PASS))
    assert discordant(result["pairs"]) == ["c", "d"]
    assert result["counts"]["both_pass"] == 1
    assert result["counts"]["both_fail"] == 1


@pytest.mark.parametrize(("stdio", "http", "expected"), [
    ((3, 3), (0, 3), "confirmed: fails on HTTP"),
    ((0, 3), (3, 3), "confirmed: fails on stdio"),
    ((2, 3), (3, 3), "noise"),
    ((3, 3), (1, 3), "noise"),
    ((0, 3), (0, 3), "unclear"),
    ((0, 0), (3, 3), "no reruns"),
])
def test_verdict(stdio, http, expected):
    # Validates: only a clean split across all reruns is reported as a real
    # transport difference; anything mixed is randomness
    assert verdict(stdio, http) == expected


def test_tally_ignores_skipped_reruns():
    # Validates: a skipped rerun must not inflate the rerun denominator
    legs = [_leg(a=PASS), _leg(a=FAIL), _leg(a=SKIP)]
    assert tally_reruns(legs, ["a"]) == {"a": (1, 2)}


def test_summary_uses_cli_time_not_wall_clock():
    # Regression: duration_s includes usage-cap sleeps, which would pass as
    # HTTP latency when one transport happens to hit the cap
    leg = _leg(a={"passed": True, "duration_s": 9000.0, "duration_ms": 30000},
               b={"passed": False, "duration_s": 50.0, "duration_ms": 50000,
                  "failure_mode": "wrong_tool"},
               c=SKIP)
    summary = leg_summary(leg)
    assert summary["ran"] == 2
    assert summary["passed"] == 1
    assert summary["median_s"] == pytest.approx(40.0, abs=0.01)
    assert summary["failure_modes"] == {"wrong_tool": 1}


def test_fix_is_outcome_blind():
    # Validates: a false-failure repair must replace rows that come back
    # failing too, so it cannot selectively raise the HTTP score
    legs = {"m": [_leg(a=FAIL, b=FAIL, c=PASS)]}
    fixes = {"m": [_leg(a=PASS, b=FAIL)]}
    assert apply_fix(legs, fixes) == ["a", "b"]
    rows = {r["test_id"]: r for r in legs["m"][0]["tests"]}
    assert (rows["a"]["passed"], rows["b"]["passed"], rows["c"]["passed"]) == (
        True, False, True)
    assert rows["a"]["substituted_fix"] is True
    assert "substituted_fix" not in rows["c"]


def test_fix_keeps_setup_rows():
    # Validates: fix legs rebuild fixtures first; those rows must not replace
    # the original leg's setup results
    setup = "tests/llm/test_01_setup.py::test_x"
    legs = {"m": [_leg(**{setup: PASS})]}
    assert apply_fix(legs, {"m": [_leg(**{setup: FAIL})]}) == []
    assert legs["m"][0]["tests"][0]["passed"] is True
