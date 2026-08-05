"""Unit tests for scripts/benchmark_aggregate.py — Wilson math, pooling,
stability detection, digest guard. Stdlib only, no openstudio import.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from benchmark_aggregate import aggregate, load_results, wilson, write_artifacts

pytestmark = pytest.mark.unit


def test_wilson_known_values():
    # Validates: Wilson 95% interval matches published reference values —
    # the CI numbers printed in the paper come straight from this function
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-3)
    assert hi == pytest.approx(0.9433, abs=1e-3)
    lo, hi = wilson(10, 10)
    assert lo == pytest.approx(0.7225, abs=1e-3)
    assert hi == pytest.approx(1.0, abs=1e-3)
    lo, hi = wilson(0, 10)
    assert lo == pytest.approx(0.0, abs=1e-3)
    assert hi == pytest.approx(0.2775, abs=1e-3)


def _run(model, arm, tests, image_id="sha256:abc"):
    return {
        "model": model,
        "run_config": {"arm": arm, "image": "openstudio-mcp:v1.2.0",
                       "image_id": image_id},
        "tests": tests,
    }


def _t(test_id, passed, tier="progressive", mode=None):
    entry = {"test_id": test_id, "passed": passed, "tier": tier}
    if mode:
        entry["failure_mode"] = mode
    return entry


PROG = "tests/llm/test_06_progressive.py::test_progressive"
RUNS = [
    _run("sonnet", "full", [
        _t(f"{PROG}[thermostat_L1]", True),
        _t(f"{PROG}[thermostat_L2]", True),
        _t("tests/llm/test_04_workflows.py::test_workflow[x]", True, tier="tier2"),
    ]),
    _run("sonnet", "full", [
        _t(f"{PROG}[thermostat_L1]", False, mode="wrong_tool"),
        _t(f"{PROG}[thermostat_L2]", True),
        _t("tests/llm/test_04_workflows.py::test_workflow[x]", False,
           tier="tier2", mode="outcome_mismatch"),
    ]),
    _run("sonnet", "noskills", [
        _t(f"{PROG}[thermostat_L1]", False, mode="no_mcp_tool"),
        _t(f"{PROG}[thermostat_L2]", True),
    ]),
]


def test_aggregate_pools_tiers_levels_modes_stability():
    # Validates: pooled s/n per (model, arm, tier), per-level discovery counts,
    # failure-mode counts, and 0<k<N stability detection over synthetic repeats
    agg = aggregate(RUNS)

    assert agg["tiers"][("sonnet", "full", "progressive")] == {"s": 3, "n": 4}
    assert agg["tiers"][("sonnet", "full", "tier2")] == {"s": 1, "n": 2}
    assert agg["tiers"][("sonnet", "noskills", "progressive")] == {"s": 1, "n": 2}

    assert agg["levels"][("sonnet", "full", "L1")] == {"s": 1, "n": 2}
    assert agg["levels"][("sonnet", "full", "L2")] == {"s": 2, "n": 2}
    assert agg["levels"][("sonnet", "noskills", "L1")] == {"s": 0, "n": 1}

    assert agg["modes"][("sonnet", "full", "wrong_tool")] == 1
    assert agg["modes"][("sonnet", "full", "outcome_mismatch")] == 1
    assert agg["modes"][("sonnet", "noskills", "no_mcp_tool")] == 1

    unstable = agg["unstable"]
    assert unstable[("sonnet", "full", f"{PROG}[thermostat_L1]")] == (1, 2)
    assert ("sonnet", "full", f"{PROG}[thermostat_L2]") not in unstable
    assert agg["repeats"][("sonnet", "full")] == 2


def test_write_artifacts_emits_all_files(tmp_path):
    # Validates: all five paper artifacts render with the pooled numbers in them
    agg = aggregate(RUNS)
    write_artifacts(agg, tmp_path)

    table = (tmp_path / "table4.md").read_text(encoding="utf-8")
    assert "75.0%" in table  # sonnet/full progressive 3/4
    ablation = (tmp_path / "ablation.md").read_text(encoding="utf-8")
    assert "## sonnet" in ablation and "noskills" in ablation
    discovery = (tmp_path / "discovery.csv").read_text(encoding="utf-8")
    assert "sonnet,full,L1,1,2,0.5000" in discovery
    stability = (tmp_path / "stability.md").read_text(encoding="utf-8")
    assert "thermostat_L1" in stability and "1/2" in stability
    modes = (tmp_path / "failure_modes.md").read_text(encoding="utf-8")
    assert "wrong_tool" in modes and "outcome_mismatch" in modes


def test_check_image_freshness_aborts_on_stale_image(monkeypatch):
    # Regression: a stale openstudio-mcp:dev image silently no-op'd the
    # ablation arm — the harness runs BAKED server code, so an image older
    # than HEAD must abort the sweep
    from benchmark_sweep import check_image_freshness

    monkeypatch.delenv("OSMCP_SWEEP_ALLOW_STALE_IMAGE", raising=False)
    with pytest.raises(SystemExit, match="predates HEAD"):
        check_image_freshness("img:dev", "2026-08-05T14:20:10.123456789Z",
                              "2026-08-05T15:55:00-04:00")

    # fresh image passes; override lets a stale one through deliberately
    check_image_freshness("img:dev", "2026-08-05T21:00:00.000000000Z",
                          "2026-08-05T15:55:00-04:00")
    monkeypatch.setenv("OSMCP_SWEEP_ALLOW_STALE_IMAGE", "1")
    check_image_freshness("img:dev", "2026-08-05T14:20:10.123456789Z",
                          "2026-08-05T15:55:00-04:00")
    # unparseable timestamps never block (provenance is still recorded)
    monkeypatch.delenv("OSMCP_SWEEP_ALLOW_STALE_IMAGE", raising=False)
    check_image_freshness("img:dev", "not-a-date", "also-not-a-date")


def test_load_results_refuses_mixed_image_identity(tmp_path):
    # Validates: a sweep mixing two image builds aborts instead of silently
    # pooling results from different artifacts (reviewer issue B4)
    (tmp_path / "a_full_r1.json").write_text(
        json.dumps(_run("sonnet", "full", [], image_id="sha256:aaa")))
    (tmp_path / "a_full_r2.json").write_text(
        json.dumps(_run("sonnet", "full", [], image_id="sha256:bbb")))

    with pytest.raises(SystemExit, match="mixed image identities"):
        load_results(tmp_path, ignore_digest=False)

    runs = load_results(tmp_path, ignore_digest=True)
    assert len(runs) == 2
