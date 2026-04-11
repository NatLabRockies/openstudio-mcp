"""Redirect C-level stdout to stderr to protect MCP JSON-RPC protocol.

Two real sources of stdout pollution on our runtime (openstudio PyPI wheel
3.11.0) that would corrupt the JSON-RPC stream:

1. SWIG memleak warnings at interpreter shutdown —
     "swig/python detected a memory leak of type 'boost::optional< ... > *'"
   Fires for boost::optional<Model>, boost::optional<double>, etc. The
   PyPI wheel was built WITHOUT SWIG_PYTHON_SILENT_MEMLEAK. Root cause is
   SWIG#2638 / NatLabRockies/OpenStudio#5421; fix #5422 was applied to the
   .deb build only, not the wheel we actually run.

2. OpenStudio Logger output during Space::volume() / Space::floorArea() on
   models with imperfect geometry —
     "[utilities.Polyhedron] <0> Polyhedron is not enclosed in original
      testing. Trying to add missing colinear points."
   Source: LOG(Warn, ...) in OpenStudio utilities/Polyhedron. Unfiled
   upstream as of 2026-04-11.

Strategy: at process startup, permanently redirect fd 1 to stderr so ALL
C-level and logger writes go there harmlessly. Then replace Python's
sys.stdout with a wrapper around the saved original fd so FastMCP's stdio
transport still writes JSON-RPC to the real client pipe.

Done once — no per-call suppression, no races, no missed callsites.
"""
from __future__ import annotations

import atexit
import contextlib
import io
import os
import sys


def redirect_c_stdout_to_stderr():
    """Permanently redirect C-level stdout (fd 1) to stderr.

    Must be called before FastMCP's stdio_server() captures sys.stdout.
    After this call:
      - C code (printf, SWIG, OpenStudio internals) -> fd 1 -> stderr
      - Python sys.stdout -> saved fd -> real MCP client pipe
    """
    stdout_fd = sys.stdout.fileno()  # 1
    stderr_fd = sys.stderr.fileno()  # 2

    # Save the real stdout pipe (to MCP client) as a new fd
    saved_fd = os.dup(stdout_fd)

    # Point fd 1 at stderr — all future C-level printf goes here
    os.dup2(stderr_fd, stdout_fd)

    # Build a new Python stdout that writes to the saved fd.
    # Line buffering so each JSON-RPC message flushes immediately.
    binary = io.open(saved_fd, "wb", closefd=True)
    text = io.TextIOWrapper(binary, encoding="utf-8", line_buffering=True)
    sys.stdout = text


# Retain context-manager API so model_manager.py imports don't break.
# Now a no-op since fd 1 is permanently redirected.
@contextlib.contextmanager
def suppress_openstudio_warnings():
    """No-op — fd 1 is permanently redirected at startup."""
    yield


def _redirect_stdout_to_stderr_at_exit():
    """Safety net: ensure fd 1 points to stderr during interpreter shutdown."""
    try:
        os.dup2(2, 1)
    except Exception:
        pass


atexit.register(_redirect_stdout_to_stderr_at_exit)
