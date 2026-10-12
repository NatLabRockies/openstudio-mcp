"""Shared test helpers — imported by individual test files.

Public API (no leading underscore):
  integration_enabled()  — check RUN_OPENSTUDIO_INTEGRATION env var
  unwrap(res)            — extract dict/str from MCP CallToolResult
  server_params()        — build StdioServerParameters from env vars
  poll_until_done(s, id) — async poll get_run_status until terminal state
  patch_set_vertices(mp, surface, factory) — fault-inject Surface.setVertices (in-process)
  EPW_PATH / POLL_SECONDS / SIM_TIMEOUT — simulation constants
"""
import asyncio
import contextlib
import json
import os
import shlex
import socket
import subprocess
import time
from contextlib import asynccontextmanager
from pathlib import Path

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


# ---------------------------------------------------------------------------
# In-process fault injection — geometry repair write guards
# ---------------------------------------------------------------------------

def patch_set_vertices(monkeypatch, surface, make_replacement) -> None:
    """Swap Surface.setVertices on whichever class in the SWIG MRO defines it.

    Patching the class rather than the instance is what makes this bite: the repair
    tools walk model.getSurfaces() and operate on fresh proxy objects, not the ones a
    test holds. `make_replacement` receives the original unbound function, so a fake can
    delegate to it (e.g. succeed once, then refuse).

    Deliberately no `openstudio` import — it walks type(surface).__mro__ instead — so
    conftest stays importable from unit-test contexts that must not load the SDK.

    Only usable from in-process tests. Tests driving the MCP stdio server run the code
    under test in a subprocess this cannot reach.
    """
    target = next(c for c in type(surface).__mro__ if "setVertices" in c.__dict__)
    monkeypatch.setattr(target, "setVertices", make_replacement(target.setVertices))


# ---------------------------------------------------------------------------
# HTTP (streamable) transport harness — multi-user isolation tests
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def http_server(env_overrides: dict | None = None, port: int | None = None):
    """Spawn the MCP server in streamable-HTTP mode; yield (url, proc).

    Runs inside the same host as pytest, so the client connects to 127.0.0.1 —
    no published Docker port needed.
    """
    port = port or _free_port()
    cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    args = shlex.split(os.environ.get("MCP_SERVER_ARGS", "") or "")
    env = os.environ.copy()
    env.update({
        "MCP_TRANSPORT": "http", "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(port), "MCP_PATH": "/mcp",
        # Disable the auto-GC daemon by default so the suite never reclaims the
        # shared /runs out from under other tests; retention tests opt in.
        "OSMCP_RUN_RETENTION_DAYS": "0",
    })
    if env_overrides:
        env.update(env_overrides)

    run_root = Path(os.environ.get("OPENSTUDIO_MCP_RUN_ROOT",
                                   os.environ.get("OSMCP_RUN_ROOT", "/runs")))
    run_root.mkdir(parents=True, exist_ok=True)
    log_path = run_root / f"_httpsrv_{port}.log"
    logf = log_path.open("w")
    proc = subprocess.Popen(  # noqa: S603 - cmd is the trusted MCP_SERVER_CMD
        [cmd, *args], env=env, stdout=logf, stderr=subprocess.STDOUT,
    )

    def _tail() -> str:
        try:
            return "\n".join(log_path.read_text(errors="replace").splitlines()[-30:])
        except Exception:
            return "(no server log)"

    try:
        deadline = time.time() + 60
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"HTTP server exited (code {proc.returncode}).\n{_tail()}")
            with socket.socket() as s:
                s.settimeout(0.5)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            if time.time() > deadline:
                raise TimeoutError(f"HTTP server not ready on :{port}.\n{_tail()}")
            time.sleep(0.3)
        yield f"http://127.0.0.1:{port}/mcp", proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        logf.close()


@asynccontextmanager
async def http_session(url: str, token: str | None = None):
    """Open an initialized MCP ClientSession over streamable HTTP."""
    # streamablehttp_client (deprecated alias) takes headers/auth directly;
    # streamable_http_client wants a pre-built httpx client instead.
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _get_sid):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session
