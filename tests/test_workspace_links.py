"""Guards on the session resource workspace, exercised in-process against planted links.

generated_files/ is written by the measure and the model's files/ dir is tenant-writable,
so a link at either place must never redirect what the server reads or writes.
Integration tier (imports openstudio through model_manager); no MCP transport needed.
"""
import sys
from pathlib import Path

import pytest
from conftest import integration_enabled

pytestmark = pytest.mark.integration
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")


@pytest.fixture
def mm():
    if not integration_enabled():
        pytest.skip("integration disabled")
    pytest.importorskip("openstudio")
    from mcp_server import model_manager
    model_manager.clear_model()
    yield model_manager
    model_manager.clear_model()


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    d = tmp_path / "measure_run"
    (d / "generated_files").mkdir(parents=True)
    return d


def _collect(run_dir: Path):
    from mcp_server.skills.measures.operations import _collect_generated_files
    return _collect_generated_files(run_dir)


def test_collect_adopts_only_top_level_regular_files(run_dir):
    # Validates: regular files are adopted; a nested dir is not (only what the CLI's search
    # path would resolve by bare name travels with the model)
    (run_dir / "generated_files" / "sched.csv").write_text("1\n", encoding="utf-8")
    (run_dir / "generated_files" / "nested").mkdir()
    (run_dir / "generated_files" / "nested" / "deep.csv").write_text("1\n", encoding="utf-8")
    files, err = _collect(run_dir)
    assert err is None
    assert [f.name for f in files] == ["sched.csv"]


@posix_only
def test_collect_skips_a_link_left_in_generated_files(run_dir, tmp_path):
    # Validates: a link a measure leaves in generated_files/ is not adopted, even when its
    # target is a readable regular file, so the server never publishes a file from elsewhere
    target = tmp_path / "elsewhere" / "private.txt"
    target.parent.mkdir()
    target.write_text("private\n", encoding="utf-8")
    (run_dir / "generated_files" / "sched.csv").write_text("1\n", encoding="utf-8")
    (run_dir / "generated_files" / "linked.txt").symlink_to(target)
    files, err = _collect(run_dir)
    assert err is None
    assert [f.name for f in files] == ["sched.csv"], "the link must be skipped, the real file kept"


@posix_only
def test_collect_refuses_generated_files_that_is_itself_a_link(run_dir, tmp_path):
    # Validates: when the measure replaced generated_files/ by a link, nothing is adopted and
    # the result is refused; a per-entry check alone would accept the target dir's files
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "private.csv").write_text("1\n", encoding="utf-8")
    gen = run_dir / "generated_files"
    gen.rmdir()
    gen.symlink_to(elsewhere, target_is_directory=True)
    files, err = _collect(run_dir)
    assert files == []
    assert err is not None and "generated_files" in err and "not adopted" in err


def test_collect_refuses_over_budget_output(run_dir, monkeypatch):
    # Validates: output over the per-file, count or total budget refuses the result (the copy
    # runs in the server, outside subprocess rlimits) instead of adopting part of it
    import mcp_server.skills.measures.operations as ops
    gen = run_dir / "generated_files"
    (gen / "a.csv").write_bytes(b"x" * 50)
    (gen / "b.csv").write_bytes(b"x" * 50)
    (gen / "c.csv").write_bytes(b"x" * 50)

    monkeypatch.setattr(ops, "MAX_GENERATED_FILE_BYTES", 40)
    files, err = _collect(run_dir)
    assert files == [] and "over the 40-byte limit" in err

    monkeypatch.setattr(ops, "MAX_GENERATED_FILE_BYTES", 1000)
    monkeypatch.setattr(ops, "MAX_GENERATED_FILES", 2)
    files, err = _collect(run_dir)
    assert files == [] and "over the 2 limit" in err

    monkeypatch.setattr(ops, "MAX_GENERATED_FILES", 10)
    monkeypatch.setattr(ops, "MAX_GENERATED_TOTAL_BYTES", 120)
    files, err = _collect(run_dir)
    assert files == [] and "over the 120-byte limit" in err

    monkeypatch.setattr(ops, "MAX_GENERATED_TOTAL_BYTES", 1000)
    files, err = _collect(run_dir)
    assert err is None and len(files) == 3


