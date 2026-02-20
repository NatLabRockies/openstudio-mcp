import asyncio
import json
import os
import shlex
import uuid

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _integration_enabled() -> bool:
    return os.environ.get("RUN_OPENSTUDIO_INTEGRATION", "").strip() in ("1", "true", "TRUE", "yes", "YES")


def _unwrap(res):
    if isinstance(res, dict):
        return res
    content = getattr(res, "content", None)
    if not content:
        return res
    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        return str(first)
    t = text.strip()
    if not t:
        return t
    try:
        return json.loads(t)
    except Exception:
        return t


def _unique_name(prefix: str = "pytest_spaces") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_list_spaces():
    """Test listing all spaces."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    name = _unique_name()

    async def _run():
        server_params = StdioServerParameters(
            command=server_cmd,
            args=server_args,
            env=os.environ.copy(),
        )

        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            # Create and load model
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_result = _unwrap(create_resp)
            assert create_result.get("ok") is True

            load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
            load_result = _unwrap(load_resp)
            assert load_result.get("ok") is True

            # List spaces
            spaces_resp = await session.call_tool("list_spaces", {})
            spaces_result = _unwrap(spaces_resp)

            assert isinstance(spaces_result, dict)
            assert spaces_result.get("ok") is True
            assert spaces_result["count"] == 4
            assert len(spaces_result["spaces"]) == 4
            assert "name" in spaces_result["spaces"][0]
            assert "floor_area_m2" in spaces_result["spaces"][0]

    asyncio.run(_run())


@pytest.mark.integration
def test_list_spaces_baseline():
    """Test listing spaces in 10-zone baseline model."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    name = _unique_name("pytest_bl_spaces")

    async def _run():
        server_params = StdioServerParameters(command=server_cmd, args=server_args, env=os.environ.copy())
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            cr = await session.call_tool("create_baseline_osm", {"name": name})
            cd = _unwrap(cr)
            assert cd.get("ok") is True, cd
            lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
            assert _unwrap(lr).get("ok") is True

            sr = await session.call_tool("list_spaces", {})
            sd = _unwrap(sr)
            print("baseline spaces:", sd)
            assert sd.get("ok") is True
            assert sd["count"] == 10  # 2 floors * 5 zones
            # Check perimeter/core naming
            names = [s["name"] for s in sd["spaces"]]
            assert any("Core" in n for n in names)
            assert any("Perimeter" in n for n in names)

    asyncio.run(_run())


@pytest.mark.integration
def test_thermal_zones_baseline():
    """Test listing thermal zones in baseline model."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    name = _unique_name("pytest_bl_zones")

    async def _run():
        server_params = StdioServerParameters(command=server_cmd, args=server_args, env=os.environ.copy())
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            cr = await session.call_tool("create_baseline_osm", {"name": name})
            cd = _unwrap(cr)
            assert cd.get("ok") is True, cd
            lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
            assert _unwrap(lr).get("ok") is True

            zr = await session.call_tool("list_thermal_zones", {})
            zd = _unwrap(zr)
            print("baseline zones:", zd)
            assert zd.get("ok") is True
            assert zd["count"] == 10
            # Each zone has 1 space
            for z in zd["thermal_zones"]:
                assert z["num_spaces"] == 1

    asyncio.run(_run())


@pytest.mark.integration
def test_list_thermal_zones():
    """Test listing all thermal zones."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    name = _unique_name()

    async def _run():
        server_params = StdioServerParameters(
            command=server_cmd,
            args=server_args,
            env=os.environ.copy(),
        )

        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            # Create and load model
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_result = _unwrap(create_resp)
            assert create_result.get("ok") is True

            load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
            load_result = _unwrap(load_resp)
            assert load_result.get("ok") is True

            # List zones
            zones_resp = await session.call_tool("list_thermal_zones", {})
            zones_result = _unwrap(zones_resp)

            assert isinstance(zones_result, dict)
            assert zones_result.get("ok") is True
            assert zones_result["count"] == 1
            assert "name" in zones_result["thermal_zones"][0]
            assert "num_spaces" in zones_result["thermal_zones"][0]

    asyncio.run(_run())
