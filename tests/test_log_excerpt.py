"""Unit tests for mcp_server/log_excerpt.py — crash-aware log windows (issue #150).

Pure Python, no openstudio import.
"""
import os

import pytest

from mcp_server.log_excerpt import (
    CRASH_MARKERS,
    describe_exit,
    excerpt_log,
    excerpt_log_file,
)
from mcp_server.util import read_head_bounded

pytestmark = pytest.mark.unit


def _ruby_bug_report(map_lines: int = 250) -> str:
    """Shape of a Ruby `[BUG]` report from `openstudio run --measures_only`:
    marker, control frames, Ruby-level backtrace, loaded features, then a
    `/proc/self/maps` dump that dwarfs everything else. Section offsets mirror the
    real report (loaded features past line 40, map past line 50)."""
    lines = ["[BUG] Segmentation fault at 0x0000000000000000",
             "ruby 3.2.2 (2023-03-30 revision e51014f9c0) [x86_64-linux]",
             "", "-- Control frame information "
                 "-----------------------------------------------"]
    lines += [f"c:{i:04d} p:---- s:{i:04d} e:000000 CFUNC  :addToNode" for i in range(12)]
    lines += ["", "-- Ruby level backtrace information "
                  "----------------------------------------",
              "/runs/x/measures/replace_coil/measure.rb:42:in `addToNode'",
              "/runs/x/measures/replace_coil/measure.rb:42:in `run'",
              "", "-- C level backtrace information "
                  "-------------------------------------------",
              *[f"/lib/libc.so.6(0x{i:02x}) [0x{i:02x}]" for i in range(25)],
              "", "* Loaded features:", "", "    0 enumerator.so", "    1 thread.rb",
              "", "* Process memory map:", ""]
    lines += [f"{i:012x}-{i + 1:012x} r--p 00000000 08:01 {i}  /opt/lib/libruby.so"
              for i in range(map_lines)]
    return "\n".join(lines)


def test_bug_marker_window_replaces_memory_map_tail():
    # Regression: #150 — a native crash log ended with 50 lines of memory map, hiding the
    # [BUG] line and the measure.rb backtrace the agent needs to fix the measure
    text = _ruby_bug_report()
    excerpt, marker = excerpt_log(text, tail_lines=50, before=5, after=40)
    assert marker == "[BUG] Segmentation fault at 0x0000000000000000"
    lines = excerpt.splitlines()
    assert lines[0] == marker, "marker sits at the top when nothing precedes it"
    assert "-- Ruby level backtrace information" in excerpt
    assert "/runs/x/measures/replace_coil/measure.rb:42:in `run'" in excerpt
    assert "libruby.so" not in excerpt, "memory-map dump must not be in the excerpt"
    assert lines[-1] == "... [264 more lines]", lines[-1]
    assert len(lines) == 42, "marker + 40 after + trailer"


def test_plain_log_returns_last_tail_lines_without_marker():
    # Validates: no crash marker → unchanged behaviour, exactly the last tail_lines lines
    text = "\n".join(f"line {i}" for i in range(80))
    excerpt, marker = excerpt_log(text, tail_lines=50)
    assert marker is None
    lines = excerpt.splitlines()
    assert len(lines) == 50
    assert lines[0] == "line 30"
    assert lines[-1] == "line 79"


def test_marker_inside_tail_window_is_not_duplicated():
    # Validates: marker near the end → window is clipped to the file, no trailer, no
    # doubled lines
    text = "\n".join([f"pre {i}" for i in range(10)] + ["Fatal Python error: Segmentation fault",
                                                        "post 0", "post 1"])
    excerpt, marker = excerpt_log(text, tail_lines=50, before=5, after=40)
    assert marker == "Fatal Python error: Segmentation fault"
    lines = excerpt.splitlines()
    assert lines == ["pre 5", "pre 6", "pre 7", "pre 8", "pre 9", marker, "post 0", "post 1"]


