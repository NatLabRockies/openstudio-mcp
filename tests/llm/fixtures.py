"""Pristine copies of the shared fixture models (#235).

test_01_setup builds a few models once per run under <runs>/examples/<name>/.
Every later test loads one of them, and save_osm_model with no path writes back
over the loaded file, so one agent's save changed the model every following
test saw. After setup, each fixture directory is snapshotted; before every
other test the snapshots are copied back, so each test starts from the model
setup produced.
"""
from __future__ import annotations

import shutil
from pathlib import Path

# Fixture directories under <runs>/examples, as test_01_setup creates them.
FIXTURE_NAMES = (
    "llm-test-baseline",
    "llm-test-baseline-hvac",
    "llm-test-example",
    "llm-test-ems",
)
PRISTINE_DIRNAME = "_pristine"


def _examples(runs_dir: Path) -> Path:
    return Path(runs_dir) / "examples"


def snapshot_fixtures(runs_dir: Path) -> list[str]:
    """Copy every existing fixture directory to examples/_pristine/<name>.

    A whole directory, not just the .osm: the EMS fixture keeps its plugin
    script in the model's companion folder. Returns the names snapshotted.
    """
    examples = _examples(runs_dir)
    done = []
    for name in FIXTURE_NAMES:
        src = examples / name
        if not src.is_dir():
            continue
        dst = examples / PRISTINE_DIRNAME / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        done.append(name)
    return done


def restore_fixtures(runs_dir: Path) -> list[str]:
    """Replace each fixture directory with its snapshot. Returns the names restored.

    Fixtures with no snapshot (setup never ran, or ran before this existed)
    are left alone, so the existing "run test_01_setup first" skips still apply.
    """
    examples = _examples(runs_dir)
    done = []
    for name in FIXTURE_NAMES:
        src = examples / PRISTINE_DIRNAME / name
        if not src.is_dir():
            continue
        dst = examples / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        done.append(name)
    return done
