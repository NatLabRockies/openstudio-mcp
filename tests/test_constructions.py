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


def _unique_name(prefix: str = "pytest_constructions") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_list_materials():
    """Test listing all materials."""
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

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = _unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = _unwrap(load_resp)
                assert load_result.get("ok") is True

                # List materials
                materials_resp = await session.call_tool("list_materials", {})
                materials_result = _unwrap(materials_resp)

                assert isinstance(materials_result, dict)
                assert materials_result.get("ok") is True
                assert materials_result["count"] > 0
                assert "name" in materials_result["materials"][0]
                assert "type" in materials_result["materials"][0]

    asyncio.run(_run())


@pytest.mark.integration
def test_list_constructions():
    """Test listing all constructions."""
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

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = _unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = _unwrap(load_resp)
                assert load_result.get("ok") is True

                # List constructions
                constructions_resp = await session.call_tool("list_constructions", {})
                constructions_result = _unwrap(constructions_resp)

                assert isinstance(constructions_result, dict)
                assert constructions_result.get("ok") is True
                assert constructions_result["count"] > 0
                assert "name" in constructions_result["constructions"][0]
                assert "layers" in constructions_result["constructions"][0]

    asyncio.run(_run())


@pytest.mark.integration
def test_constructions_baseline():
    """Test constructions in baseline model with full construction set."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    name = _unique_name("pytest_bl_constr")

    async def _run():
        server_params = StdioServerParameters(command=server_cmd, args=server_args, env=os.environ.copy())
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = _unwrap(cr)
                assert cd.get("ok") is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert _unwrap(lr).get("ok") is True

                # Materials — baseline has walls, roof, floor materials
                mr = await session.call_tool("list_materials", {})
                md = _unwrap(mr)
                print("baseline materials:", md)
                assert md.get("ok") is True
                assert md["count"] >= 5  # Multiple materials from construction library

                # Constructions
                cr2 = await session.call_tool("list_constructions", {})
                cd2 = _unwrap(cr2)
                print("baseline constructions:", cd2)
                assert cd2.get("ok") is True
                assert cd2["count"] >= 4  # Ext wall, roof, floor, int wall at minimum

                # Construction sets
                csr = await session.call_tool("list_construction_sets", {})
                csd = _unwrap(csr)
                print("baseline construction sets:", csd)
                assert csd.get("ok") is True
                assert csd["count"] >= 1  # DefaultConstructionSet from library

    asyncio.run(_run())
