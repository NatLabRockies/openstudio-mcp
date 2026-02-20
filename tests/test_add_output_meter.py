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


def _unique_name(prefix: str = "pytest_output_meter") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_add_output_meter_default():
    """Test adding an output meter with default parameters."""
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

            # Add output meter
            meter_resp = await session.call_tool(
                "add_output_meter",
                {
                    "meter_name": "Electricity:Facility",
                },
            )
            meter_result = _unwrap(meter_resp)

            assert meter_result.get("ok") is True
            assert meter_result["output_meter"]["name"] == "Electricity:Facility"
            assert meter_result["output_meter"]["reporting_frequency"] == "Hourly"

    asyncio.run(_run())


@pytest.mark.integration
def test_add_output_meter_monthly():
    """Test adding an output meter with monthly reporting."""
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

            # Add output meter with monthly reporting
            meter_resp = await session.call_tool(
                "add_output_meter",
                {
                    "meter_name": "Gas:Facility",
                    "reporting_frequency": "Monthly",
                },
            )
            meter_result = _unwrap(meter_resp)

            assert meter_result.get("ok") is True
            assert meter_result["output_meter"]["reporting_frequency"] == "Monthly"

    asyncio.run(_run())


@pytest.mark.integration
def test_add_output_meter_no_model_loaded():
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

            # Try to add output meter without loading model
            meter_resp = await session.call_tool(
                "add_output_meter",
                {
                    "meter_name": "Electricity:Facility",
                },
            )
            meter_result = _unwrap(meter_resp)

            assert meter_result.get("ok") is False
            assert "error" in meter_result
            assert "No model loaded" in meter_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_add_multiple_output_meters():
    """Test adding multiple output meters."""
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

            # Add electricity meter
            elec_resp = await session.call_tool(
                "add_output_meter",
                {
                    "meter_name": "Electricity:Facility",
                },
            )
            elec_result = _unwrap(elec_resp)
            assert elec_result.get("ok") is True

            # Add gas meter
            gas_resp = await session.call_tool(
                "add_output_meter",
                {
                    "meter_name": "Gas:Facility",
                },
            )
            gas_result = _unwrap(gas_resp)
            assert gas_result.get("ok") is True

            # Both should have unique handles
            assert elec_result["output_meter"]["handle"] != gas_result["output_meter"]["handle"]

    asyncio.run(_run())


@pytest.mark.integration
def test_add_heating_cooling_meters():
    """Test adding heating and cooling meters."""
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

            # Add heating electricity meter
            heating_resp = await session.call_tool(
                "add_output_meter",
                {
                    "meter_name": "Heating:Electricity",
                },
            )
            heating_result = _unwrap(heating_resp)
            assert heating_result.get("ok") is True

            # Add cooling electricity meter
            cooling_resp = await session.call_tool(
                "add_output_meter",
                {
                    "meter_name": "Cooling:Electricity",
                },
            )
            cooling_result = _unwrap(cooling_resp)
            assert cooling_result.get("ok") is True

    asyncio.run(_run())
