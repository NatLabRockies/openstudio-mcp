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


def _unique_name(prefix: str = "pytest_output_var") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_add_output_variable_default():
    """Test adding an output variable with default parameters."""
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

                # Add output variable
                output_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Mean Air Temperature"
                })
                output_result = _unwrap(output_resp)

                assert output_result.get("ok") is True
                assert output_result["output_variable"]["variable_name"] == "Zone Mean Air Temperature"
                assert output_result["output_variable"]["key_value"] == "*"
                assert output_result["output_variable"]["reporting_frequency"] == "Hourly"

    asyncio.run(_run())


@pytest.mark.integration
def test_add_output_variable_with_key():
    """Test adding an output variable for a specific object."""
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

                # Get a thermal zone name
                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_result = _unwrap(zones_resp)
                assert len(zones_result["thermal_zones"]) > 0
                zone_name = zones_result["thermal_zones"][0]["name"]

                # Add output variable for specific zone
                output_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Mean Air Temperature",
                    "key_value": zone_name
                })
                output_result = _unwrap(output_resp)

                assert output_result.get("ok") is True
                assert output_result["output_variable"]["key_value"] == zone_name

    asyncio.run(_run())


@pytest.mark.integration
def test_add_output_variable_monthly():
    """Test adding an output variable with monthly reporting."""
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

                # Add output variable with monthly reporting
                output_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Surface Outside Face Temperature",
                    "reporting_frequency": "Monthly"
                })
                output_result = _unwrap(output_resp)

                assert output_result.get("ok") is True
                assert output_result["output_variable"]["reporting_frequency"] == "Monthly"

    asyncio.run(_run())


@pytest.mark.integration
def test_add_output_variable_no_model_loaded():
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

                # Try to add output variable without loading model
                output_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Mean Air Temperature"
                })
                output_result = _unwrap(output_resp)

                assert output_result.get("ok") is False
                assert "error" in output_result
                assert "No model loaded" in output_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_add_multiple_output_variables():
    """Test adding multiple output variables."""
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

                # Add multiple output variables
                var1_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Mean Air Temperature"
                })
                var1_result = _unwrap(var1_resp)
                assert var1_result.get("ok") is True

                var2_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Air System Sensible Heating Rate"
                })
                var2_result = _unwrap(var2_resp)
                assert var2_result.get("ok") is True

                # Both should have unique handles
                assert var1_result["output_variable"]["handle"] != var2_result["output_variable"]["handle"]

    asyncio.run(_run())
