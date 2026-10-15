"""util.copy_regular_file_nofollow: the primitive every server-side resource move uses
(measure output into the session workspace, workspace into the model's files/). Both ends
are tenant-writable, so a link at either end must never redirect the copy, and a file
over the budget must never be copied in full."""
import sys
from pathlib import Path

import pytest

from mcp_server.util import copy_regular_file_nofollow

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")


def test_copies_a_regular_file_and_reports_bytes(tmp_path):
    # Validates: the plain case copies content exactly and returns the byte count
    src = tmp_path / "a.csv"
    src.write_bytes(b"0,1\n" * 100)
    dst = tmp_path / "out" / "a.csv"
    dst.parent.mkdir()
    assert copy_regular_file_nofollow(src, dst, max_bytes=10_000) == 400
    assert dst.read_bytes() == src.read_bytes()


@posix_only
def test_refuses_a_symlinked_source(tmp_path):
    # Validates: a link planted where the source should be is not read through, even when
    # its target is a readable regular file (a stat-then-copy check would have accepted it)
    target = tmp_path / "elsewhere.txt"
    target.write_text("private\n", encoding="utf-8")
    src = tmp_path / "linked.txt"
    src.symlink_to(target)
    dst = tmp_path / "copy.txt"
    with pytest.raises(OSError, match="symbolic link"):  # O_NOFOLLOW -> ELOOP
        copy_regular_file_nofollow(src, dst, max_bytes=10_000)
    assert not dst.exists(), "nothing may be written when the source is a link"


@posix_only
def test_refuses_a_symlinked_destination(tmp_path):
    # Validates: a link planted at the destination name is not written through, so a
    # tenant cannot redirect a server-side write to a file of their choosing
    src = tmp_path / "a.csv"
    src.write_text("1\n", encoding="utf-8")
    target = tmp_path / "victim.txt"
    target.write_text("untouched\n", encoding="utf-8")
    dst = tmp_path / "a_link.csv"
    dst.symlink_to(target)
    with pytest.raises(OSError, match="symbolic link"):  # O_NOFOLLOW -> ELOOP
        copy_regular_file_nofollow(src, dst, max_bytes=10_000)
    assert target.read_text(encoding="utf-8") == "untouched\n"


@posix_only
def test_refuses_a_fifo_at_the_destination_without_blocking(tmp_path):
    # Regression: the destination was opened O_WRONLY without O_NONBLOCK and never fstat-checked,
    # so a FIFO planted at the destination name (between the caller's check and the copy) hung
    # the server on open, or, with a reader attached, took the copy as a stream
    import os

    src = tmp_path / "a.csv"
    src.write_text("1\n", encoding="utf-8")
    dst = tmp_path / "a_fifo.csv"
    os.mkfifo(dst)
    with pytest.raises((OSError, ValueError)):  # ENXIO (no reader) or "not a regular file"
        copy_regular_file_nofollow(src, dst, max_bytes=10_000)
    assert src.read_text(encoding="utf-8") == "1\n"


def test_refuses_a_file_over_the_budget_before_copying(tmp_path):
    # Validates: the size check runs on the opened file, so an over-budget file is refused
    # without being copied (the copy runs in the server, outside subprocess rlimits)
    src = tmp_path / "big.bin"
    src.write_bytes(b"x" * 2048)
    dst = tmp_path / "big_copy.bin"
    with pytest.raises(ValueError, match="exceeds"):
        copy_regular_file_nofollow(src, dst, max_bytes=1024)
    assert not dst.exists()


def test_refuses_a_non_regular_source(tmp_path):
    # Validates: a directory (or any non-regular entry) at the source is refused by the
    # fstat check rather than copied or crashed on
    src = tmp_path / "a_dir"
    src.mkdir()
    with pytest.raises((OSError, ValueError)):
        copy_regular_file_nofollow(src, tmp_path / "out.bin", max_bytes=1024)


def test_stops_when_the_source_grows_past_the_budget_mid_copy(tmp_path, monkeypatch):
    # Validates: a file that passes the up-front size check but is still being appended to
    # (a measure's helper process, a sparse file) is cut off at the budget, not copied whole
    import os

    src = tmp_path / "growing.bin"
    src.write_bytes(b"a" * 100)
    real_read = os.read
    appended = {"done": False}

    def read_then_grow(fd, n):
        chunk = real_read(fd, n)
        if chunk and not appended["done"]:
            appended["done"] = True
            with src.open("ab") as f:
                f.write(b"b" * 500)
        return chunk

    monkeypatch.setattr(os, "read", read_then_grow)
    with pytest.raises(ValueError, match="grew past"):
        copy_regular_file_nofollow(src, tmp_path / "out.bin", max_bytes=300)
    path = Path(tmp_path / "out.bin")
    assert path.stat().st_size <= 300, "no more than the budget may reach the destination"
