import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_output_meter") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_add_output_meter_default():
    """Test adding an output meter with default parameters."""
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

                # Add output meter
                meter_resp = await session.call_tool("add_output_meter", {
                    "meter_name": "Electricity:Facility",
                })
                meter_result = unwrap(meter_resp)

                assert meter_result.get("ok") is True
                assert meter_result["output_meter"]["name"] == "Electricity:Facility"
                assert meter_result["output_meter"]["reporting_frequency"] == "Hourly"

    asyncio.run(_run())


@pytest.mark.integration
def test_add_output_meter_monthly():
    """Test adding an output meter with monthly reporting."""
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

                # Add output meter with monthly reporting
                meter_resp = await session.call_tool("add_output_meter", {
                    "meter_name": "Gas:Facility",
                    "reporting_frequency": "Monthly",
                })
                meter_result = unwrap(meter_resp)

                assert meter_result.get("ok") is True
                assert meter_result["output_meter"]["reporting_frequency"] == "Monthly"

    asyncio.run(_run())


@pytest.mark.integration
def test_add_output_meter_no_model_loaded():
    """Test error when no model is loaded."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to add output meter without loading model
                meter_resp = await session.call_tool("add_output_meter", {
                    "meter_name": "Electricity:Facility",
                })
                meter_result = unwrap(meter_resp)

                assert meter_result.get("ok") is False
                assert "error" in meter_result
                assert "No model loaded" in meter_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_add_multiple_output_meters():
    """Test adding multiple output meters."""
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

                # Add electricity meter
                elec_resp = await session.call_tool("add_output_meter", {
                    "meter_name": "Electricity:Facility",
                })
                elec_result = unwrap(elec_resp)
                assert elec_result.get("ok") is True

                # Add gas meter
                gas_resp = await session.call_tool("add_output_meter", {
                    "meter_name": "Gas:Facility",
                })
                gas_result = unwrap(gas_resp)
                assert gas_result.get("ok") is True

                # Both should have unique handles
                assert elec_result["output_meter"]["handle"] != gas_result["output_meter"]["handle"]

    asyncio.run(_run())


@pytest.mark.integration
def test_add_heating_cooling_meters():
    """Test adding heating and cooling meters."""
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

                # Add heating electricity meter
                heating_resp = await session.call_tool("add_output_meter", {
                    "meter_name": "Heating:Electricity",
                })
                heating_result = unwrap(heating_resp)
                assert heating_result.get("ok") is True

                # Add cooling electricity meter
                cooling_resp = await session.call_tool("add_output_meter", {
                    "meter_name": "Cooling:Electricity",
                })
                cooling_result = unwrap(cooling_resp)
                assert cooling_result.get("ok") is True

    asyncio.run(_run())
