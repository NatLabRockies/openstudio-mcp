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


def _unique_name(prefix: str = "pytest_create_tz") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_create_thermal_zone_minimal():
    """Test creating a thermal zone with no spaces."""
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

            # Create thermal zone
            zone_resp = await session.call_tool("create_thermal_zone", {"name": "New Zone"})
            zone_result = _unwrap(zone_resp)

            assert zone_result.get("ok") is True
            assert zone_result["thermal_zone"]["name"] == "New Zone"
            assert "handle" in zone_result["thermal_zone"]
            assert zone_result["thermal_zone"]["num_spaces"] == 0

            # Verify it appears in list
            list_resp = await session.call_tool("list_thermal_zones", {})
            list_result = _unwrap(list_resp)
            assert any(z["name"] == "New Zone" for z in list_result["thermal_zones"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_thermal_zone_with_spaces():
    """Test creating a thermal zone with spaces assigned."""
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

            # Get existing spaces
            spaces_resp = await session.call_tool("list_spaces", {})
            spaces_result = _unwrap(spaces_resp)
            assert len(spaces_result["spaces"]) > 0
            space_names = [spaces_result["spaces"][0]["name"]]

            # Create thermal zone with spaces
            zone_resp = await session.call_tool(
                "create_thermal_zone",
                {
                    "name": "New Zone",
                    "space_names": space_names,
                },
            )
            zone_result = _unwrap(zone_resp)

            assert zone_result.get("ok") is True
            assert zone_result["thermal_zone"]["num_spaces"] == 1

            # Independent query verification
            sd = _unwrap(
                await session.call_tool(
                    "get_space_details",
                    {
                        "space_name": space_names[0],
                    },
                ),
            )
            assert sd["space"]["thermal_zone"] == "New Zone"

    asyncio.run(_run())


@pytest.mark.integration
def test_create_thermal_zone_verify_space_assignment():
    """Test that space assignment is reflected in space details."""
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

            # Create a new space
            space_resp = await session.call_tool("create_space", {"name": "Test Space"})
            space_result = _unwrap(space_resp)
            assert space_result.get("ok") is True

            # Create thermal zone with the space
            zone_resp = await session.call_tool(
                "create_thermal_zone",
                {
                    "name": "Test Zone",
                    "space_names": ["Test Space"],
                },
            )
            zone_result = _unwrap(zone_resp)
            assert zone_result.get("ok") is True

            # Check space details shows the zone
            space_details_resp = await session.call_tool("get_space_details", {"space_name": "Test Space"})
            space_details = _unwrap(space_details_resp)
            assert space_details.get("ok") is True
            assert space_details["space"]["thermal_zone"] == "Test Zone"

    asyncio.run(_run())


@pytest.mark.integration
def test_create_thermal_zone_no_model_loaded():
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

        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            # Try to create thermal zone without loading model
            zone_resp = await session.call_tool("create_thermal_zone", {"name": "Should Fail"})
            zone_result = _unwrap(zone_resp)

            assert zone_result.get("ok") is False
            assert "error" in zone_result
            assert "No model loaded" in zone_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_create_thermal_zone_invalid_space():
    """Test error when space doesn't exist."""
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

            # Create thermal zone with invalid space
            zone_resp = await session.call_tool(
                "create_thermal_zone",
                {
                    "name": "New Zone",
                    "space_names": ["NonexistentSpace"],
                },
            )
            zone_result = _unwrap(zone_resp)

            assert zone_result.get("ok") is False
            assert "error" in zone_result
            assert "not found" in zone_result["error"]

    asyncio.run(_run())
