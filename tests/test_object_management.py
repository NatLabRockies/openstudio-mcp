"""Integration tests for object management tools (Phase 6B).

Tests delete_object, rename_object, list_model_objects.
"""

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


def _unique(prefix: str = "pytest_objmgmt") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _server_params():
    cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    args = shlex.split(args_env) if args_env else []
    return StdioServerParameters(command=cmd, args=args, env=os.environ.copy())


async def _setup_example(session, model_name):
    """Create + load example model."""
    cr = _unwrap(await session.call_tool("create_example_osm", {"name": model_name}))
    assert cr.get("ok") is True
    lr = _unwrap(await session.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr.get("ok") is True


async def _setup_baseline(session, model_name, ashrae_sys_num="07"):
    """Create + load baseline model with HVAC."""
    cr = _unwrap(
        await session.call_tool(
            "create_baseline_osm",
            {
                "name": model_name,
                "ashrae_sys_num": ashrae_sys_num,
            },
        ),
    )
    assert cr.get("ok") is True, cr
    lr = _unwrap(await session.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr.get("ok") is True


# ---- Rename tests ----


@pytest.mark.integration
def test_rename_space():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            # Get first space name
            spaces = _unwrap(await s.call_tool("list_spaces", {}))
            old_name = spaces["spaces"][0]["name"]
            # Rename
            res = _unwrap(
                await s.call_tool(
                    "rename_object",
                    {
                        "object_name": old_name,
                        "new_name": "Renamed Space",
                    },
                ),
            )
            assert res.get("ok") is True
            assert res["old_name"] == old_name
            assert res["new_name"] == "Renamed Space"
            # Verify
            spaces2 = _unwrap(await s.call_tool("list_spaces", {}))
            assert any(sp["name"] == "Renamed Space" for sp in spaces2["spaces"])

    asyncio.run(_run())


@pytest.mark.integration
def test_rename_thermal_zone():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            zones = _unwrap(await s.call_tool("list_thermal_zones", {}))
            old_name = zones["thermal_zones"][0]["name"]
            res = _unwrap(
                await s.call_tool(
                    "rename_object",
                    {
                        "object_name": old_name,
                        "new_name": "Renamed Zone",
                    },
                ),
            )
            assert res.get("ok") is True
            assert res["type"] == "ThermalZone"

            # Independent query verification
            zones2 = _unwrap(await s.call_tool("list_thermal_zones", {}))
            names = [z["name"] for z in zones2["thermal_zones"]]
            assert "Renamed Zone" in names
            assert old_name not in names

    asyncio.run(_run())


# ---- Delete tests ----


@pytest.mark.integration
def test_delete_space():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            # Create a new space to delete (don't delete model's original)
            _unwrap(await s.call_tool("create_space", {"name": "ToDelete"}))
            spaces_before = _unwrap(await s.call_tool("list_spaces", {}))
            count_before = spaces_before["count"]
            # Delete
            res = _unwrap(
                await s.call_tool(
                    "delete_object",
                    {
                        "object_name": "ToDelete",
                    },
                ),
            )
            assert res.get("ok") is True
            assert res["type"] == "Space"
            # Verify count decreased
            spaces_after = _unwrap(await s.call_tool("list_spaces", {}))
            assert spaces_after["count"] == count_before - 1

    asyncio.run(_run())


@pytest.mark.integration
def test_delete_nonexistent():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            res = _unwrap(
                await s.call_tool(
                    "delete_object",
                    {
                        "object_name": "DoesNotExist123",
                    },
                ),
            )
            assert res.get("ok") is False
            assert "not found" in res["error"]

    asyncio.run(_run())


# ---- List tests ----


@pytest.mark.integration
def test_list_objects_by_type():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            res = _unwrap(
                await s.call_tool(
                    "list_model_objects",
                    {
                        "object_type": "Space",
                    },
                ),
            )
            assert res.get("ok") is True
            assert res["type"] == "Space"
            assert res["count"] > 0
            assert "name" in res["objects"][0]

    asyncio.run(_run())


@pytest.mark.integration
def test_list_objects_invalid_type():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            res = _unwrap(
                await s.call_tool(
                    "list_model_objects",
                    {
                        "object_type": "FakeType",
                    },
                ),
            )
            assert res.get("ok") is False
            assert "Unsupported" in res["error"]

    asyncio.run(_run())


# ---- Baseline model tests ----


@pytest.mark.integration
def test_delete_boiler():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            # System 7 has boiler
            await _setup_baseline(s, _unique(), ashrae_sys_num="07")
            boilers = _unwrap(
                await s.call_tool(
                    "list_model_objects",
                    {
                        "object_type": "BoilerHotWater",
                    },
                ),
            )
            assert boilers.get("ok") is True and boilers["count"] > 0
            boiler_name = boilers["objects"][0]["name"]
            res = _unwrap(
                await s.call_tool(
                    "delete_object",
                    {
                        "object_name": boiler_name,
                        "object_type": "BoilerHotWater",
                    },
                ),
            )
            assert res.get("ok") is True

            # Independent query verification
            boilers2 = _unwrap(
                await s.call_tool(
                    "list_model_objects",
                    {
                        "object_type": "BoilerHotWater",
                    },
                ),
            )
            assert boilers2["count"] < boilers["count"]

    asyncio.run(_run())


@pytest.mark.integration
def test_rename_air_loop():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_baseline(s, _unique(), ashrae_sys_num="03")
            loops = _unwrap(await s.call_tool("list_air_loops", {}))
            assert loops.get("ok") is True and loops["count"] > 0
            old = loops["air_loops"][0]["name"]
            res = _unwrap(
                await s.call_tool(
                    "rename_object",
                    {
                        "object_name": old,
                        "new_name": "My AHU",
                    },
                ),
            )
            assert res.get("ok") is True
            assert res["type"] == "AirLoopHVAC"

            # Independent query verification
            loops2 = _unwrap(await s.call_tool("list_air_loops", {}))
            names = [l["name"] for l in loops2["air_loops"]]
            assert "My AHU" in names
            assert old not in names

    asyncio.run(_run())


@pytest.mark.integration
def test_delete_with_type_hint():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            # Create a schedule to delete
            _unwrap(
                await s.call_tool(
                    "create_schedule_ruleset",
                    {
                        "name": "TempSched",
                        "schedule_type": "Fractional",
                        "default_value": 1.0,
                    },
                ),
            )
            res = _unwrap(
                await s.call_tool(
                    "delete_object",
                    {
                        "object_name": "TempSched",
                        "object_type": "ScheduleRuleset",
                    },
                ),
            )
            assert res.get("ok") is True
            assert res["type"] == "ScheduleRuleset"

            # Independent query verification
            scheds = _unwrap(await s.call_tool("list_schedule_rulesets", {}))
            names = [sr["name"] for sr in scheds["schedule_rulesets"]]
            assert "TempSched" not in names

    asyncio.run(_run())


@pytest.mark.integration
def test_rename_schedule():
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            await _setup_example(s, _unique())
            # Create a schedule to rename
            _unwrap(
                await s.call_tool(
                    "create_schedule_ruleset",
                    {
                        "name": "OldSched",
                        "schedule_type": "Fractional",
                        "default_value": 1.0,
                    },
                ),
            )
            res = _unwrap(
                await s.call_tool(
                    "rename_object",
                    {
                        "object_name": "OldSched",
                        "new_name": "NewSched",
                    },
                ),
            )
            assert res.get("ok") is True
            assert res["new_name"] == "NewSched"

            # Independent query verification
            scheds = _unwrap(await s.call_tool("list_schedule_rulesets", {}))
            names = [sr["name"] for sr in scheds["schedule_rulesets"]]
            assert "NewSched" in names
            assert "OldSched" not in names

    asyncio.run(_run())
