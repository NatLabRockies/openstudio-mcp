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


def _unique_name(prefix: str = "pytest_create_schedule") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_create_schedule_ruleset_fractional():
    """Test creating a fractional schedule (0-1)."""
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

                # Create fractional schedule
                schedule_resp = await session.call_tool("create_schedule_ruleset", {
                    "name": "Always On Test",
                    "schedule_type": "Fractional",
                    "default_value": 1.0
                })
                schedule_result = _unwrap(schedule_resp)

                assert schedule_result.get("ok") is True
                assert schedule_result["schedule"]["name"] == "Always On Test"
                assert "handle" in schedule_result["schedule"]

                # Verify it appears in list
                list_resp = await session.call_tool("list_schedule_rulesets", {})
                list_result = _unwrap(list_resp)
                assert any(s["name"] == "Always On Test" for s in list_result["schedule_rulesets"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_schedule_ruleset_temperature():
    """Test creating a temperature schedule."""
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

                # Create temperature schedule
                schedule_resp = await session.call_tool("create_schedule_ruleset", {
                    "name": "Constant 21C",
                    "schedule_type": "Temperature",
                    "default_value": 21.0
                })
                schedule_result = _unwrap(schedule_resp)

                assert schedule_result.get("ok") is True
                assert schedule_result["schedule"]["name"] == "Constant 21C"

                # Independent query verification
                lst = _unwrap(await session.call_tool("list_schedule_rulesets", {}))
                assert any(s["name"] == "Constant 21C" for s in lst["schedule_rulesets"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_schedule_ruleset_onoff():
    """Test creating an on/off schedule."""
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

                # Create on/off schedule
                schedule_resp = await session.call_tool("create_schedule_ruleset", {
                    "name": "Always Off",
                    "schedule_type": "OnOff",
                    "default_value": 0.0
                })
                schedule_result = _unwrap(schedule_resp)

                assert schedule_result.get("ok") is True
                assert schedule_result["schedule"]["name"] == "Always Off"

                lst = _unwrap(await session.call_tool("list_schedule_rulesets", {}))
                assert any(s["name"] == "Always Off" for s in lst["schedule_rulesets"])

    asyncio.run(_run())


@pytest.mark.integration
def test_create_schedule_ruleset_no_model_loaded():
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

                # Try to create schedule without loading model
                schedule_resp = await session.call_tool("create_schedule_ruleset", {"name": "Should Fail"})
                schedule_result = _unwrap(schedule_resp)

                assert schedule_result.get("ok") is False
                assert "error" in schedule_result
                assert "No model loaded" in schedule_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_create_schedule_ruleset_details():
    """Test that created schedule has proper details."""
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

                # Create schedule
                schedule_resp = await session.call_tool("create_schedule_ruleset", {"name": "Test Schedule"})
                schedule_result = _unwrap(schedule_resp)
                assert schedule_result.get("ok") is True

                # Get details
                details_resp = await session.call_tool("get_schedule_details", {"schedule_name": "Test Schedule"})
                details_result = _unwrap(details_resp)

                assert details_result.get("ok") is True
                assert details_result["schedule"]["name"] == "Test Schedule"
                assert details_result["schedule"]["num_rules"] == 0  # No rules yet

    asyncio.run(_run())
