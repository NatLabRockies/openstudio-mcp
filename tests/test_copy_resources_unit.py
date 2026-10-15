"""resources.copy_resources walks the source and destination trees by directory descriptor
(issue #190). Before, the destination was checked for links once and then written by pathname,
and the source was re-resolved by pathname at each subdirectory, so a directory above either
end replaced by a link while the copy ran redirected the writes or the reads."""
import os
import sys
from pathlib import Path

import pytest

from mcp_server import config, resources
from mcp_server.resources import copy_resources

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and dir_fd")

REAL = b"real plugin\n"
DECOY = b"decoy plugin\n"


def _layout(tmp_path: Path) -> tuple[Path, Path]:
    """root/model/files (the source) and root/pkg (where lib/ will go); other/ holds decoys."""
    root = tmp_path / "root"
    src = root / "model" / "files"
    (src / "sub").mkdir(parents=True)
    (src / "schedule.csv").write_bytes(b"1,2\n")
    (src / "sub" / "plugin.py").write_bytes(REAL)
    (root / "pkg").mkdir()
    other = tmp_path / "other"
    for sub in ("lib", "files"):
        (other / sub / "sub").mkdir(parents=True)
        (other / sub / "sub" / "plugin.py").write_bytes(DECOY)
    (other / "files" / "schedule.csv").write_bytes(b"9\n")
    return root, other


def _snapshot(tree: Path) -> dict[str, bytes]:
    return {str(p.relative_to(tree)): p.read_bytes() for p in sorted(tree.rglob("*")) if p.is_file()}


def _confine(monkeypatch, roots: list[Path]) -> None:
    monkeypatch.setattr(config, "confinement_roots", lambda: roots, raising=False)


@posix_only
def test_destination_ancestor_swapped_after_the_precheck_is_refused(tmp_path, monkeypatch):
    # Regression: copy_resources checked dst and dst.parent for links once, then created and wrote
    # dst/<rel> by pathname; root/pkg replaced by a link to another tree after that check received
    # the copies. The destination is now opened by walking from the confinement root.
    root, other = _layout(tmp_path)
    _confine(monkeypatch, [root])
    real_related = resources._related

    def relate_then_swap(a, b):
        out = real_related(a, b)
        if not (root / "pkg").is_symlink():
            (root / "pkg").rename(root / "pkg_moved")
            (root / "pkg").symlink_to(other, target_is_directory=True)
        return out

    monkeypatch.setattr(resources, "_related", relate_then_swap)
    before = _snapshot(other)
    with pytest.raises(ValueError, match="not usable"):
        copy_resources([root / "model" / "files"], root / "pkg" / "lib")
    assert _snapshot(other) == before, "nothing may be written behind the swapped component"


@posix_only
def test_source_ancestor_swapped_mid_walk_does_not_redirect_the_reads(tmp_path, monkeypatch):
    # Regression: the source walk re-resolved each subdirectory and each file by pathname, so
    # root/model replaced by a link while the walk was in progress made the copy read the link
    # target's files; the walk now opens each entry relative to the directory it already holds
    root, other = _layout(tmp_path)
    _confine(monkeypatch, [root])
    real_scandir = os.scandir
    calls = {"n": 0}

    def scandir_then_swap(path="."):
        it = real_scandir(path)
        calls["n"] += 1
        if calls["n"] == 1:
            (root / "model").rename(root / "model_moved")
            (root / "model").symlink_to(other, target_is_directory=True)
        return it

    monkeypatch.setattr(os, "scandir", scandir_then_swap)
    out = copy_resources([root / "model" / "files"], root / "pkg" / "lib")
    assert [rel for rel, _ in out["copied"]] == ["schedule.csv", "sub/plugin.py"], out
    assert (root / "pkg" / "lib" / "schedule.csv").read_bytes() == b"1,2\n"
    assert (root / "pkg" / "lib" / "sub" / "plugin.py").read_bytes() == REAL


@posix_only
@pytest.mark.parametrize("confined", [True, False])
def test_plain_copies_behave_the_same_with_and_without_a_confinement_root(tmp_path, monkeypatch, confined):
    # Validates: the descriptor walk is transparent: subpaths kept, first source wins, a linked
    # entry is skipped, an existing file is kept unless overwrite (then reported in replaced),
    # a link at a destination name is never written through, dst is created only when
    # something is copied
    root, other = _layout(tmp_path)
    _confine(monkeypatch, [root] if confined else [])
    src = root / "model" / "files"
    (src / "link.csv").symlink_to(src / "schedule.csv")
    dst = root / "pkg" / "lib"

    out = copy_resources([src, other / "files"], dst)
    assert out == {
        "copied": [("schedule.csv", 0), ("sub/plugin.py", 0)],
        "replaced": [],
        "skipped": [("link.csv", "not a regular file")],
    }
    assert (dst / "sub" / "plugin.py").read_bytes() == REAL

    (src / "schedule.csv").write_bytes(b"changed\n")
    again = copy_resources([src], dst)
    assert again["copied"] == [] and again["replaced"] == []
    assert (dst / "schedule.csv").read_bytes() == b"1,2\n"
    over = copy_resources([src], dst, overwrite=True)
    assert over["replaced"] == ["schedule.csv", "sub/plugin.py"]
    assert (dst / "schedule.csv").read_bytes() == b"changed\n"

    victim = root / "victim.txt"
    victim.write_bytes(b"keep\n")
    (dst / "schedule.csv").unlink()
    (dst / "schedule.csv").symlink_to(victim)
    linked = copy_resources([src], dst, overwrite=True)
    assert linked["skipped"] == [
        ("link.csv", "not a regular file"), ("schedule.csv", "destination is a link or directory"),
    ]
    assert victim.read_bytes() == b"keep\n"

    (root / "empty").mkdir()
    assert copy_resources([root / "empty"], root / "pkg" / "lib2")["copied"] == []
    assert not (root / "pkg" / "lib2").exists()
