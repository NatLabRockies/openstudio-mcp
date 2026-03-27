"""Integration tests for schedules skill."""
import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_schedules") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_list_schedule_rulesets_via_generic():
    """Test listing all schedule rulesets via list_model_objects."""
    # Validates: list_model_objects(ScheduleRuleset) returns schedules with name field
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

                # List schedule rulesets via generic access
                schedules_resp = await session.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0})
                schedules_result = unwrap(schedules_resp)
                print("list_model_objects(ScheduleRuleset):", schedules_result)
                assert schedules_result["ok"] is True, schedules_result
                assert isinstance(schedules_result["objects"], list)

                # Check we have some schedules
                assert schedules_result["count"] > 0, "Expected at least one schedule ruleset"

                schedule = schedules_result["objects"][0]
                assert schedule["name"], "Schedule should have a name"
                print(f"Found {schedules_result['count']} schedule rulesets")
                print(f"First schedule: {schedule['name']}")

    asyncio.run(_run())


@pytest.mark.integration
def test_get_schedule_details():
    """Test getting details for a specific schedule."""
    # Validates: get_schedule_details returns schedule name, rules array, day schedule info
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

                # First list schedules to get a valid name
                list_resp = await session.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0})
                list_result = unwrap(list_resp)
                assert list_result["ok"] is True
                assert list_result["count"] > 0, "Need at least one schedule for this test"

                schedule_name = list_result["objects"][0]["name"]

                # Get details for the first schedule
                details_resp = await session.call_tool("get_schedule_details", {"schedule_name": schedule_name})
                details_result = unwrap(details_resp)
                print("get_schedule_details:", details_result)
                assert details_result["ok"] is True, details_result
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
    # Validates: get_schedule_details returns ok:false with "not found" for bad name
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

                # Try to get non-existent schedule
                details_resp = await session.call_tool("get_schedule_details", {"schedule_name": "NonExistentSchedule"})
                details_result = unwrap(details_resp)
                print("get_schedule_details (not found):", details_result)
                assert details_result["ok"] is False
                assert "not found" in details_result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_schedules_baseline():
    """Test schedule rulesets in baseline model with weekday/saturday/sunday profiles."""
    # Validates: baseline has >= 5 schedules, People Lights schedule has >= 2 rules
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_sched")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                sr = await session.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0})
                sd = unwrap(sr)
                print("baseline schedules:", sd)
                assert sd["ok"] is True
                # Baseline has infiltration, people/lights/equip, activity, cooling, heating schedules
                assert sd["count"] >= 5

                # Find the people/lights schedule and check it has rules
                ple_name = None
                for s in sd["objects"]:
                    if "People Lights" in s["name"]:
                        ple_name = s["name"]
                        break
                assert ple_name, "Expected People Lights and Equipment Schedule in baseline"

                # Get details for that schedule
                dr = await session.call_tool("get_schedule_details", {"schedule_name": ple_name})
                dd = unwrap(dr)
                assert dd["ok"] is True
                assert len(dd["schedule"]["rules"]) >= 2

    asyncio.run(_run())


@pytest.mark.integration
def test_schedules_tools_without_loaded_model():
    """Test that schedule tools fail gracefully when no model is loaded."""
    # Validates: schedule tools return ok:false with "no model loaded" when no model
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to list schedules without loading a model
                schedules_resp = await session.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0})
                schedules_result = unwrap(schedules_resp)
                print("list_model_objects(ScheduleRuleset, no model):", schedules_result)
                assert schedules_result["ok"] is False
                assert "no model loaded" in schedules_result["error"].lower()

    asyncio.run(_run())
