"""model_save.save_model_confined: an OpenStudio model is saved to a private temp file (the SDK's
save() takes a pathname only) and copied to its destination through the descriptor walk, so a link
planted at the destination name or at any component above it is refused instead of written through
(issue #190, the last pathname write)."""
import sys
import tempfile
from pathlib import Path

import pytest
from test_analysis_tools import _http_tenant

from mcp_server import confined_fs, model_save

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and dir_fd")

SECRET = b"bob's private bytes\n"
OSM = b"OS:Version,\n  {00000000-0000-0000-0000-000000000000},\n  3.11.0;\n"


class _Model:
    """Stands in for openstudio.model.Model: save(path, overwrite) writes the OSM text by pathname."""

    def __init__(self, text: bytes = OSM, result: bool = True, raise_on_save: Exception | None = None):
        self.text, self.result, self.raise_on_save = text, result, raise_on_save
        self.saved_to: list[Path] = []

    def save(self, path, overwrite):
        if self.raise_on_save is not None:
            raise self.raise_on_save
        self.saved_to.append(Path(str(path)))
        Path(str(path)).write_bytes(self.text)
        return self.result


def _staging_files() -> list[str]:
    return sorted(p.name for p in Path(tempfile.gettempdir()).iterdir() if p.name.startswith(model_save.STAGING_PREFIX))


def test_saves_exact_bytes_and_leaves_no_staging_file(tmp_path, monkeypatch):
    # Validates: the destination holds what the SDK wrote, the SDK was pointed at a private temp
    # file (never at the destination), missing parents are created, and the temp file is gone
    root = _http_tenant(monkeypatch, tmp_path)
    model = _Model()
    dest = root / "run_a" / "in.osm"
    before = _staging_files()
    model_save.save_model_confined(model, dest)
    assert dest.read_bytes() == OSM
    assert model.saved_to and model.saved_to[0] != dest and model.saved_to[0].parent == Path(tempfile.gettempdir())
    assert _staging_files() == before


@posix_only
def test_link_at_the_destination_name_is_refused_and_its_target_untouched(tmp_path, monkeypatch):
    # Regression: model.save(path) opens the destination by pathname and follows a link planted
    # there (a finished sandboxed step can leave <run>/<name>.osm as a link to another tenant's
    # file), truncating and overwriting the target; the descriptor copy refuses the link
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "model.osm").write_bytes(SECRET)
    dest = root / "run_b" / "out.osm"
    dest.parent.mkdir()
    dest.symlink_to(bob / "model.osm")
    with pytest.raises((OSError, ValueError)):
        model_save.save_model_confined(_Model(), dest)
    assert dest.is_symlink() and (bob / "model.osm").read_bytes() == SECRET
    assert _staging_files() == []


@posix_only
def test_link_at_a_destination_parent_is_refused_with_nothing_under_the_target(tmp_path, monkeypatch):
    # Regression: a run-dir component swapped for a link to another tenant's directory after the
    # caller's check made the pathname save create the file there; the walk fails on the link
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "run").mkdir()
    (root / "run_c").symlink_to(bob / "run", target_is_directory=True)
    with pytest.raises(OSError, match=r"symbolic link|Too many levels|Not a directory"):
        model_save.save_model_confined(_Model(), root / "run_c" / "in.osm")
    assert sorted(p.name for p in (bob / "run").iterdir()) == []
    assert _staging_files() == []


def test_sdk_refusing_the_save_is_a_runtime_error_with_nothing_at_the_destination(tmp_path, monkeypatch):
    # Validates: model.save returning False (what the SDK does for an unwritable path) is a
    # RuntimeError naming the destination, nothing is created there, the temp file is gone
    root = _http_tenant(monkeypatch, tmp_path)
    dest = root / "run_d" / "in.osm"
    with pytest.raises(RuntimeError, match=r"in.osm"):
        model_save.save_model_confined(_Model(result=False), dest)
    assert not dest.exists()
    assert _staging_files() == []


def test_sdk_exception_propagates_and_the_staging_file_is_removed(tmp_path, monkeypatch):
    # Validates: an exception out of the SDK's save is not swallowed and leaves no temp file
    root = _http_tenant(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        model_save.save_model_confined(_Model(raise_on_save=RuntimeError("boom")), root / "run_e" / "in.osm")
    assert _staging_files() == []


def test_over_budget_save_leaves_an_existing_destination_untouched(tmp_path, monkeypatch):
    # Validates: the copy checks the staged size before truncating an existing destination, so an
    # over-budget model is a ValueError and the previous file keeps its bytes
    root = _http_tenant(monkeypatch, tmp_path)
    dest = root / "run_f" / "model.osm"
    dest.parent.mkdir()
    dest.write_bytes(b"previous\n")
    with pytest.raises(ValueError, match="exceeds"):
        model_save.save_model_confined(_Model(), dest, max_bytes=8)
    assert dest.read_bytes() == b"previous\n"
    assert _staging_files() == []


def test_existing_regular_destination_is_replaced(tmp_path, monkeypatch):
    # Validates: saving over the model's own file (save_osm_model on a loaded model) replaces it
    root = _http_tenant(monkeypatch, tmp_path)
    dest = root / "models" / "m.osm"
    dest.parent.mkdir()
    dest.write_bytes(b"old\n")
    model_save.save_model_confined(_Model(), dest)
    assert dest.read_bytes() == OSM


def test_destination_under_no_confinement_root_is_written_in_path_mode(tmp_path, monkeypatch):
    # Validates: a destination outside every confinement root (a shared asset dir in stdio mode)
    # is written through the same API in path mode
    monkeypatch.setattr(confined_fs, "confinement_root_for", lambda _path: None)
    dest = tmp_path / "elsewhere" / "m.osm"
    model_save.save_model_confined(_Model(), dest)
    assert dest.read_bytes() == OSM
