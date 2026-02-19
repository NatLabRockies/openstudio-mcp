#!/usr/bin/env python3
"""SEB4 convenience wrapper for the generic OSW runner.

This script intentionally contains *no* MCP/tool logic. It simply delegates to
`mcp_run_osw.py`, preserving historical developer workflows that ran the SEB4
fixture by default.

- If you pass `--osw ...`, it will use that.
- Otherwise it injects a default SEB4 OSW path (or MCP_OSW_PATH if set).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


DEFAULT_SEB4_OSW = os.environ.get(
    "MCP_OSW_PATH",
    "tests/assets/SEB_model/SEB4_baseboard/workflow.osw",
)


def main() -> int:
    # Both scripts are expected to live side-by-side in the repo's scripts/ dir.
    this_dir = Path(__file__).resolve().parent
    target = this_dir / "mcp_run_osw.py"

    argv = sys.argv[1:]

    # If caller already provided --osw, pass through unchanged.
    if "--osw" not in argv:
        argv = ["--osw", DEFAULT_SEB4_OSW, *argv]

    proc = subprocess.run([sys.executable, str(target), *argv])
    return int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
