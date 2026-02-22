import asyncio
import os
import uuid

import pytest

from conftest import unwrap, integration_enabled, server_params
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_create_schedule") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_create_schedule_ruleset_fractional():
    """Test creating a fractional schedule (0-1)."""
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

                # Create fractional schedule
                schedule_resp = await session.call_tool("create_schedule_ruleset", {
                    "name": "Always On Test",
                    "schedule_type": "Fractional",
                    "default_value": 1.0
                })
                schedule_result = unwrap(schedule_resp)

                assert schedule_result.get("ok") is True
                assert schedule_result["schedule"]["name"] == "Always On Test"
                assert "handle" in schedule_result["schedule"]

                # Verify it appears in list
                list_resp = await session.call_tool("list_schedule_rulesets", {})
                list_result = unwrap(list_resp)
                assert any(s["name"] == "Always On Test" for s in list_result["schedule_rulesets"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_schedule_ruleset_temperature():
    """Test creating a temperature schedule."""
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

                # Create temperature schedule
                schedule_resp = await session.call_tool("create_schedule_ruleset", {
                    "name": "Constant 21C",
                    "schedule_type": "Temperature",
                    "default_value": 21.0
                })
                schedule_result = unwrap(schedule_resp)

                assert schedule_result.get("ok") is True
                assert schedule_result["schedule"]["name"] == "Constant 21C"

                # Independent query verification
                lst = unwrap(await session.call_tool("list_schedule_rulesets", {}))
                assert any(s["name"] == "Constant 21C" for s in lst["schedule_rulesets"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_schedule_ruleset_onoff():
    """Test creating an on/off schedule."""
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

                # Create on/off schedule
                schedule_resp = await session.call_tool("create_schedule_ruleset", {
                    "name": "Always Off",
                    "schedule_type": "OnOff",
                    "default_value": 0.0
                })
                schedule_result = unwrap(schedule_resp)

                assert schedule_result.get("ok") is True
                assert schedule_result["schedule"]["name"] == "Always Off"

                lst = unwrap(await session.call_tool("list_schedule_rulesets", {}))
                assert any(s["name"] == "Always Off" for s in lst["schedule_rulesets"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_schedule_ruleset_no_model_loaded():
    """Test error when no model is loaded."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to create schedule without loading model
                schedule_resp = await session.call_tool("create_schedule_ruleset", {"name": "Should Fail"})
                schedule_result = unwrap(schedule_resp)

                assert schedule_result.get("ok") is False
                assert "error" in schedule_result
                assert "No model loaded" in schedule_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_create_schedule_ruleset_details():
    """Test that created schedule has proper details."""
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

                # Create schedule
                schedule_resp = await session.call_tool("create_schedule_ruleset", {"name": "Test Schedule"})
                schedule_result = unwrap(schedule_resp)
                assert schedule_result.get("ok") is True

                # Get details
                details_resp = await session.call_tool("get_schedule_details", {"schedule_name": "Test Schedule"})
                details_result = unwrap(details_resp)

                assert details_result.get("ok") is True
                assert details_result["schedule"]["name"] == "Test Schedule"
                assert details_result["schedule"]["num_rules"] == 0  # No rules yet

    asyncio.run(_run())
