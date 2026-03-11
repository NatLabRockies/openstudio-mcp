"""Shared test helpers — imported by individual test files.

Public API (no leading underscore):
  integration_enabled()  — check RUN_OPENSTUDIO_INTEGRATION env var
  unwrap(res)            — extract dict/str from MCP CallToolResult
  server_params()        — build StdioServerParameters from env vars
  poll_until_done(s, id) — async poll get_run_status until terminal state
  EPW_PATH / POLL_SECONDS / SIM_TIMEOUT — simulation constants
"""
import asyncio
import json
import os
import shlex
import time

from mcp import StdioServerParameters


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: marks tests that run OpenStudio simulations")


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def integration_enabled() -> bool:
    """True when RUN_OPENSTUDIO_INTEGRATION is set to a truthy value."""
    return os.environ.get("RUN_OPENSTUDIO_INTEGRATION", "").strip() in (
        "1", "true", "TRUE", "yes", "YES",
    )


# ---------------------------------------------------------------------------
# MCP result unwrapping (Pattern A — getattr-based, most robust)
# ---------------------------------------------------------------------------

def unwrap(res):
    """Extract a dict (or string) from a CallToolResult."""
    content = getattr(res, "content", None)
    if not content:
        return res if isinstance(res, dict) else {"_raw": str(res)}
    text = getattr(content[0], "text", None)
    if text is None:
        return str(content[0])
    try:
        return json.loads(text.strip())
    except Exception:
        return text.strip()


# ---------------------------------------------------------------------------
# Server connection
# ---------------------------------------------------------------------------

def server_params() -> StdioServerParameters:
    """Build StdioServerParameters from MCP_SERVER_CMD / MCP_SERVER_ARGS env."""
    cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    args = shlex.split(args_env) if args_env else []
    return StdioServerParameters(command=cmd, args=args, env=os.environ.copy())


# ---------------------------------------------------------------------------
# Simulation polling
# ---------------------------------------------------------------------------

# EPW with companion .stat + .ddy (required by ChangeBuildingLocation measure)
EPW_PATH = (
    "/opt/comstock-measures/ChangeBuildingLocation"
    "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
)
POLL_SECONDS = float(os.environ.get("MCP_POLL_SECONDS", "3"))
SIM_TIMEOUT = float(os.environ.get("MCP_SIM_TIMEOUT", str(60 * 20)))


async def poll_until_done(s, run_id: str) -> dict:
    """Poll get_run_status until the run reaches a terminal state."""
    terminal = {"success", "failed", "error", "cancelled"}
    started = time.time()
    while True:
        if time.time() - started > SIM_TIMEOUT:
            raise AssertionError(f"Simulation timed out after {SIM_TIMEOUT}s")
        status = unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))
        state = (status.get("run", {}).get("status") or "unknown").lower()
        if state in terminal:
            return status
        await asyncio.sleep(POLL_SECONDS)


# ---------------------------------------------------------------------------
# Model setup helpers (shared across integration tests)
# ---------------------------------------------------------------------------

async def create_and_load(session, name):
    """Create example model, load it, return zone names."""
    cr = await session.call_tool("create_example_osm", {"name": name})
    cd = unwrap(cr)
    assert cd.get("ok") is True, cd
    lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
    assert unwrap(lr).get("ok") is True
    zr = await session.call_tool("list_thermal_zones", {"max_results": 0})
    zd = unwrap(zr)
    return [z["name"] for z in zd["thermal_zones"]]


async def create_baseline_and_load(session, name):
    """Create baseline 10-zone model, load it, return zone names."""
    cr = await session.call_tool("create_baseline_osm", {"name": name})
    cd = unwrap(cr)
    assert cd.get("ok") is True, cd
    lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
    assert unwrap(lr).get("ok") is True
    zr = await session.call_tool("list_thermal_zones", {"max_results": 0})
    zd = unwrap(zr)
    return [z["name"] for z in zd["thermal_zones"]]


async def setup_example(session, model_name):
    """Create and load example model."""
    cr = unwrap(await session.call_tool("create_example_osm", {"name": model_name}))
    assert cr.get("ok") is True
    lr = unwrap(await session.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr.get("ok") is True
