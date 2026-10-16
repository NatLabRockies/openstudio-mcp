"""The SDK's pathname-only loads of tenant-written files go through a private copy made by descriptor,
workflow JSON is written into run dirs through the descriptor walk, and a package zip is never placed
where it would archive itself (issue #190, the last three items)."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from test_analysis_tools import _http_tenant

from mcp_server import confined_fs, model_save
from mcp_server.skills.analysis import operations as analysis
from mcp_server.skills.simulation import operations as simulation

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and dir_fd")

SECRET = b"bob's private bytes\n"
OSM = b"OS:Version,\n  {00000000-0000-0000-0000-000000000000},\n  3.11.0;\n"


def _staging_files() -> list[str]:
    return sorted(p.name for p in Path(tempfile.gettempdir()).iterdir() if p.name.startswith(model_save.STAGING_PREFIX))


# ---- staged_for_sdk_load -------------------------------------------------------------------------

def test_tenant_tree_file_is_loaded_from_a_private_copy_with_exact_bytes(tmp_path, monkeypatch):
    # Validates: under a tenant root the SDK is pointed at a temp copy (never at the tenant path)
    # holding the same bytes, and the copy is gone once the block exits
    root = _http_tenant(monkeypatch, tmp_path)
    src = root / "run_a" / "in.osm"
    src.parent.mkdir(parents=True)
    src.write_bytes(OSM)
    before = _staging_files()
    with model_save.staged_for_sdk_load(src) as sdk_path:
        assert sdk_path != src and sdk_path.parent == Path(tempfile.gettempdir())
        assert sdk_path.name.startswith(model_save.STAGING_PREFIX) and sdk_path.suffix == ".osm"
        assert sdk_path.read_bytes() == OSM
        assert len(_staging_files()) == len(before) + 1
    assert not sdk_path.exists()
    assert _staging_files() == before


def test_copy_is_removed_when_the_sdk_load_raises(tmp_path, monkeypatch):
    # Validates: an exception inside the block (the SDK, or the caller) still removes the temp copy
    root = _http_tenant(monkeypatch, tmp_path)
    src = root / "in.osm"
    src.write_bytes(OSM)
    before = _staging_files()
    seen: dict[str, object] = {}

    def _sdk_load(path: Path) -> None:  # stands in for the SDK: records what it was given, then fails
        seen["path"], seen["staged"] = path, path.exists() and path.name in _staging_files()
        raise RuntimeError("sdk boom")

    with pytest.raises(RuntimeError, match="sdk boom"):
        with model_save.staged_for_sdk_load(src) as sdk_path:
            _sdk_load(sdk_path)
    assert seen["path"] != src and seen["staged"] is True  # a distinct staging copy existed at load time
    assert not seen["path"].exists()
    assert _staging_files() == before


def test_file_outside_every_confinement_root_is_passed_through_unchanged(tmp_path, monkeypatch):
    # Validates: the shared read-only roots (bundled models, test assets) keep their pathname load,
    # no copy is made (confinement_root_for is None there)
    # (tmp_path sits under the system temp dir, itself a confinement root, so a dir under the
    # repo's runs/ stands in for a shared root, as the read_file tests do)
    _http_tenant(monkeypatch, tmp_path)
    shared = Path(tempfile.mkdtemp(prefix="shared_root_", dir=Path.cwd() / "runs"))
    try:
        src = shared / "example.osm"
        src.write_bytes(OSM)
        assert confined_fs.confinement_root_for(src) is None, "precondition: outside every confinement root"
        before = _staging_files()
        with model_save.staged_for_sdk_load(src) as sdk_path:
            assert sdk_path == src.resolve()
            assert _staging_files() == before
    finally:
        shutil.rmtree(shared, ignore_errors=True)


@posix_only
def test_link_at_the_file_name_is_refused_and_its_target_unread(tmp_path, monkeypatch):
    # Regression: Model.load(path) opens by pathname and follows a link a sandboxed step left at
    # <run>/in.osm, loading another tenant's model into this tenant's session; the walk refuses it
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "model.osm").write_bytes(SECRET)
    link = root / "run_a" / "in.osm"
    link.parent.mkdir()
    link.symlink_to(bob / "model.osm")
    before = _staging_files()
    entered = False
    with pytest.raises(OSError, match=r"symbolic link|Too many levels|Not a directory"):
        with model_save.staged_for_sdk_load(link):
            entered = True
    assert entered is False
    assert _staging_files() == before  # no leftover copy
    assert (bob / "model.osm").read_bytes() == SECRET


@posix_only
def test_link_at_a_directory_component_is_refused(tmp_path, monkeypatch):
    # Regression: a directory component swapped for a link after the caller's check redirected the
    # SDK's open; every component is now opened relative to its parent's descriptor
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "run").mkdir()
    (bob / "run" / "in.osm").write_bytes(SECRET)
    (root / "run_a").symlink_to(bob / "run")
    with pytest.raises(OSError, match=r"symbolic link|Too many levels|Not a directory"):
        with model_save.staged_for_sdk_load(root / "run_a" / "in.osm"):
            pytest.fail("the block must not run")


def test_oversized_file_is_refused_before_the_sdk_sees_it(tmp_path, monkeypatch):
    # Validates: the copy is bounded (the SDK would otherwise read an arbitrarily large planted file)
    root = _http_tenant(monkeypatch, tmp_path)
    src = root / "big.osm"
    src.write_bytes(OSM)
    before = _staging_files()
    with pytest.raises(ValueError, match="exceeds"):
        with model_save.staged_for_sdk_load(src, max_bytes=len(OSM) - 1):
            pytest.fail("the block must not run")
    assert _staging_files() == before


def test_directory_at_the_file_name_is_refused(tmp_path, monkeypatch):
    # Validates: a non-regular entry (here a directory) at the name is a ValueError, not an SDK call
    root = _http_tenant(monkeypatch, tmp_path)
    (root / "in.osm").mkdir()
    with pytest.raises((ValueError, OSError)):
        with model_save.staged_for_sdk_load(root / "in.osm"):
            pytest.fail("the block must not run")


# ---- run_osw's staged OSW read and writes ---------------------------------------------------------

@posix_only
def test_staged_osw_is_read_through_the_walk_not_a_planted_link(tmp_path, monkeypatch):
    # Regression: run_osw read the staged OSW with Path.read_text, following a link a concurrent
    # tenant-side process planted at <run>/workflow.osw to another tenant's file
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "workflow.osw").write_text(json.dumps({"seed_file": "bobs.osm"}), encoding="utf-8")
    run_dir = root / "run_x"
    run_dir.mkdir()
    (run_dir / "workflow.osw").symlink_to(bob / "workflow.osw")
    with pytest.raises((OSError, ValueError)):
        simulation._load_json(run_dir / "workflow.osw")


@posix_only
def test_staged_osw_write_refuses_a_planted_link_and_leaves_its_target(tmp_path, monkeypatch):
    # Regression: run_osw rewrote the staged OSW with Path.write_text, which follows a link planted
    # at <run>/workflow.osw and overwrites the target (another tenant's file) with this tenant's OSW
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "workflow.osw").write_bytes(SECRET)
    run_dir = root / "run_x"
    run_dir.mkdir()
    (run_dir / "workflow.osw").symlink_to(bob / "workflow.osw")
    err = simulation._dump_json(run_dir / "workflow.osw", {"seed_file": "mine.osm"})
    assert err is not None and "workflow.osw" in err
    assert (bob / "workflow.osw").read_bytes() == SECRET
    assert (run_dir / "workflow.osw").is_symlink()


def test_staged_osw_write_and_read_round_trip(tmp_path, monkeypatch):
    # Validates: a regular staged OSW is written with the same JSON layout as before and read back
    root = _http_tenant(monkeypatch, tmp_path)
    run_dir = root / "run_x"
    run_dir.mkdir()
    osw = {"seed_file": "in.osm", "steps": [{"measure_dir_name": "m", "arguments": {"a": 1}}]}
    assert simulation._dump_json(run_dir / "workflow.osw", osw) is None
    assert (run_dir / "workflow.osw").read_text(encoding="utf-8") == json.dumps(osw, indent=2) + "\n"
    assert simulation._load_json(run_dir / "workflow.osw") == osw


def test_oversized_osw_is_refused(tmp_path, monkeypatch):
    # Validates: the staged OSW read is bounded; a planted multi-gigabyte file is an error, not a slurp
    root = _http_tenant(monkeypatch, tmp_path)
    big = root / "workflow.osw"
    big.write_bytes(b"{" + b" " * 64 + b"}")
    monkeypatch.setattr(simulation, "MAX_OSW_BYTES", 32)
    with pytest.raises(ValueError, match="exceeds"):
        simulation._load_json(big)


# ---- prepare_analysis_package output placement ---------------------------------------------------

@pytest.mark.parametrize("root_name", sorted(analysis.REQUIRED_ANALYSIS_PACKAGE_ROOTS))
def test_output_zip_inside_a_package_root_is_rejected_before_anything_is_staged(tmp_path, monkeypatch, root_name):
    # Regression: an output zip under measures/, weather/, seeds/, scripts/ or lib/ is itself a
    # member of the tree being archived, so the writer archived its own temp file (on older
    # versions the previous zip); it is now refused up front, before the seed is staged
    root = _http_tenant(monkeypatch, tmp_path)
    pkg = root / "pkg"
    (pkg / root_name).mkdir(parents=True)
    result = analysis.prepare_analysis_package(str(pkg), str(pkg / root_name / "out.zip"))
    assert result["ok"] is False
    assert f"{root_name}/" in result["error"] and "archive itself" in result["error"]
    assert sorted(p.name for p in (pkg / root_name).iterdir()) == []  # nothing written there
    assert not (pkg / "seeds").exists() or root_name == "seeds"  # the seed staging never ran


def test_output_zip_beside_the_package_roots_passes_the_placement_check(tmp_path, monkeypatch):
    # Validates: an output next to the roots (pkg/analysis.zip) or outside the package is still
    # accepted by the placement check (the call then fails later on the empty package, not here)
    root = _http_tenant(monkeypatch, tmp_path)
    pkg = root / "pkg"
    pkg.mkdir()
    for out in (pkg / "analysis.zip", root / "elsewhere" / "analysis.zip"):
        result = analysis.prepare_analysis_package(str(pkg), str(out))
        assert result["ok"] is False
        assert "archive itself" not in result["error"]
