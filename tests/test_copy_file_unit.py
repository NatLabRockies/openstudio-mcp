"""results.copy_file (the copy_file tool) under a tenant root: the destination directory is
created through directory descriptors and a copy onto the source itself is refused
(issue #190, Codex review findings on the first version of the descriptor walk)."""
import sys
from pathlib import Path

import pytest
from test_analysis_tools import _http_tenant

from mcp_server import config
from mcp_server.skills.results import operations as results

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and dir_fd")


def _snapshot(tree: Path) -> list[str]:
    return sorted(str(p.relative_to(tree)) for p in tree.rglob("*"))


@posix_only
def test_destination_ancestor_swapped_after_authorization_is_not_created_through(tmp_path, monkeypatch):
    # Regression: copy_file authorized the destination, then ran mkdir(parents=True) by
    # pathname; alice/exports swapped for a link to bob's tree in between created bob/new (the
    # copy itself was then refused); the directories are now created from the tenant root
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    src = root / "a.csv"
    src.write_bytes(b"1\n")
    (root / "exports").mkdir()
    real_allowed = config.is_path_allowed

    def allow_then_swap(p, *, write=False):
        out = real_allowed(p, write=write)
        if write and not (root / "exports").is_symlink():
            (root / "exports").rename(root / "exports_moved")
            (root / "exports").symlink_to(bob, target_is_directory=True)
        return out

    monkeypatch.setattr(config, "is_path_allowed", allow_then_swap)
    before = _snapshot(bob)
    res = results.copy_file(str(src), str(root / "exports" / "new"))
    assert res["ok"] is False and res["error"] == "invalid_destination", res
    assert _snapshot(bob) == before, "no directory may be created in the other tenant's tree"


def test_copying_a_file_onto_its_own_directory_keeps_the_file(tmp_path, monkeypatch):
    # Regression: copy_file(file, file.parent) truncated the file to zero bytes (the no-follow
    # copier replaced shutil.copy2 without its same-file guard)
    root = _http_tenant(monkeypatch, tmp_path)
    src = root / "a.csv"
    src.write_bytes(b"1,2,3\n")
    res = results.copy_file(str(src), str(root))
    assert res["ok"] is False and res["error"] == "copy_failed", res
    assert "source file" in res["message"]
    assert src.read_bytes() == b"1,2,3\n"


@posix_only
def test_a_dotdot_destination_through_a_link_cannot_reach_a_sibling_tenant(tmp_path, monkeypatch):
    # Regression: the destination was authorized after resolving links (alice/link/../../bob
    # resolves inside alice when link -> alice/deep/nested) but the descriptor walk collapsed
    # the '..' lexically and wrote into the real sibling bob; '..' components are now refused
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "a.csv").write_bytes(b"bobs\n")
    (root / "deep" / "nested").mkdir(parents=True)
    (root / "link").symlink_to(root / "deep" / "nested", target_is_directory=True)
    src = root / "a.csv"
    src.write_bytes(b"alices\n")
    res = results.copy_file(str(src), str(root / "link" / ".." / ".." / "bob"))
    assert res["ok"] is False and res["error"] == "invalid_destination", res
    assert (bob / "a.csv").read_bytes() == b"bobs\n", "the other tenant's file must be untouched"
