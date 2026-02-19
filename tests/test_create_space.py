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


def _unique_name(prefix: str = "pytest_create_space") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_create_space_minimal():
    """Test creating a space with minimal parameters."""
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

                # Create space
                space_resp = await session.call_tool("create_space", {"name": "New Office"})
                space_result = _unwrap(space_resp)

                assert space_result.get("ok") is True
                assert space_result["space"]["name"] == "New Office"
                assert "handle" in space_result["space"]
                assert space_result["space"]["floor_area_m2"] == 0.0  # No surfaces yet

                # Verify it appears in list
                list_resp = await session.call_tool("list_spaces", {})
                list_result = _unwrap(list_resp)
                assert any(s["name"] == "New Office" for s in list_result["spaces"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_space_with_building_story():
    """Test creating a space with building story assigned."""
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

                # Get existing building story
                stories_resp = await session.call_tool("list_building_stories", {})
                stories_result = _unwrap(stories_resp)
                assert stories_result.get("ok") is True
                assert len(stories_result["building_stories"]) > 0
                story_name = stories_result["building_stories"][0]["name"]

                # Create space with building story
                space_resp = await session.call_tool("create_space", {
                    "name": "New Office",
                    "building_story_name": story_name
                })
                space_result = _unwrap(space_resp)

                assert space_result.get("ok") is True
                assert space_result["space"]["building_story"] == story_name

                # Independent query verification
                sd = _unwrap(await session.call_tool("get_space_details", {
                    "space_name": "New Office"
                }))
                assert sd["space"]["building_story"] == story_name

    asyncio.run(_run())


@pytest.mark.integration
def test_create_space_with_space_type():
    """Test creating a space with space type assigned."""
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

                # Get existing space type
                space_types_resp = await session.call_tool("list_space_types", {})
                space_types_result = _unwrap(space_types_resp)
                assert space_types_result.get("ok") is True
                assert len(space_types_result["space_types"]) > 0
                space_type_name = space_types_result["space_types"][0]["name"]

                # Create space with space type
                space_resp = await session.call_tool("create_space", {
                    "name": "New Office",
                    "space_type_name": space_type_name
                })
                space_result = _unwrap(space_resp)

                assert space_result.get("ok") is True
                assert space_result["space"]["space_type"] == space_type_name

                # Independent query verification
                sd = _unwrap(await session.call_tool("get_space_details", {
                    "space_name": "New Office"
                }))
                assert sd["space"]["space_type"] == space_type_name

    asyncio.run(_run())


@pytest.mark.integration
def test_create_space_no_model_loaded():
    """Test error when no model is loaded."""
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

                # Try to create space without loading model
                space_resp = await session.call_tool("create_space", {"name": "Should Fail"})
                space_result = _unwrap(space_resp)

                assert space_result.get("ok") is False
                assert "error" in space_result
                assert "No model loaded" in space_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_create_space_invalid_building_story():
    """Test error when building story doesn't exist."""
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

                # Create space with invalid building story
                space_resp = await session.call_tool("create_space", {
                    "name": "New Office",
                    "building_story_name": "NonexistentStory"
                })
                space_result = _unwrap(space_resp)

                assert space_result.get("ok") is False
                assert "error" in space_result
                assert "not found" in space_result["error"]

    asyncio.run(_run())