def test_empty_text_returns_empty_excerpt():
    # Validates: an empty/unwritten log degrades to ("", None) rather than raising
    assert excerpt_log("") == ("", None)


def test_first_marker_wins():
    # Validates: the earliest marker line anchors the window (Ruby prints [BUG] first, then
    # "Segmentation fault" again in later sections)
    text = "\n".join(["ok"] * 3 + ["[BUG] Segmentation fault at 0x1"] + ["x"] * 60
                     + ["Segmentation fault (core dumped)"])
    _excerpt, marker = excerpt_log(text)
    assert marker == "[BUG] Segmentation fault at 0x1"


def test_marker_list_covers_ruby_and_python_crashes():
    # Validates: the roster is the contract the skill docs describe (native Ruby/Python
    # crashes only — no EnergyPlus fatals, which never occur in measures-only runs)
    assert CRASH_MARKERS == ("[BUG] ", "Fatal Python error", "Segmentation fault",
                             "SIGSEGV", "SIGABRT")


@pytest.mark.parametrize(("code", "expected"), [
    (134, "SIGABRT (native crash, see crash_marker)"),
    (-6, "SIGABRT (native crash, see crash_marker)"),
    (139, "SIGSEGV (native crash, see crash_marker)"),
    (-11, "SIGSEGV (native crash, see crash_marker)"),
    (1, "exit code 1"),
])
def test_describe_exit(code, expected):
    # Validates: Ruby's crash handler aborts (134/-6) and a raw segfault (139/-11) are
    # named for the agent; ordinary failures keep the plain exit code
    assert describe_exit(code) == expected


def test_excerpt_log_file_finds_marker_at_head_of_oversize_log(tmp_path):
    # Regression: #150 review — Ruby's memory-map dump can exceed the tail cap on its own;
    # a tail-only scan then drops the [BUG] line at the top and falls back to the map
    body = _ruby_bug_report(map_lines=20_000)  # ~1.4 MB of map lines after the report
    path = tmp_path / "openstudio.log"
    path.write_bytes(body.encode("utf-8"))
    assert path.stat().st_size > 200_000
    excerpt, marker, tail = excerpt_log_file(path, max_bytes=200_000)
    assert marker == "[BUG] Segmentation fault at 0x0000000000000000"
    assert "/runs/x/measures/replace_coil/measure.rb:42:in `run'" in excerpt
    assert "libruby.so" not in excerpt
    assert len(tail.encode("utf-8")) == 200_000, "tail is still the bounded last chunk"
    assert tail.endswith("/opt/lib/libruby.so")


def test_excerpt_log_file_small_log_reads_tail_only(tmp_path):
    # Validates: a log under the cap is scanned once, no head re-read, plain tail when
    # there is no marker
    path = tmp_path / "test.log"
    path.write_bytes("\n".join(f"line {i}" for i in range(80)).encode("utf-8"))
    excerpt, marker, tail = excerpt_log_file(path, max_bytes=200_000, tail_lines=50)
    assert marker is None
    assert excerpt.splitlines()[0] == "line 30"
    assert tail.startswith("line 0\n")


def test_excerpt_log_file_refuses_symlink(tmp_path):
    # Validates: the sandboxed subprocess could swap the log for a symlink; the reader
    # must refuse it rather than leak the target (same guarantee as read_tail_bounded)
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW unavailable (Windows): no-follow is POSIX-only, CI covers it")
    target = tmp_path / "secret"
    target.write_text("[BUG] not yours", encoding="utf-8")
    link = tmp_path / "openstudio.log"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform/user")
    with pytest.raises(ValueError, match="symlink or unreadable"):
        excerpt_log_file(link)


def test_read_head_bounded_returns_first_bytes(tmp_path):
    # Validates: head reader caps at max_bytes from offset 0 and returns a short file whole
    path = tmp_path / "log"
    path.write_bytes(b"0123456789" * 10)
    assert read_head_bounded(path, 25) == b"0123456789012345678901234"
    assert read_head_bounded(path, 1_000) == b"0123456789" * 10
