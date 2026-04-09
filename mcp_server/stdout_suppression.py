"""Utilities for suppressing unwanted stdout from OpenStudio Python bindings.

The OpenStudio SWIG bindings print memory leak warnings to stdout:
"swig/python detected a memory leak of type 'openstudio::model::Model *', no destructor found."

This pollutes the MCP JSON-RPC protocol which requires clean stdout.
We redirect these warnings to stderr instead.
"""
from __future__ import annotations

import atexit
import contextlib
import os
import sys
import threading

# Process-wide reentrant lock so concurrent worker threads never interleave their
# os.dup2() calls on fd 1 (stdout).  FastMCP dispatches sync tools via
# anyio.to_thread.run_sync, so two tools CAN run simultaneously; without
# this lock, Thread B can save a "corrupted" stderr as its saved_stdout_fd
# and permanently point fd 1 at stderr after Thread A restores it.
# RLock (not Lock) allows the same thread to re-enter the suppression block
# safely — e.g., create_baseline_osm suppresses the entire create_baseline_model
# call, which internally calls set_constructions, which also suppresses its
# VersionTranslator.loadModel() call.
_suppress_lock = threading.RLock()


@contextlib.contextmanager
def suppress_openstudio_warnings():
    """Temporarily redirect stdout to stderr to suppress OpenStudio SWIG warnings.

    This ensures the MCP JSON-RPC protocol on stdout remains clean.
    Works at both Python and C level by redirecting file descriptors.

    Thread-safe: holds a process-wide lock for the duration so concurrent
    calls from worker threads cannot corrupt each other's saved fd state.
    """
    with _suppress_lock:
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()

        saved_stdout_fd = os.dup(stdout_fd)
        try:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(stderr_fd, stdout_fd)
            yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved_stdout_fd, stdout_fd)
            os.close(saved_stdout_fd)


def _redirect_stdout_to_stderr_at_exit():
    """Redirect stdout to stderr during Python cleanup to catch SWIG warnings.

    OpenStudio prints memory leak warnings when models are garbage-collected
    during Python interpreter shutdown. This redirects those to stderr.
    """
    try:
        stdout_fd = 1  # sys.stdout might be None at exit
        stderr_fd = 2
        os.dup2(stderr_fd, stdout_fd)
    except Exception:
        pass  # Silently ignore errors during shutdown


# Register the cleanup handler to run before Python exits
atexit.register(_redirect_stdout_to_stderr_at_exit)
