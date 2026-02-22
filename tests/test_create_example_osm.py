"""
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL="*" RUN_OPENSTUDIO_INTEGRATION=1 MCP_RUNS_HOST_DIR="/c/projects/openstudio-mcp/runs" MCP_SERVER_CMD=docker MCP_SERVER_ARGS="run --rm -i \
  -v /c/projects/openstudio-mcp/tests/assets/SEB_model:/inputs \
  -v /c/projects/openstudio-mcp/runs:/runs \
  -e OPENSTUDIO_MCP_MODE=prod \
  openstudio-mcp:dev openstudio-mcp" pytest -vv -s tests/test_create_example_osm.py
"""
import asyncio
import os
import uuid
from pathlib import Path

import pytest

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from conftest import unwrap, integration_enabled, server_params


def _normalize_host_runs_dir(host_runs: str) -> Path:
    """Normalize a host /runs directory path for the current OS.

    On Windows, users often pass MSYS paths like /c/projects/... which pathlib
    will treat as a POSIX-style absolute path and not resolve to the real drive.
    We translate common MSYS patterns to a Windows drive path.
    """
    host_runs = host_runs.strip()
    if not host_runs:
        return Path(host_runs)

    if os.name == "nt":
        # Convert MSYS-style '/c/...' or '/C/...' to 'C:\\...'
        if host_runs.startswith(("/", "\\")) and len(host_runs) >= 3 and host_runs[2] == "/":
            drive = host_runs[1]
            if drive.isalpha():
                rest = host_runs[3:]  # skip '/c/'
                host_runs = drive.upper() + ":\\" + rest.replace("/", "\\")
        # Also accept 'C:/foo/bar'
        host_runs = host_runs.replace("/", "\\")
    return Path(host_runs)


def _maybe_check_host_file_exists(container_osm_path: str) -> None:
    """Optionally assert the OSM exists on the host filesystem.

    Enable by setting MCP_RUNS_HOST_DIR to the host path that corresponds to the
    container's /runs mount.
    """
    host_runs_raw = os.environ.get("MCP_RUNS_HOST_DIR", "").strip()
    if not host_runs_raw:
        return

    host_runs = _normalize_host_runs_dir(host_runs_raw)

    if not container_osm_path.startswith("/runs/"):
        pytest.skip(f"Tool returned osm_path not under /runs: {container_osm_path}")

    rel = container_osm_path[len("/runs/") :].lstrip("/").replace("/", os.sep)
    host_path = host_runs / rel
    assert host_path.exists(), (
        f"Expected OSM to exist on host at: {host_path}\n"
        f"(MCP_RUNS_HOST_DIR was: {host_runs_raw} -> normalized to: {host_runs})\n"
        f"(container osm_path was: {container_osm_path})"
    )


def _unique_name(prefix: str = "pytest_example_model") -> str:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    token = uuid.uuid4().hex[:10]
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_create_example_osm_smoke():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resp = await session.call_tool("create_example_osm", {"name": name})
                result = unwrap(resp)

                # Helpful for local debugging / CI logs
                print("create_example_osm result:", result)
                assert isinstance(result, dict), f"Unexpected tool result type: {type(result)}"
                assert result.get("ok") is True, f"Tool returned ok!=true: {result}"

                osm_path = result.get("osm_path")
                assert osm_path, f"No osm_path returned: {result}"
                assert str(osm_path).endswith(".osm"), f"Expected .osm path, got: {osm_path}"
                assert str(osm_path).startswith("/runs/"), f"Expected osm_path under /runs, got: {osm_path}"

                _maybe_check_host_file_exists(str(osm_path))

    asyncio.run(_run())
