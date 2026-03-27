"""Integration tests for object management tools (Phase 6B).

Tests delete_object, rename_object, list_model_objects.
"""
import asyncio
import uuid

import pytest
from conftest import integration_enabled, server_params, setup_example, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_objmgmt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _setup_baseline(session, model_name, ashrae_sys_num="07"):
    """Create + load baseline model with HVAC."""
    cr = unwrap(await session.call_tool("create_baseline_osm", {
        "name": model_name, "ashrae_sys_num": ashrae_sys_num,
    }))
    assert cr["ok"] is True, cr
    lr = unwrap(await session.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr["ok"] is True


# ---- Rename tests ----

@pytest.mark.integration
def test_rename_space():
    # Validates: rename_object changes space name and old name disappears from listing
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Get first space name
                spaces = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                old_name = spaces["spaces"][0]["name"]
                # Rename
                res = unwrap(await s.call_tool("rename_object", {
                    "object_name": old_name, "new_name": "Renamed Space",
                }))
                assert res["ok"] is True
                assert res["old_name"] == old_name
                assert res["new_name"] == "Renamed Space"
                # Verify
                spaces2 = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                assert any(sp["name"] == "Renamed Space" for sp in spaces2["spaces"])
    asyncio.run(_run())


@pytest.mark.integration
def test_rename_thermal_zone():
    # Validates: rename_object changes zone name, returns type=ThermalZone
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                zones = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                old_name = zones["thermal_zones"][0]["name"]
                res = unwrap(await s.call_tool("rename_object", {
                    "object_name": old_name, "new_name": "Renamed Zone",
                }))
                assert res["ok"] is True
                assert res["type"] == "ThermalZone"

                # Independent query verification
                zones2 = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                names = [z["name"] for z in zones2["thermal_zones"]]
                assert "Renamed Zone" in names
                assert old_name not in names
    asyncio.run(_run())


# ---- Delete tests ----

@pytest.mark.integration
def test_delete_space():
    # Validates: delete_object removes space and decreases count by 1
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Create a new space to delete (don't delete model's original)
                unwrap(await s.call_tool("create_space", {"name": "ToDelete"}))
                spaces_before = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                count_before = spaces_before["count"]
                # Delete
                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": "ToDelete",
                }))
                assert res["ok"] is True
                assert res["type"] == "Space"
                # Verify count decreased
                spaces_after = unwrap(await s.call_tool("list_spaces", {"max_results": 0}))
                assert spaces_after["count"] == count_before - 1
    asyncio.run(_run())


@pytest.mark.integration
def test_delete_nonexistent():
    # Validates: delete_object returns ok:false with "not found" for bad name
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": "DoesNotExist123",
                }))
                assert res["ok"] is False
                assert "not found" in res["error"]
    asyncio.run(_run())


# list_model_objects tests are in test_generic_access.py

# ---- Baseline model tests ----

@pytest.mark.integration
def test_delete_boiler():
    # Validates: delete_object removes BoilerHotWater from System 7 model
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # System 7 has boiler
                await _setup_baseline(s, _unique(), ashrae_sys_num="07")
                boilers = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "BoilerHotWater", "max_results": 0,
                }))
                assert boilers["ok"] is True and boilers["count"] > 0
                boiler_name = boilers["objects"][0]["name"]
                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": boiler_name, "object_type": "BoilerHotWater",
                }))
                assert res["ok"] is True

                # Independent query verification
                boilers2 = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "BoilerHotWater", "max_results": 0,
                }))
                assert boilers2["count"] < boilers["count"]
    asyncio.run(_run())


@pytest.mark.integration
def test_rename_air_loop():
    # Validates: rename_object changes air loop name, returns type=AirLoopHVAC
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique(), ashrae_sys_num="03")
                loops = unwrap(await s.call_tool("list_air_loops", {}))
                assert loops["ok"] is True and loops["count"] > 0
                old = loops["air_loops"][0]["name"]
                res = unwrap(await s.call_tool("rename_object", {
                    "object_name": old, "new_name": "My AHU",
                }))
                assert res["ok"] is True
                assert res["type"] == "AirLoopHVAC"

                # Independent query verification
                loops2 = unwrap(await s.call_tool("list_air_loops", {}))
                names = [l["name"] for l in loops2["air_loops"]]
                assert "My AHU" in names
                assert old not in names
    asyncio.run(_run())


@pytest.mark.integration
def test_delete_with_type_hint():
    # Validates: delete_object with object_type hint removes ScheduleRuleset
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Create a schedule to delete
                unwrap(await s.call_tool("create_schedule_ruleset", {
                    "name": "TempSched", "schedule_type": "Fractional", "default_value": 1.0,
                }))
                res = unwrap(await s.call_tool("delete_object", {
                    "object_name": "TempSched", "object_type": "ScheduleRuleset",
                }))
                assert res["ok"] is True
                assert res["type"] == "ScheduleRuleset"

                # Independent query verification
                scheds = unwrap(await s.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0}))
                names = [sr["name"] for sr in scheds["objects"]]
                assert "TempSched" not in names
    asyncio.run(_run())


@pytest.mark.integration
def test_rename_schedule():
    # Validates: rename_object changes schedule name, old name gone from listing
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Create a schedule to rename
                unwrap(await s.call_tool("create_schedule_ruleset", {
                    "name": "OldSched", "schedule_type": "Fractional", "default_value": 1.0,
                }))
                res = unwrap(await s.call_tool("rename_object", {
                    "object_name": "OldSched", "new_name": "NewSched",
                }))
                assert res["ok"] is True
                assert res["new_name"] == "NewSched"

                # Independent query verification
                scheds = unwrap(await s.call_tool("list_model_objects", {"object_type": "ScheduleRuleset", "max_results": 0}))
                names = [sr["name"] for sr in scheds["objects"]]
                assert "NewSched" in names
                assert "OldSched" not in names
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# H-29: fetch_object UUID validation (direct SDK, not MCP)
# ---------------------------------------------------------------------------

def test_bad_uuid_returns_none():
    # Regression: malformed UUID in fetch_object caused unhandled exception
    openstudio = pytest.importorskip("openstudio")
    from mcp_server.osm_helpers import fetch_object
    model = openstudio.model.Model()
    result = fetch_object(model, "Space", handle="not-a-valid-uuid-!!!")
    assert result is None, "Malformed UUID should return None, not an object"
