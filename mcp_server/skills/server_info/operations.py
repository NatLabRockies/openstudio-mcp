"""Server info operations — health check and version detection."""
from __future__ import annotations

import os
import subprocess

import openstudio

from mcp_server.config import RUN_ROOT, MAX_CONCURRENCY, LOG_TAIL_DEFAULT
from mcp_server.version import __version__ as MCP_VERSION, OPENSTUDIO_SDK_VERSION


def _run_cmd(cmd: list[str]) -> tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return 0, out.strip()
    except subprocess.CalledProcessError as e:
        return e.returncode, (e.output or "").strip()


def get_server_status() -> dict:
    return {
        "ok": True,
        "run_root": str(RUN_ROOT),
        "max_concurrency": MAX_CONCURRENCY,
        "default_log_tail": LOG_TAIL_DEFAULT,
        "cwd": os.getcwd(),
    }


def get_versions() -> dict:
    rc, os_ver = _run_cmd(["openstudio", "--version"])
    eplus_ver = None
    for line in os_ver.splitlines():
        if "EnergyPlus" in line and "Version" in line:
            eplus_ver = line.strip()
            break

    return {
        "openstudio_mcp": MCP_VERSION,
        "openstudio": OPENSTUDIO_SDK_VERSION,
        "openstudio_cli": os_ver.strip(),
        "openstudio_python": openstudio.openStudioVersion(),
        "energyplus": eplus_ver,
        "ok": rc == 0,
    }
