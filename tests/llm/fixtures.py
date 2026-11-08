"""Pristine copies of the shared fixture models (#235).

test_01_setup builds a few models once per run under <runs>/examples/<name>/.
Every later test loads one of them, and save_osm_model with no path writes back
over the loaded file, so one agent's save changed the model every following
test saw. Each creation test snapshots the fixture it built; before every other
test the snapshots are copied back, so each test starts from the model setup
produced.

Snapshots live NEXT TO the runs dir (<runs>-pristine/), not inside it: the
runs dir is mounted into the agent's container, so a copy inside it would show
up in list_files and could itself be loaded and saved over.
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


def pristine_dir(runs_dir: Path) -> Path:
    runs_dir = Path(runs_dir).resolve()
    return runs_dir.parent / f"{runs_dir.name}-pristine"


def _replace_tree(src: Path, dst: Path, what: str) -> None:
    try:
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    except PermissionError as e:
        # The MCP container runs as root; on a native Linux host its files are
        # root-owned and a non-root pytest cannot replace them.
        raise RuntimeError(
            f"cannot {what} fixture {src.name}: {e}. The runs dir must be writable by "
            "the user running pytest (on Linux, run pytest as the container's user or "
            "chown the runs dir after test_01_setup)") from e


def snapshot_fixture(runs_dir: Path, name: str) -> bool:
    """Copy <runs>/examples/<name> to the pristine dir. False when it does not exist.

    A whole directory, not just the .osm: the EMS fixture keeps its plugin
    script in the model's companion folder.
    """
    src = Path(runs_dir) / "examples" / name
    if not src.is_dir():
        return False
    _replace_tree(src, pristine_dir(runs_dir) / name, "snapshot")
    return True


def snapshot_fixtures(runs_dir: Path) -> list[str]:
    """Snapshot every fixture directory that exists. Returns the names snapshotted."""
    return [name for name in FIXTURE_NAMES if snapshot_fixture(runs_dir, name)]


def restore_fixtures(runs_dir: Path) -> list[str]:
    """Replace each fixture directory with its snapshot. Returns the names restored.

    Fixtures with no snapshot (setup never ran, or ran before this existed)
    are left alone, so the existing "run test_01_setup first" skips still apply.
    """
    done = []
    for name in FIXTURE_NAMES:
        src = pristine_dir(runs_dir) / name
        if not src.is_dir():
            continue
        _replace_tree(src, Path(runs_dir) / "examples" / name, "restore")
        done.append(name)
    return done