def _persist(pending: Path, dst: Path):
    from mcp_server.skills.model_management.operations import _persist_pending_files
    return _persist_pending_files(pending, dst)


@posix_only
def test_persist_never_writes_through_a_link_at_the_destination(tmp_path):
    # Validates: a link planted at files/<name> is skipped and reported; its target keeps its
    # content and the pending file stays in the workspace (nothing is lost or redirected)
    pending = tmp_path / "ws" / "files"
    pending.mkdir(parents=True)
    (pending / "sched.csv").write_text("generated\n", encoding="utf-8")
    victim = tmp_path / "victim.txt"
    victim.write_text("untouched\n", encoding="utf-8")
    dst = tmp_path / "model" / "files"
    dst.mkdir(parents=True)
    (dst / "sched.csv").symlink_to(victim)

    persisted, replaced, skipped = _persist(pending, dst)
    assert (persisted, replaced, skipped) == ([], [], ["sched.csv"])
    assert victim.read_text(encoding="utf-8") == "untouched\n"
    assert (pending / "sched.csv").exists(), "a skipped file must stay pending, not be unlinked"


def test_persist_skips_a_directory_at_the_destination_name(tmp_path):
    # Validates: a directory already at files/<name> is not treated as a container to copy
    # into (copy2 would); the file is skipped and reported
    pending = tmp_path / "ws" / "files"
    pending.mkdir(parents=True)
    (pending / "sched.csv").write_text("generated\n", encoding="utf-8")
    dst = tmp_path / "model" / "files"
    (dst / "sched.csv").mkdir(parents=True)
    persisted, replaced, skipped = _persist(pending, dst)
    assert (persisted, replaced, skipped) == ([], [], ["sched.csv"])
    assert not (dst / "sched.csv" / "sched.csv").exists()


def test_persist_replaces_a_regular_file_and_reports_it(tmp_path):
    # Validates: an existing regular file of the same name is replaced by the generated one
    # (the model's newest truth) and the replacement is reported, not silent
    pending = tmp_path / "ws" / "files"
    pending.mkdir(parents=True)
    (pending / "sched.csv").write_text("new\n", encoding="utf-8")
    dst = tmp_path / "model" / "files"
    dst.mkdir(parents=True)
    (dst / "sched.csv").write_text("old\n", encoding="utf-8")
    persisted, replaced, skipped = _persist(pending, dst)
    assert (persisted, replaced, skipped) == (["sched.csv"], ["sched.csv"], [])
    assert (dst / "sched.csv").read_text(encoding="utf-8") == "new\n"
    assert not (pending / "sched.csv").exists()


@posix_only
def test_stage_refuses_a_model_files_dir_that_is_a_link(mm, tmp_path):
    # Validates: a model whose files/ is itself a link is not staged into the measure run
    # (reject_escaping_symlinks checks entries, not the dir, so the dir needs its own check)
    import openstudio

    from mcp_server.skills.measures.operations import _stage_model_resources
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    osm = model_dir / "m.osm"
    assert openstudio.model.exampleModel().save(str(osm), True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "private.txt").write_text("private\n", encoding="utf-8")
    (model_dir / "files").symlink_to(elsewhere, target_is_directory=True)
    mm.load_model(osm)

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    err = _stage_model_resources(run_dir)
    assert err is not None and "symlink" in err
    assert not (run_dir / "files").exists(), "nothing may be staged from a linked files/ dir"


@posix_only
def test_workspace_root_that_is_a_link_is_refused(mm, tmp_path, monkeypatch):
    # Validates: a link planted at <run_root>/workspace does not redirect where the server
    # creates and writes session workspaces
    import openstudio

    from mcp_server import config
    root = tmp_path / "runs"
    root.mkdir()
    monkeypatch.setattr(config, "RUN_ROOT", root.resolve())
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / "workspace").symlink_to(elsewhere, target_is_directory=True)
    mm.set_model(openstudio.model.exampleModel())
    with pytest.raises(RuntimeError, match="symlink"):
        mm.pending_files_dir()
    assert list(elsewhere.iterdir()) == [], "nothing may be created through the link"
