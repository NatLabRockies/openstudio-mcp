import asyncio
import os
import uuid

import pytest

from conftest import unwrap, integration_enabled, server_params
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_create_space") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_create_space_minimal():
    """Test creating a space with minimal parameters."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Create space
                space_resp = await session.call_tool("create_space", {"name": "New Office"})
                space_result = unwrap(space_resp)

                assert space_result.get("ok") is True
                assert space_result["space"]["name"] == "New Office"
                assert "handle" in space_result["space"]
                assert space_result["space"]["floor_area_m2"] == 0.0  # No surfaces yet

                # Verify it appears in list
                list_resp = await session.call_tool("list_spaces", {})
                list_result = unwrap(list_resp)
                assert any(s["name"] == "New Office" for s in list_result["spaces"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_space_with_building_story():
    """Test creating a space with building story assigned."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Get existing building story
                stories_resp = await session.call_tool("list_building_stories", {})
                stories_result = unwrap(stories_resp)
                assert stories_result.get("ok") is True
                assert len(stories_result["building_stories"]) > 0
                story_name = stories_result["building_stories"][0]["name"]

                # Create space with building story
                space_resp = await session.call_tool("create_space", {
                    "name": "New Office",
                    "building_story_name": story_name
                })
                space_result = unwrap(space_resp)

                assert space_result.get("ok") is True
                assert space_result["space"]["building_story"] == story_name

                # Independent query verification
                sd = unwrap(await session.call_tool("get_space_details", {
                    "space_name": "New Office"
                }))
                assert sd["space"]["building_story"] == story_name

    asyncio.run(_run())


@pytest.mark.integration
def test_create_space_with_space_type():
    """Test creating a space with space type assigned."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Get existing space type
                space_types_resp = await session.call_tool("list_space_types", {})
                space_types_result = unwrap(space_types_resp)
                assert space_types_result.get("ok") is True
                assert len(space_types_result["space_types"]) > 0
                space_type_name = space_types_result["space_types"][0]["name"]

                # Create space with space type
                space_resp = await session.call_tool("create_space", {
                    "name": "New Office",
                    "space_type_name": space_type_name
                })
                space_result = unwrap(space_resp)

                assert space_result.get("ok") is True
                assert space_result["space"]["space_type"] == space_type_name

                # Independent query verification
                sd = unwrap(await session.call_tool("get_space_details", {
                    "space_name": "New Office"
                }))
                assert sd["space"]["space_type"] == space_type_name

    asyncio.run(_run())


@pytest.mark.integration
def test_create_space_no_model_loaded():
    """Test error when no model is loaded."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to create space without loading model
                space_resp = await session.call_tool("create_space", {"name": "Should Fail"})
                space_result = unwrap(space_resp)

                assert space_result.get("ok") is False
                assert "error" in space_result
                assert "No model loaded" in space_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_create_space_invalid_building_story():
    """Test error when building story doesn't exist."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Create space with invalid building story
                space_resp = await session.call_tool("create_space", {
                    "name": "New Office",
                    "building_story_name": "NonexistentStory"
                })
                space_result = unwrap(space_resp)

                assert space_result.get("ok") is False
                assert "error" in space_result
                assert "not found" in space_result["error"]

    asyncio.run(_run())
