"""Integration tests for space_types skill."""
import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_space_types") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_list_space_types():
    """Test listing all space types via list_model_objects."""
    # Validates: list_model_objects(SpaceType) returns space types from example model
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # List space types via generic list_model_objects
                space_types_result = unwrap(await session.call_tool("list_model_objects", {"object_type": "SpaceType"}))
                print("list_model_objects(SpaceType):", space_types_result)

                assert space_types_result["ok"] is True, space_types_result
                assert space_types_result["count"] > 0, "Example model should have at least one space type"
                assert isinstance(space_types_result["objects"], list)

                space_type = space_types_result["objects"][0]
                assert len(space_type["name"]) > 0, "Space type should have a non-empty name"

                print(f"Found {space_types_result['count']} space types")
                print(f"First space type: {space_type['name']}")

    asyncio.run(_run())


@pytest.mark.integration
def test_get_space_type_details():
    """Test getting details for a specific space type."""
    # Validates: get_space_type_details returns load categories and associated spaces
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # First list space types to get a valid name
                list_result = unwrap(await session.call_tool("list_model_objects", {"object_type": "SpaceType"}))
                assert list_result["ok"] is True
                assert list_result["count"] > 0, "Need at least one space type for this test"

                space_type_name = list_result["objects"][0]["name"]

                # Get details for the first space type
                details_result = unwrap(await session.call_tool("get_space_type_details", {"space_type_name": space_type_name}))
                print("get_space_type_details:", details_result)

                assert details_result["ok"] is True, details_result

                space_type = details_result["space_type"]
                assert space_type["name"] == space_type_name
                # Verify all load category lists are present (may be empty)
                assert isinstance(space_type["people_loads"], list)
                assert isinstance(space_type["lighting_loads"], list)
                assert isinstance(space_type["electric_equipment_loads"], list)
                assert isinstance(space_type["gas_equipment_loads"], list)
                assert isinstance(space_type["spaces"], list)

                print(f"Space type '{space_type_name}' has:")
                print(f"  - {len(space_type['people_loads'])} people loads")
                print(f"  - {len(space_type['lighting_loads'])} lighting loads")
                print(f"  - {len(space_type['electric_equipment_loads'])} electric equipment loads")
                print(f"  - {len(space_type['spaces'])} spaces using this type")

    asyncio.run(_run())


@pytest.mark.integration
def test_get_space_type_details_not_found():
    """Test getting details for a non-existent space type."""
    # Validates: get_space_type_details returns error for nonexistent space type
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # Try to get non-existent space type
                details_result = unwrap(await session.call_tool("get_space_type_details", {"space_type_name": "NonExistentSpaceType"}))
                print("get_space_type_details (not found):", details_result)

                assert details_result["ok"] is False
                assert "not found" in details_result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_space_types_tools_without_loaded_model():
    """Test that space type tools fail gracefully when no model is loaded."""
    # Validates: list_model_objects returns error when no model loaded
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to list space types without loading a model
                space_types_result = unwrap(await session.call_tool("list_model_objects", {"object_type": "SpaceType"}))
                print("list_model_objects(SpaceType, no model):", space_types_result)

                assert space_types_result["ok"] is False
                assert "no model loaded" in space_types_result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_space_types_baseline():
    """Test space types in baseline model with loads attached."""
    # Validates: baseline model has Baseline space type assigned to all 10 zones
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_stypes")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cd = unwrap(await session.call_tool("create_baseline_osm", {"name": name}))
                assert cd["ok"] is True, cd
                assert unwrap(await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]}))["ok"] is True

                sd = unwrap(await session.call_tool("list_model_objects", {"object_type": "SpaceType"}))
                print("baseline space types:", sd)
                assert sd["ok"] is True
                assert sd["count"] >= 1

                # Find Baseline Model Space Type
                bl_st = None
                for st in sd["objects"]:
                    if "Baseline" in st["name"]:
                        bl_st = st
                        break
                assert bl_st is not None, "Expected 'Baseline Model Space Type' in baseline model"

                # Get details
                dd = unwrap(await session.call_tool("get_space_type_details", {"space_type_name": bl_st["name"]}))
                assert dd["ok"] is True
                assert len(dd["space_type"]["spaces"]) == 10, (
                    f"All 10 baseline zones should use this type, got {len(dd['space_type']['spaces'])}"
                )

    asyncio.run(_run())
