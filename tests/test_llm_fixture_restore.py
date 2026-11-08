"""Snapshot and restore of the shared LLM fixture models (tests/llm/fixtures.py)."""
from __future__ import annotations

from pathlib import Path

import pytest
from llm.fixtures import pristine_dir, restore_fixtures, snapshot_fixture, snapshot_fixtures

pytestmark = pytest.mark.unit


def _make_fixture(runs: Path, name: str, osm: bytes) -> Path:
    d = runs / "examples" / name
    (d / "baseline_model" / "files").mkdir(parents=True)
    (d / "baseline_model.osm").write_bytes(osm)
    (d / "baseline_model" / "files" / "plugin.py").write_text("print(1)\n")
    return d


def test_restore_brings_back_the_snapshot_after_an_in_place_save(tmp_path):
    # Regression: #235 — an agent's save_osm_model with no path overwrote
    # /runs/examples/llm-test-baseline/baseline_model.osm (people removed, reheat
    # coils dropped) and every later test in the run loaded the changed model
    runs = tmp_path / "runs"
    fixture = _make_fixture(runs, "llm-test-baseline", b"PRISTINE")
    assert snapshot_fixture(runs, "llm-test-baseline") is True

    (fixture / "baseline_model.osm").write_bytes(b"MUTATED BY AGENT")
    (fixture / "baseline_model" / "files" / "plugin.py").unlink()
    (fixture / "stray.osm").write_bytes(b"left behind")

    assert restore_fixtures(runs) == ["llm-test-baseline"]
    assert (fixture / "baseline_model.osm").read_bytes() == b"PRISTINE"
    assert (fixture / "baseline_model" / "files" / "plugin.py").read_text() == "print(1)\n"
    assert not (fixture / "stray.osm").exists(), "files an agent added must not leak into the next test"
    pristine = pristine_dir(runs) / "llm-test-baseline" / "baseline_model.osm"
    assert pristine.read_bytes() == b"PRISTINE", "restore must not consume the snapshot"


def test_snapshots_live_outside_the_runs_dir(tmp_path):
    # Regression: review of #242 — a snapshot inside <runs>/examples sits in the
    # agent's /runs mount, shows up in list_files, and could be saved over itself
    runs = tmp_path / "runs"
    _make_fixture(runs, "llm-test-baseline", b"X")
    snapshot_fixture(runs, "llm-test-baseline")
    assert pristine_dir(runs) == (tmp_path / "runs-pristine").resolve()
    assert not any(p.name.endswith("pristine") for p in runs.rglob("*"))


def test_fixtures_without_a_snapshot_are_left_alone(tmp_path):
    # Validates: a fixture setup never produced keeps its "run test_01_setup first"
    # skip; restore must not invent or delete it
    runs = tmp_path / "runs"
    _make_fixture(runs, "llm-test-example", b"NO SNAPSHOT")
    other = runs / "examples" / "not-a-fixture"
    other.mkdir(parents=True)
    (other / "x.osm").write_bytes(b"x")

    assert restore_fixtures(runs) == []
    assert (runs / "examples" / "llm-test-example" / "baseline_model.osm").read_bytes() == b"NO SNAPSHOT"
    assert (other / "x.osm").read_bytes() == b"x"
    assert snapshot_fixtures(runs) == ["llm-test-example"]
    assert snapshot_fixture(runs, "llm-test-ems") is False


def test_snapshot_after_setup_replaces_an_older_snapshot(tmp_path):
    # Validates: a rerun of test_01_setup in the same runs dir produces fresh
    # fixtures; the new snapshot, not last run's, must win
    runs = tmp_path / "runs"
    fixture = _make_fixture(runs, "llm-test-baseline-hvac", b"RUN 1")
    snapshot_fixture(runs, "llm-test-baseline-hvac")
    (fixture / "baseline_model.osm").write_bytes(b"RUN 2")
    snapshot_fixture(runs, "llm-test-baseline-hvac")
    (fixture / "baseline_model.osm").write_bytes(b"MUTATED")
    restore_fixtures(runs)
    assert (fixture / "baseline_model.osm").read_bytes() == b"RUN 2"


def test_only_the_named_fixture_is_snapshotted(tmp_path):
    # Regression: review of #242 — snapshotting every fixture after every setup
    # test let a later setup test (retrofit simulation) overwrite the baseline's
    # snapshot with a modified model
    runs = tmp_path / "runs"
    _make_fixture(runs, "llm-test-baseline", b"BASE")
    _make_fixture(runs, "llm-test-example", b"EXAMPLE")
    snapshot_fixture(runs, "llm-test-baseline")
    (runs / "examples" / "llm-test-example" / "baseline_model.osm").write_bytes(b"CHANGED LATER")
    snapshot_fixture(runs, "llm-test-example")
    (runs / "examples" / "llm-test-baseline" / "baseline_model.osm").write_bytes(b"CHANGED LATER")
    assert restore_fixtures(runs) == ["llm-test-baseline", "llm-test-example"]
    assert (runs / "examples" / "llm-test-baseline" / "baseline_model.osm").read_bytes() == b"BASE"


def test_nothing_to_do_without_a_runs_dir(tmp_path):
    # Validates: with LLM tests disabled the runs dir may not exist; the autouse
    # hook must not fail collection-time skips
    assert restore_fixtures(tmp_path / "missing") == []
    assert snapshot_fixtures(tmp_path / "missing") == []
