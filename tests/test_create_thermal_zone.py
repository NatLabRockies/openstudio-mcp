import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_create_tz") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_create_thermal_zone_minimal():
    """Test creating a thermal zone with no spaces."""
    # Validates: create_thermal_zone creates empty zone visible in list_thermal_zones
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
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # Create thermal zone
                zone_resp = await session.call_tool("create_thermal_zone", {"name": "New Zone"})
                zone_result = unwrap(zone_resp)

                assert zone_result["ok"] is True
                assert zone_result["thermal_zone"]["name"] == "New Zone"
                assert zone_result["thermal_zone"]["num_equipment"] == 0

                # Verify it appears in list
                list_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                list_result = unwrap(list_resp)
                assert any(z["name"] == "New Zone" for z in list_result["thermal_zones"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_thermal_zone_with_spaces():
    """Test creating a thermal zone with spaces assigned."""
    # Validates: create_thermal_zone assigns existing space to new zone
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
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # Get existing spaces
                spaces_resp = await session.call_tool("list_spaces", {"max_results": 0})
                spaces_result = unwrap(spaces_resp)
                assert len(spaces_result["spaces"]) == 4, "Example model should have 4 spaces"
                space_names = [spaces_result["spaces"][0]["name"]]

                # Create thermal zone with spaces
                zone_resp = await session.call_tool("create_thermal_zone", {
                    "name": "New Zone",
                    "space_names": space_names,
                })
                zone_result = unwrap(zone_resp)

                assert zone_result["ok"] is True
                assert zone_result["thermal_zone"]["name"] == "New Zone"

                # Independent query verification
                sd = unwrap(await session.call_tool("get_space_details", {
                    "space_name": space_names[0],
                }))
                assert sd["space"]["thermal_zone"] == "New Zone"

    asyncio.run(_run())


@pytest.mark.integration
def test_create_thermal_zone_verify_space_assignment():
    """Test that space assignment is reflected in space details."""
    # Validates: space thermal_zone field reflects the zone it was assigned to
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
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # Create a new space
                space_resp = await session.call_tool("create_space", {"name": "Test Space"})
                space_result = unwrap(space_resp)
                assert space_result["ok"] is True

                # Create thermal zone with the space
                zone_resp = await session.call_tool("create_thermal_zone", {
                    "name": "Test Zone",
                    "space_names": ["Test Space"],
                })
                zone_result = unwrap(zone_resp)
                assert zone_result["ok"] is True

                # Check space details shows the zone
                space_details_resp = await session.call_tool("get_space_details", {"space_name": "Test Space"})
                space_details = unwrap(space_details_resp)
                assert space_details["ok"] is True
                assert space_details["space"]["thermal_zone"] == "Test Zone"

    asyncio.run(_run())


@pytest.mark.integration
def test_create_thermal_zone_no_model_loaded():
    """Test error when no model is loaded."""
    # Validates: create_thermal_zone returns "No model loaded" error without prior load
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to create thermal zone without loading model
                zone_resp = await session.call_tool("create_thermal_zone", {"name": "Should Fail"})
                zone_result = unwrap(zone_resp)

                assert zone_result["ok"] is False
                assert "No model loaded" in zone_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_create_thermal_zone_invalid_space():
    """Test error when space doesn't exist."""
    # Validates: create_thermal_zone returns "not found" for nonexistent space name
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
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # Create thermal zone with invalid space
                zone_resp = await session.call_tool("create_thermal_zone", {
                    "name": "New Zone",
                    "space_names": ["NonexistentSpace"],
                })
                zone_result = unwrap(zone_resp)

                assert zone_result["ok"] is False
                assert "not found" in zone_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_create_thermal_zone_json_string_spaces():
    """Test create_thermal_zone accepts space_names as JSON string."""
    # Regression: MCP clients sent space_names as JSON string, caused TypeError
    import json

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})

                spaces_resp = await session.call_tool("list_spaces", {"max_results": 0})
                space_name = unwrap(spaces_resp)["spaces"][0]["name"]

                zone_resp = await session.call_tool("create_thermal_zone", {
                    "name": "JSON Test Zone",
                    "space_names": json.dumps([space_name]),
                })
                zone_result = unwrap(zone_resp)

                assert zone_result["ok"] is True, (
                    f"JSON-string space_names failed: {zone_result.get('error')}"
                )

    asyncio.run(_run())
