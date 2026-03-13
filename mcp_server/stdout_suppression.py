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


@contextlib.contextmanager
def suppress_openstudio_warnings():
    """Temporarily redirect stdout to stderr to suppress OpenStudio SWIG warnings.

    This ensures the MCP JSON-RPC protocol on stdout remains clean.
    Works at both Python and C level by redirecting file descriptors.
    """
    # Save original file descriptors
    stdout_fd = sys.stdout.fileno()
    stderr_fd = sys.stderr.fileno()

    # Duplicate the current stdout FD to restore later
    saved_stdout_fd = os.dup(stdout_fd)

    # Flush Python-level buffers before redirecting
    sys.stdout.flush()
    sys.stderr.flush()

    try:
        # Redirect stdout (fd 1) to stderr (fd 2) at OS level
        # This catches C-level fprintf(stdout, ...) from SWIG
        os.dup2(stderr_fd, stdout_fd)

        yield

    finally:
        # Flush again before restoring
        sys.stdout.flush()
        sys.stderr.flush()

        # Restore original stdout
        os.dup2(saved_stdout_fd, stdout_fd)
        os.close(saved_stdout_fd)


def create_suppression_middleware():
    """Create a FastMCP middleware that wraps ALL tool calls in stdout suppression.

    Returns a Middleware instance. Factory function avoids importing fastmcp
    at module level (this module is also used by model_manager which loads
    before the server).
    """
    from fastmcp.server.middleware import Middleware

    class _StdoutSuppressionMiddleware(Middleware):
        async def on_call_tool(self, context, call_next):
            with suppress_openstudio_warnings():
                return await call_next(context)

    return _StdoutSuppressionMiddleware()


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
