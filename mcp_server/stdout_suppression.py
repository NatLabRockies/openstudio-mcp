"""Keep stdout clean for MCP JSON-RPC on the openstudio PyPI wheel.

Two real sources of stdout pollution on our runtime corrupt the JSON-RPC
stream. Two-layer defense at startup:

Class A — SWIG memleak warnings at interpreter shutdown —
    "swig/python detected a memory leak of type 'boost::optional< ... > *'"
  Fires for boost::optional<Model>, boost::optional<double>, etc. The PyPI
  `openstudio==3.11.0` wheel was built WITHOUT SWIG_PYTHON_SILENT_MEMLEAK
  (root cause SWIG#2638; OpenStudio#5421 was "fixed" by #5422 for .deb only,
  wheel build missed it — filed as NatLabRockies/OpenStudio#5608).
  Caught by `redirect_c_stdout_to_stderr` (fd-level backstop).

Class B — OpenStudio Logger output during Space::volume() / floorArea() —
    "[utilities.Polyhedron] <0> Polyhedron is not enclosed in original
     testing. Trying to add missing colinear points."
    "[openstudio.model.Space] <0> Object of type 'OS:Space' and named
     '...' is not enclosed, there are N edges that aren't used..."
  Source: the default `standardOutLogger` sink runs at Warn level and
  writes to C stdout. Silenced via the intended Logger API in
  `silence_openstudio_stdout_logger()`.

Call order in server.py::main():
  1. silence_openstudio_stdout_logger()  # primary fix for Class B
  2. redirect_c_stdout_to_stderr()       # backstop for Class A + unknowns
  3. mcp.run()

Done once — no per-call suppression, no races, no missed callsites.
"""
from __future__ import annotations

import atexit
import contextlib
import io
import os
import sys


def silence_openstudio_stdout_logger():
    """Set OpenStudio's standardOutLogger to Fatal level.

    Primary defense for Class B (Polyhedron/Space Logger warnings).
    Uses the intended OpenStudio Logger API — no fd manipulation.
    Call at process startup before any SDK operations.
    """
    import openstudio
    openstudio.Logger.instance().standardOutLogger().setLogLevel(openstudio.Fatal)


def redirect_c_stdout_to_stderr():
    """Permanently redirect C-level stdout (fd 1) to stderr.

    Belt-and-suspenders backstop for anything the Logger config doesn't
    catch (SWIG memleak fprintfs under odd fd states, future unknown C
    stdout writes). Must be called before FastMCP's stdio_server()
    captures sys.stdout.
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
