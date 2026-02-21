"""Integration tests for schedules skill."""

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


def _unique_name(prefix: str = "pytest_schedules") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_list_schedule_rulesets():
    """Test listing all schedule rulesets."""
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

            # Create and load example model
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_result = _unwrap(create_resp)
            assert create_result.get("ok") is True

            load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
            load_result = _unwrap(load_resp)
            assert load_result.get("ok") is True

            # List schedule rulesets
            schedules_resp = await session.call_tool("list_schedule_rulesets", {})
            schedules_result = _unwrap(schedules_resp)
            print("list_schedule_rulesets:", schedules_result)

            assert isinstance(schedules_result, dict)
            assert schedules_result.get("ok") is True, schedules_result
            assert "count" in schedules_result
            assert "schedule_rulesets" in schedules_result
            assert isinstance(schedules_result["schedule_rulesets"], list)

            # Check we have some schedules
            assert schedules_result["count"] > 0, "Expected at least one schedule ruleset"

            # Check schedule structure
            if schedules_result["schedule_rulesets"]:
                schedule = schedules_result["schedule_rulesets"][0]
                assert "handle" in schedule
                assert "name" in schedule
                assert "schedule_type_limits" in schedule
                assert "default_day_schedule" in schedule
                assert "num_rules" in schedule

                print(f"Found {schedules_result['count']} schedule rulesets")
                print(f"First schedule: {schedule['name']}")

    asyncio.run(_run())


@pytest.mark.integration
def test_get_schedule_details():
    """Test getting details for a specific schedule."""
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

            # Create and load example model
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_result = _unwrap(create_resp)
            assert create_result.get("ok") is True

            load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
            load_result = _unwrap(load_resp)
            assert load_result.get("ok") is True

            # First list schedules to get a valid name
            list_resp = await session.call_tool("list_schedule_rulesets", {})
            list_result = _unwrap(list_resp)
            assert list_result.get("ok") is True
            assert list_result["count"] > 0, "Need at least one schedule for this test"

            schedule_name = list_result["schedule_rulesets"][0]["name"]

            # Get details for the first schedule
            details_resp = await session.call_tool("get_schedule_details", {"schedule_name": schedule_name})
            details_result = _unwrap(details_resp)
            print("get_schedule_details:", details_result)

            assert isinstance(details_result, dict)
            assert details_result.get("ok") is True, details_result
            assert "schedule" in details_result

            schedule = details_result["schedule"]
            assert schedule["name"] == schedule_name
            assert "rules" in schedule
            assert isinstance(schedule["rules"], list)

            # Check rule structure if any rules exist
            if schedule["rules"]:
                rule = schedule["rules"][0]
                assert "day_schedule" in rule
                assert "apply_sunday" in rule
                assert "apply_monday" in rule

                print(f"Schedule '{schedule_name}' has {len(schedule['rules'])} rules")
            else:
                print(f"Schedule '{schedule_name}' has no rules (uses default only)")

    asyncio.run(_run())


@pytest.mark.integration
def test_get_schedule_details_not_found():
    """Test getting details for a non-existent schedule."""
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

            # Create and load example model
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_result = _unwrap(create_resp)
            assert create_result.get("ok") is True

            load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
            load_result = _unwrap(load_resp)
            assert load_result.get("ok") is True

            # Try to get non-existent schedule
            details_resp = await session.call_tool("get_schedule_details", {"schedule_name": "NonExistentSchedule"})
            details_result = _unwrap(details_resp)
            print("get_schedule_details (not found):", details_result)

            assert isinstance(details_result, dict)
            assert details_result.get("ok") is False
            assert "error" in details_result
            assert "not found" in details_result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_schedules_baseline():
    """Test schedule rulesets in baseline model with weekday/saturday/sunday profiles."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    name = _unique_name("pytest_bl_sched")

    async def _run():
        server_params = StdioServerParameters(command=server_cmd, args=server_args, env=os.environ.copy())
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            cr = await session.call_tool("create_baseline_osm", {"name": name})
            cd = _unwrap(cr)
            assert cd.get("ok") is True, cd
            lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
            assert _unwrap(lr).get("ok") is True

            sr = await session.call_tool("list_schedule_rulesets", {})
            sd = _unwrap(sr)
            print("baseline schedules:", sd)
            assert sd.get("ok") is True
            # Baseline has infiltration, people/lights/equip, activity, cooling, heating schedules
            assert sd["count"] >= 5

            # Find the people/lights schedule and check it has rules
            ple_name = None
            for s in sd["schedule_rulesets"]:
                if "People Lights" in s["name"]:
                    ple_name = s["name"]
                    assert s["num_rules"] >= 2  # Saturday + Sunday rules
                    break
            assert ple_name is not None, "Expected People Lights and Equipment Schedule"

            # Get details for that schedule
            dr = await session.call_tool("get_schedule_details", {"schedule_name": ple_name})
            dd = _unwrap(dr)
            assert dd.get("ok") is True
            assert len(dd["schedule"]["rules"]) >= 2

    asyncio.run(_run())


@pytest.mark.integration
def test_schedules_tools_without_loaded_model():
    """Test that schedule tools fail gracefully when no model is loaded."""
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

            # Try to list schedules without loading a model
            schedules_resp = await session.call_tool("list_schedule_rulesets", {})
            schedules_result = _unwrap(schedules_resp)
            print("list_schedule_rulesets (no model):", schedules_result)

            assert isinstance(schedules_result, dict)
            assert schedules_result.get("ok") is False
            assert "error" in schedules_result
            assert "no model loaded" in schedules_result["error"].lower()

    asyncio.run(_run())
