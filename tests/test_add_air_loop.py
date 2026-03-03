import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_add_air_loop") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_add_air_loop_minimal():
    """Test adding an air loop with no zones."""
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

                # Add air loop
                air_loop_resp = await session.call_tool("add_air_loop", {"name": "New VAV System"})
                air_loop_result = unwrap(air_loop_resp)

                assert air_loop_result.get("ok") is True
                assert air_loop_result["air_loop"]["name"] == "New VAV System"
                assert "handle" in air_loop_result["air_loop"]
                assert air_loop_result["air_loop"]["num_thermal_zones"] == 0

                # Verify it appears in list
                list_resp = await session.call_tool("list_air_loops", {})
                list_result = unwrap(list_resp)
                assert any(a["name"] == "New VAV System" for a in list_result["air_loops"])

    asyncio.run(_run())


@pytest.mark.integration
def test_add_air_loop_with_zones():
    """Test adding an air loop with zones assigned."""
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

                # Get existing thermal zones
                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_result = unwrap(zones_resp)
                assert len(zones_result["thermal_zones"]) > 0
                zone_names = [zones_result["thermal_zones"][0]["name"]]

                # Add air loop with zones
                air_loop_resp = await session.call_tool("add_air_loop", {
                    "name": "New VAV System",
                    "thermal_zone_names": zone_names,
                })
                air_loop_result = unwrap(air_loop_resp)

                assert air_loop_result.get("ok") is True
                assert air_loop_result["air_loop"]["num_thermal_zones"] == 1
                assert zone_names[0] in air_loop_result["air_loop"]["thermal_zones"]

    asyncio.run(_run())


@pytest.mark.integration
def test_add_air_loop_verify_zone_connection():
    """Test that zone connection is reflected in air loop details."""
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

                # Create a new space and thermal zone
                space_resp = await session.call_tool("create_space", {"name": "Test Space"})
                assert unwrap(space_resp).get("ok") is True

                zone_resp = await session.call_tool("create_thermal_zone", {
                    "name": "Test Zone",
                    "space_names": ["Test Space"],
                })
                assert unwrap(zone_resp).get("ok") is True

                # Add air loop with the zone
                air_loop_resp = await session.call_tool("add_air_loop", {
                    "name": "Test VAV",
                    "thermal_zone_names": ["Test Zone"],
                })
                air_loop_result = unwrap(air_loop_resp)
                assert air_loop_result.get("ok") is True

                # Get air loop details
                details_resp = await session.call_tool("get_air_loop_details", {"air_loop_name": "Test VAV"})
                details_result = unwrap(details_resp)
                assert details_result.get("ok") is True
                assert "Test Zone" in details_result["air_loop"]["thermal_zones"]

    asyncio.run(_run())


@pytest.mark.integration
def test_add_air_loop_no_model_loaded():
    """Test error when no model is loaded."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to add air loop without loading model
                air_loop_resp = await session.call_tool("add_air_loop", {"name": "Should Fail"})
                air_loop_result = unwrap(air_loop_resp)

                assert air_loop_result.get("ok") is False
                assert "error" in air_loop_result
                assert "No model loaded" in air_loop_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_add_air_loop_invalid_zone():
    """Test error when thermal zone doesn't exist."""
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

                # Add air loop with invalid zone
                air_loop_resp = await session.call_tool("add_air_loop", {
                    "name": "New VAV System",
                    "thermal_zone_names": ["NonexistentZone"],
                })
                air_loop_result = unwrap(air_loop_resp)

                assert air_loop_result.get("ok") is False
                assert "error" in air_loop_result
                assert "not found" in air_loop_result["error"]

    asyncio.run(_run())
