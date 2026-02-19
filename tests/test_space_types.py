"""Integration tests for space_types skill."""
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


def _unique_name(prefix: str = "pytest_space_types") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_list_space_types():
    """Test listing all space types."""
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

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = _unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = _unwrap(load_resp)
                assert load_result.get("ok") is True

                # List space types
                space_types_resp = await session.call_tool("list_space_types", {})
                space_types_result = _unwrap(space_types_resp)
                print("list_space_types:", space_types_result)

                assert isinstance(space_types_result, dict)
                assert space_types_result.get("ok") is True, space_types_result
                assert "count" in space_types_result
                assert "space_types" in space_types_result
                assert isinstance(space_types_result["space_types"], list)

                # Example model has at least one space type
                assert space_types_result["count"] > 0, "Expected at least one space type"

                if space_types_result["space_types"]:
                    space_type = space_types_result["space_types"][0]
                    assert "handle" in space_type
                    assert "name" in space_type
                    assert "num_people" in space_type
                    assert "num_lights" in space_type
                    assert "num_electric_equipment" in space_type

                    print(f"Found {space_types_result['count']} space types")
                    print(f"First space type: {space_type['name']}")

    asyncio.run(_run())


@pytest.mark.integration
def test_get_space_type_details():
    """Test getting details for a specific space type."""
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

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = _unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = _unwrap(load_resp)
                assert load_result.get("ok") is True

                # First list space types to get a valid name
                list_resp = await session.call_tool("list_space_types", {})
                list_result = _unwrap(list_resp)
                assert list_result.get("ok") is True
                assert list_result["count"] > 0, "Need at least one space type for this test"

                space_type_name = list_result["space_types"][0]["name"]

                # Get details for the first space type
                details_resp = await session.call_tool("get_space_type_details", {"space_type_name": space_type_name})
                details_result = _unwrap(details_resp)
                print("get_space_type_details:", details_result)

                assert isinstance(details_result, dict)
                assert details_result.get("ok") is True, details_result
                assert "space_type" in details_result

                space_type = details_result["space_type"]
                assert space_type["name"] == space_type_name
                assert "people_loads" in space_type
                assert "lighting_loads" in space_type
                assert "electric_equipment_loads" in space_type
                assert "gas_equipment_loads" in space_type
                assert "spaces" in space_type

                print(f"Space type '{space_type_name}' has:")
                print(f"  - {len(space_type['people_loads'])} people loads")
                print(f"  - {len(space_type['lighting_loads'])} lighting loads")
                print(f"  - {len(space_type['electric_equipment_loads'])} electric equipment loads")
                print(f"  - {len(space_type['spaces'])} spaces using this type")

    asyncio.run(_run())


@pytest.mark.integration
def test_get_space_type_details_not_found():
    """Test getting details for a non-existent space type."""
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

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = _unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = _unwrap(load_resp)
                assert load_result.get("ok") is True

                # Try to get non-existent space type
                details_resp = await session.call_tool("get_space_type_details", {"space_type_name": "NonExistentSpaceType"})
                details_result = _unwrap(details_resp)
                print("get_space_type_details (not found):", details_result)

                assert isinstance(details_result, dict)
                assert details_result.get("ok") is False
                assert "error" in details_result
                assert "not found" in details_result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_space_types_tools_without_loaded_model():
    """Test that space type tools fail gracefully when no model is loaded."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    async def _run():
        server_params = StdioServerParameters(
            command=server_cmd,
            args=server_args,
            env=os.environ.copy(),
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to list space types without loading a model
                space_types_resp = await session.call_tool("list_space_types", {})
                space_types_result = _unwrap(space_types_resp)
                print("list_space_types (no model):", space_types_result)

                assert isinstance(space_types_result, dict)
                assert space_types_result.get("ok") is False
                assert "error" in space_types_result
                assert "no model loaded" in space_types_result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_space_types_baseline():
    """Test space types in baseline model with loads attached."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    name = _unique_name("pytest_bl_stypes")

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

                sr = await session.call_tool("list_space_types", {})
                sd = _unwrap(sr)
                print("baseline space types:", sd)
                assert sd.get("ok") is True
                assert sd["count"] >= 1

                # Find Baseline Model Space Type
                bl_st = None
                for st in sd["space_types"]:
                    if "Baseline" in st["name"]:
                        bl_st = st
                        break
                assert bl_st is not None, "Expected 'Baseline Model Space Type'"
                assert bl_st["num_people"] >= 1
                assert bl_st["num_lights"] >= 1
                assert bl_st["num_electric_equipment"] >= 1

                # Get details
                dr = await session.call_tool("get_space_type_details", {"space_type_name": bl_st["name"]})
                dd = _unwrap(dr)
                assert dd.get("ok") is True
                assert len(dd["space_type"]["spaces"]) == 10  # All 10 spaces use this type

    asyncio.run(_run())
