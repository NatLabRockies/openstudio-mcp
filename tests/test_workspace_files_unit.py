"""workspace_files.persist_pending_files: the session workspace's generated files move into the
saved model's files/ by directory descriptor (issue #190). Before, files/ and its parents were
created with mkdir(parents=True) and written by pathname after a one-time link check, so a
link planted above files/ received the generated files."""
import sys
from pathlib import Path

import pytest

from mcp_server import config
from mcp_server.workspace_files import persist_pending_files

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and dir_fd")


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "root"
    pending = root / "workspace" / "pending"
    pending.mkdir(parents=True)
    (pending / "report.html").write_bytes(b"<html>1</html>")
    (pending / "data.csv").write_bytes(b"a,b\n")
    (pending / "nested").mkdir()
    (root / "model").mkdir()
    other = tmp_path / "other"
    (other / "files").mkdir(parents=True)
    (other / "files" / "data.csv").write_bytes(b"theirs\n")
    return root, pending, other


def _snapshot(tree: Path) -> dict[str, bytes]:
    return {str(p.relative_to(tree)): p.read_bytes() for p in sorted(tree.rglob("*")) if p.is_file()}


@posix_only
@pytest.mark.parametrize("confined", [True, False])
def test_moves_regular_files_reports_replacements_and_skips_links(tmp_path, monkeypatch, confined):
    # Validates: regular files move (and leave the workspace), a same-named regular file in
    # files/ is replaced and reported, a link in the workspace or at a destination name is
    # skipped, a nested directory is ignored, files/ is created under its companion folder
    root, pending, _other = _layout(tmp_path)
    monkeypatch.setattr(config, "confinement_roots", lambda: [root] if confined else [], raising=False)
    (pending / "link.csv").symlink_to(pending / "data.csv")
    dst_files = root / "model" / "m" / "files"

    assert persist_pending_files(pending, dst_files) == (["data.csv", "report.html"], [], [])
    assert (dst_files / "data.csv").read_bytes() == b"a,b\n"
    assert sorted(p.name for p in pending.iterdir()) == ["link.csv", "nested"]

    (pending / "data.csv").write_bytes(b"c,d\n")
    assert persist_pending_files(pending, dst_files) == (["data.csv"], ["data.csv"], [])
    assert (dst_files / "data.csv").read_bytes() == b"c,d\n"

    victim = root / "victim.txt"
    victim.write_bytes(b"keep\n")
    (dst_files / "report.html").unlink()
    (dst_files / "report.html").symlink_to(victim)
    (pending / "report.html").write_bytes(b"<html>2</html>")
    assert persist_pending_files(pending, dst_files) == ([], [], ["report.html"])
    assert victim.read_bytes() == b"keep\n"
    assert (pending / "report.html").exists(), "a skipped file stays in the workspace"

    (root / "empty").mkdir()
    assert persist_pending_files(root / "empty", root / "model" / "m2" / "files") == ([], [], [])
    assert not (root / "model" / "m2").exists()


@posix_only
def test_a_link_above_the_destination_fails_the_move_and_writes_nothing(tmp_path, monkeypatch):
    # Regression: files/ was created with mkdir(parents=True) and written by pathname, so a
    # link at the companion folder (root/model/m -> other) received the generated files and
    # overwrote the target's same-named file; the move now walks from the confinement root
    root, pending, other = _layout(tmp_path)
    monkeypatch.setattr(config, "confinement_roots", lambda: [root], raising=False)
    (root / "model" / "m").symlink_to(other, target_is_directory=True)
    before = _snapshot(other)
    with pytest.raises(OSError, match=r"symbolic link|Not a directory"):
        persist_pending_files(pending, root / "model" / "m" / "files")
    assert _snapshot(other) == before
    assert sorted(p.name for p in pending.iterdir()) == ["data.csv", "nested", "report.html"]
