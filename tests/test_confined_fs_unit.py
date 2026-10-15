"""util.py file primitives under a confinement root (issue #190): a symlink planted at a
directory component ABOVE the one the primitive opens must fail the access instead of
redirecting it. Before #190 only the final component (and, for the dir-fd writer, the
immediate directory) was checked; everything above was resolved by pathname at open time."""
import hashlib
import os
import sys
from pathlib import Path

import pytest

from mcp_server import config
from mcp_server.util import (
    copy_regular_file_nofollow,
    open_nofollow_for_write,
    read_file_bounded,
    read_file_in_dir_nofollow,
    read_head_bounded,
    read_tail_bounded,
    sha256_regular_file_nofollow,
    write_text_in_dir_nofollow,
)

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and dir_fd")

DECOY = b"decoy bytes that must never be read or overwritten\n"
# A link at a directory component fails its O_NOFOLLOW|O_DIRECTORY open with ELOOP, or with
# ENOTDIR on Linux, which checks O_DIRECTORY first.
LINK_AT_COMPONENT = r"symbolic link|Not a directory"


def _tree(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    """root/alpha -> other (a link two levels above the leaf); other/b/f.txt holds DECOY.

    The confinement roots are patched to [root]; `raising=False` so the same
    test runs against code that predates confinement_roots (where it is red).
    """
    root = tmp_path / "root"
    other = tmp_path / "other"
    (other / "b").mkdir(parents=True)
    (other / "b" / "f.txt").write_bytes(DECOY)
    root.mkdir()
    (root / "alpha").symlink_to(other, target_is_directory=True)
    monkeypatch.setattr(config, "confinement_roots", lambda: [root], raising=False)
    return root, other


def _snapshot(other: Path) -> dict[str, bytes]:
    return {str(p.relative_to(other)): p.read_bytes() for p in sorted(other.rglob("*")) if p.is_file()}


@posix_only
def test_reads_refuse_a_link_at_an_ancestor_component(tmp_path, monkeypatch):
    # Regression: read_file_bounded / read_tail_bounded / read_head_bounded /
    # sha256_regular_file_nofollow / read_file_in_dir_nofollow opened the leaf no-follow but
    # resolved root/alpha by pathname, so the link handed them the decoy's bytes
    root, _other = _tree(tmp_path, monkeypatch)
    target = root / "alpha" / "b" / "f.txt"
    for reader in (read_file_bounded, read_tail_bounded, read_head_bounded):
        with pytest.raises(ValueError, match="symlink"):
            reader(target, 4096)
    with pytest.raises(OSError, match=LINK_AT_COMPONENT):
        sha256_regular_file_nofollow(target, 4096)
    with pytest.raises(OSError, match=LINK_AT_COMPONENT):
        read_file_in_dir_nofollow(target.parent, "f.txt", 4096)


@posix_only
def test_writes_refuse_a_link_at_an_ancestor_component_and_leave_the_target_tree_alone(tmp_path, monkeypatch):
    # Regression: open_nofollow_for_write and write_text_in_dir_nofollow created or truncated
    # files in the link's target directory (the dir-fd writer refused a link at the immediate
    # directory only, not above it)
    root, other = _tree(tmp_path, monkeypatch)
    before = _snapshot(other)
    with pytest.raises(OSError, match=LINK_AT_COMPONENT):
        with open_nofollow_for_write(root / "alpha" / "b" / "new.txt") as fh:
            fh.write("x")
    with pytest.raises(OSError, match=LINK_AT_COMPONENT):
        with open_nofollow_for_write(root / "alpha" / "b" / "f.txt") as fh:
            fh.write("x")
    with pytest.raises(OSError, match=LINK_AT_COMPONENT):
        write_text_in_dir_nofollow(root / "alpha" / "b", "f.txt", "x")
    with pytest.raises(OSError, match=LINK_AT_COMPONENT):
        write_text_in_dir_nofollow(root / "alpha" / "b", "new.txt", "x")
    assert _snapshot(other) == before, "nothing may be created or changed behind the link"


@posix_only
def test_copy_refuses_a_link_at_an_ancestor_of_either_end(tmp_path, monkeypatch):
    # Regression: copy_regular_file_nofollow opened both ends no-follow at the leaf only, so a
    # link above the source read the decoy and a link above the destination wrote into other/
    root, other = _tree(tmp_path, monkeypatch)
    (root / "own").mkdir()
    src = root / "own" / "src.txt"
    src.write_bytes(b"own bytes\n")
    before = _snapshot(other)
    with pytest.raises(OSError, match=LINK_AT_COMPONENT):
        copy_regular_file_nofollow(root / "alpha" / "b" / "f.txt", root / "own" / "copy.txt", 4096)
    assert not (root / "own" / "copy.txt").exists(), "the decoy must not be copied"
    with pytest.raises(OSError, match=LINK_AT_COMPONENT):
        copy_regular_file_nofollow(src, root / "alpha" / "b" / "src.txt", 4096)
    assert _snapshot(other) == before


@posix_only
def test_a_relative_path_under_the_root_is_confined_too(tmp_path, monkeypatch):
    # Regression: callers keep some paths relative (test_measure_op's measure_dir); a relative
    # path must be classified against the roots lexically, not dropped to the unconfined path
    root, _other = _tree(tmp_path, monkeypatch)
    monkeypatch.chdir(root)
    with pytest.raises(ValueError, match="symlink"):
        read_file_bounded(Path("alpha") / "b" / "f.txt", 4096)


@posix_only
def test_a_path_under_no_root_keeps_the_final_component_check_only(tmp_path, monkeypatch):
    # Validates: outside every confinement root (shared read-only roots) behaviour is unchanged:
    # a plain file reads, a link at the leaf is refused, a link above the leaf is followed
    root, _other = _tree(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "confinement_roots", list, raising=False)
    plain = root / "plain.txt"
    plain.write_bytes(b"plain\n")
    assert read_file_bounded(plain, 4096) == b"plain\n"
    leaf_link = root / "leaf_link.txt"
    leaf_link.symlink_to(plain)
    with pytest.raises(ValueError, match="symlink"):
        read_file_bounded(leaf_link, 4096)
    assert read_file_bounded(root / "alpha" / "b" / "f.txt", 4096) == DECOY


@posix_only
def test_plain_files_under_the_root_read_write_copy_and_hash_normally(tmp_path, monkeypatch):
    # Validates: the descriptor walk is transparent for an ordinary tree under the root
    root, _other = _tree(tmp_path, monkeypatch)
    (root / "a" / "b").mkdir(parents=True)
    f = root / "a" / "b" / "f.txt"
    with open_nofollow_for_write(f) as fh:
        fh.write("hello\n")
    assert read_file_bounded(f, 4096) == b"hello\n"
    assert read_tail_bounded(f, 3) == b"lo\n"
    assert read_head_bounded(f, 3) == b"hel"
    assert sha256_regular_file_nofollow(f, 4096) == hashlib.sha256(b"hello\n").hexdigest()
    write_text_in_dir_nofollow(root / "a" / "b", "g.txt", "bye\n")
    assert read_file_in_dir_nofollow(root / "a" / "b", "g.txt", 4096) == b"bye\n"
    assert copy_regular_file_nofollow(f, root / "a" / "copy.txt", 4096) == 6
    assert (root / "a" / "copy.txt").read_bytes() == b"hello\n"
    with open_nofollow_for_write(f) as fh:  # existing regular file: truncated and rewritten
        fh.write("x")
    assert f.read_bytes() == b"x"


@posix_only
def test_a_fifo_at_a_write_name_is_refused_without_blocking_or_truncating(tmp_path, monkeypatch):
    # Regression: open_nofollow_for_write used O_CREAT|O_TRUNC without O_NONBLOCK or an fstat
    # check, so a FIFO at the name blocked the open (and a non-regular entry could be truncated
    # before any check); writes now create exclusively or fstat-then-ftruncate
    root, _other = _tree(tmp_path, monkeypatch)
    fifo = root / "pipe"
    os.mkfifo(fifo)
    with pytest.raises((OSError, ValueError)):
        with open_nofollow_for_write(fifo) as fh:
            fh.write("x")
    assert fifo.is_fifo()


@posix_only
def test_dir_handle_creates_subdirs_by_descriptor_and_refuses_a_link_at_a_created_name(tmp_path, monkeypatch):
    # Validates: walk(create=True) makes missing components relative to the parent descriptor;
    # a link already at the name fails the no-follow open instead of being descended; a file
    # already at the name is refused; create_file honours overwrite
    from mcp_server.confined_fs import DirHandle

    root, other = _tree(tmp_path, monkeypatch)
    with DirHandle.open(root) as h:
        assert h.fd is not None, "under a root the handle is descriptor-backed"
        with h.walk(Path("x") / "y", create=True) as leaf:
            assert (root / "x" / "y").is_dir()
            fd, existed = leaf.create_file("f.txt", overwrite=False)
            os.write(fd, b"one")
            os.close(fd)
            assert existed is False
            with pytest.raises(FileExistsError):
                leaf.create_file("f.txt", overwrite=False)
            assert (root / "x" / "y" / "f.txt").read_bytes() == b"one"
            fd, existed = leaf.create_file("f.txt", overwrite=True)
            os.close(fd)
            assert existed is True and (root / "x" / "y" / "f.txt").read_bytes() == b""
            assert leaf.identity() == (os.lstat(root / "x" / "y").st_dev, os.lstat(root / "x" / "y").st_ino)
        with pytest.raises(OSError, match=LINK_AT_COMPONENT):
            h.walk(Path("alpha") / "b", create=True)
        (root / "file").write_bytes(b"")
        with pytest.raises(NotADirectoryError):
            h.subdir("file", create=True)
        with pytest.raises(ValueError, match="plain file name"):
            h.subdir("a/b")
    assert _snapshot(other) == {"b/f.txt": DECOY}
