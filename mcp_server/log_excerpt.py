"""Crash-aware excerpts of subprocess logs (issue #150).

When a measure run dies in native code (SDK segfault, e.g. ``remove()`` then
``addToNode`` on a dead node), Ruby's crash handler prints a ``[BUG]`` report:
marker line, control frames, the Ruby-level backtrace (with the measure.rb line
number), loaded features, then a ``/proc/self/maps`` dump of several hundred
lines. A plain "last 50 lines" tail shows only the memory map, so the agent
never sees what crashed or where.

Pure Python, no openstudio import — unit-tested in tests/test_log_excerpt.py.
"""
from __future__ import annotations

from pathlib import Path

from mcp_server.util import read_head_bounded, read_tail_bounded

# Bound on how much of a failed run's log is read back for the excerpt (same
# cap as gbxml_import). The full log stays on disk under log_path.
LOG_TAIL_MAX_BYTES = 200_000

# Native Ruby/Python crash signatures only. EnergyPlus ``**  Fatal  **`` is not
# here on purpose: it never appears in measures-only runs and has its own parser.
CRASH_MARKERS: tuple[str, ...] = (
    "[BUG] ",              # Ruby crash handler, first line of the report
    "Fatal Python error",  # CPython faulthandler
    "Segmentation fault",
    "SIGSEGV",
    "SIGABRT",
)


def find_crash_marker(lines: list[str]) -> int | None:
    """Index of the first line carrying any CRASH_MARKERS substring, else None."""
    for i, line in enumerate(lines):
        for marker in CRASH_MARKERS:
            if marker in line:
                return i
    return None


def excerpt_log(
    text: str,
    tail_lines: int = 50,
    before: int = 5,
    after: int = 40,
) -> tuple[str, str | None]:
    """Return ``(excerpt, crash_marker_line)`` for a log's text.

    With a crash marker: the window ``[i-before, i+after]`` around the first
    marker line (Ruby's control frames and Ruby-level backtrace, including the
    measure.rb line, sit within ~25 lines after ``[BUG]``), followed by
    ``... [N more lines]`` when the log continues past the window.

    Without one: the last ``tail_lines`` lines, ``crash_marker_line`` None
    (the pre-#150 behaviour).
    """
    if not text:
        return "", None
    lines = text.splitlines()
    idx = find_crash_marker(lines)
    if idx is None:
        return "\n".join(lines[-tail_lines:]), None
    start = max(0, idx - before)
    end = min(len(lines), idx + after + 1)
    window = lines[start:end]
    remaining = len(lines) - end
    if remaining > 0:
        window.append(f"... [{remaining} more lines]")
    return "\n".join(window), lines[idx]


def excerpt_log_file(
    path: Path,
    max_bytes: int = LOG_TAIL_MAX_BYTES,
    tail_lines: int = 50,
) -> tuple[str, str | None, str]:
    """Symlink-refusing, bounded excerpt of a log on disk.

    Returns ``(excerpt, crash_marker_line, tail_text)``. ``tail_text`` is the
    last ``max_bytes`` decoded (callers parse minitest/pytest summaries from
    it). The crash scan runs on that tail first; if the tail was clipped and
    carries no marker, the first ``max_bytes`` are scanned too, because Ruby's
    ``[BUG]`` report puts the marker and backtrace at the top and the
    memory-map dump — which can exceed the cap on its own — at the bottom.

    Raises ``ValueError`` like the util readers (symlink, non-regular,
    unreadable); callers turn that into a ``(log unreadable: …)`` excerpt.
    """
    tail_bytes = read_tail_bounded(path, max_bytes)
    tail_text = tail_bytes.decode("utf-8", errors="replace")
    excerpt, marker = excerpt_log(tail_text, tail_lines=tail_lines)
    if marker is None and len(tail_bytes) >= max_bytes:
        head_text = read_head_bounded(path, max_bytes).decode("utf-8", errors="replace")
        head_excerpt, head_marker = excerpt_log(head_text, tail_lines=tail_lines)
        if head_marker is not None:
            return head_excerpt, head_marker, tail_text
    return excerpt, marker, tail_text


def describe_exit(returncode: int) -> str:
    """Human-readable exit status for a failed subprocess.

    Ruby's crash handler ends its ``[BUG]`` report with ``abort()`` (134, or -6
    when the signal reaches Python directly); an unhandled segfault is 139/-11.
    """
    if returncode in (134, -6):
        return "SIGABRT (native crash, see crash_marker)"
    if returncode in (139, -11):
        return "SIGSEGV (native crash, see crash_marker)"
    return f"exit code {returncode}"
