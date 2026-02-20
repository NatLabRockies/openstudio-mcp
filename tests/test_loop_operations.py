"""Integration tests for loop_operations skill (Phase 5C)."""

import asyncio
import json
import os
import shlex

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

INTEGRATION_ENV_VAR = "RUN_OPENSTUDIO_INTEGRATION"
SERVER_CMD_VAR = "MCP_SERVER_CMD"

pytestmark = pytest.mark.skipif(
    os.getenv(INTEGRATION_ENV_VAR) != "1",
    reason=f"{INTEGRATION_ENV_VAR} not set to 1",
)


def _unwrap(result) -> dict:
    if hasattr(result, "content") and len(result.content) > 0:
        text_content = result.content[0]
        if hasattr(text_content, "text"):
            return json.loads(text_content.text)
    return {}


def _get_server_params():
    server_cmd = os.environ.get(SERVER_CMD_VAR, "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    return StdioServerParameters(
        command=server_cmd,
        args=server_args,
        env=os.environ.copy(),
    )


async def _create_and_load(session, name):
    cr = await session.call_tool("create_example_osm", {"name": name})
    cd = _unwrap(cr)
    assert cd.get("ok") is True, cd
    lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
    assert _unwrap(lr).get("ok") is True
    zr = await session.call_tool("list_thermal_zones", {})
    zd = _unwrap(zr)
    return [z["name"] for z in zd["thermal_zones"]]


async def _create_baseline_and_load(session, name):
    cr = await session.call_tool("create_baseline_osm", {"name": name})
    cd = _unwrap(cr)
    assert cd.get("ok") is True, cd
    lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
    assert _unwrap(lr).get("ok") is True
    zr = await session.call_tool("list_thermal_zones", {})
    zd = _unwrap(zr)
    return [z["name"] for z in zd["thermal_zones"]]


# --- Baseline model tests (System 7 w/ plant loops) ---


def test_add_second_boiler():
    """Add second BoilerHotWater to HW loop."""

    async def _run():
        async with stdio_client(_get_server_params()) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            zones = await _create_baseline_and_load(session, "lo_addblr")
            await session.call_tool(
                "add_baseline_system",
                {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                },
            )
            # Find HW plant loop
            plr = await session.call_tool("list_plant_loops", {})
            loops = _unwrap(plr)["plant_loops"]
            hw = next(
                l
                for l in loops
                if "hw" in l["name"].lower() or "hot" in l["name"].lower() or "heat" in l["name"].lower()
            )

            result = await session.call_tool(
                "add_supply_equipment",
                {
                    "plant_loop_name": hw["name"],
                    "equipment_type": "BoilerHotWater",
                    "equipment_name": "Backup Boiler",
                    "properties": json.dumps({"nominal_thermal_efficiency": 0.85}),
                },
            )
            data = _unwrap(result)
            assert data["ok"] is True
            assert data["equipment_name"] == "Backup Boiler"

            # Verify 2 boilers exist
            cr = await session.call_tool("list_hvac_components", {"category": "plant"})
            comps = _unwrap(cr)["components"]
            boilers = [c for c in comps if c["type"] == "BoilerHotWater"]
            assert len(boilers) >= 2

    asyncio.run(_run())


def test_add_second_chiller():
    """Add second ChillerElectricEIR to CHW loop."""

    async def _run():
        async with stdio_client(_get_server_params()) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            zones = await _create_baseline_and_load(session, "lo_addchl")
            await session.call_tool(
                "add_baseline_system",
                {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                },
            )
            plr = await session.call_tool("list_plant_loops", {})
            loops = _unwrap(plr)["plant_loops"]
            chw = next(
                l
                for l in loops
                if "chw" in l["name"].lower() or "chill" in l["name"].lower() or "cool" in l["name"].lower()
            )

            result = await session.call_tool(
                "add_supply_equipment",
                {
                    "plant_loop_name": chw["name"],
                    "equipment_type": "ChillerElectricEIR",
                    "equipment_name": "Backup Chiller",
                    "properties": json.dumps({"reference_cop": 5.5}),
                },
            )
            data = _unwrap(result)
            assert data["ok"] is True

            cr = await session.call_tool("list_hvac_components", {"category": "plant"})
            chillers = [c for c in _unwrap(cr)["components"] if c["type"] == "ChillerElectricEIR"]
            assert len(chillers) >= 2

    asyncio.run(_run())


def test_remove_boiler():
    """Remove named boiler from HW loop."""

    async def _run():
        async with stdio_client(_get_server_params()) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            zones = await _create_baseline_and_load(session, "lo_rmblr")
            await session.call_tool(
                "add_baseline_system",
                {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                },
            )
            # Add a second boiler first
            plr = await session.call_tool("list_plant_loops", {})
            loops = _unwrap(plr)["plant_loops"]
            hw = next(
                l
                for l in loops
                if "hw" in l["name"].lower() or "hot" in l["name"].lower() or "heat" in l["name"].lower()
            )

            await session.call_tool(
                "add_supply_equipment",
                {
                    "plant_loop_name": hw["name"],
                    "equipment_type": "BoilerHotWater",
                    "equipment_name": "Temp Boiler",
                },
            )

            # Now remove it
            result = await session.call_tool(
                "remove_supply_equipment",
                {
                    "plant_loop_name": hw["name"],
                    "equipment_name": "Temp Boiler",
                },
            )
            data = _unwrap(result)
            assert data["ok"] is True
            assert data["removed"] == "Temp Boiler"

            # Independent query verification
            cr = await session.call_tool("list_hvac_components", {"category": "plant"})
            names = [c["name"] for c in _unwrap(cr)["components"]]
            assert "Temp Boiler" not in names

    asyncio.run(_run())


def test_add_equipment_invalid_type():
    """Bad equipment type returns error."""

    async def _run():
        async with stdio_client(_get_server_params()) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            zones = await _create_baseline_and_load(session, "lo_invtyp")
            await session.call_tool(
                "add_baseline_system",
                {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                },
            )
            plr = await session.call_tool("list_plant_loops", {})
            loops = _unwrap(plr)["plant_loops"]
            hw = next(
                l
                for l in loops
                if "hw" in l["name"].lower() or "hot" in l["name"].lower() or "heat" in l["name"].lower()
            )

            result = await session.call_tool(
                "add_supply_equipment",
                {
                    "plant_loop_name": hw["name"],
                    "equipment_type": "FakeEquipment",
                    "equipment_name": "Bad",
                },
            )
            data = _unwrap(result)
            assert data["ok"] is False

    asyncio.run(_run())


def test_add_equipment_invalid_loop():
    """Bad loop name returns error."""

    async def _run():
        async with stdio_client(_get_server_params()) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            await _create_and_load(session, "lo_invlp")

            result = await session.call_tool(
                "add_supply_equipment",
                {
                    "plant_loop_name": "Nonexistent Loop",
                    "equipment_type": "BoilerHotWater",
                    "equipment_name": "Bad Boiler",
                },
            )
            data = _unwrap(result)
            assert data["ok"] is False

    asyncio.run(_run())


def test_remove_equipment_not_found():
    """Bad equipment name returns error."""

    async def _run():
        async with stdio_client(_get_server_params()) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            zones = await _create_baseline_and_load(session, "lo_rmnf")
            await session.call_tool(
                "add_baseline_system",
                {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                },
            )
            plr = await session.call_tool("list_plant_loops", {})
            loops = _unwrap(plr)["plant_loops"]
            hw = next(
                l
                for l in loops
                if "hw" in l["name"].lower() or "hot" in l["name"].lower() or "heat" in l["name"].lower()
            )

            result = await session.call_tool(
                "remove_supply_equipment",
                {
                    "plant_loop_name": hw["name"],
                    "equipment_name": "Ghost Equipment",
                },
            )
            data = _unwrap(result)
            assert data["ok"] is False

    asyncio.run(_run())


# --- Example model tests (zone equipment) ---


def test_add_baseboard_to_zone():
    """Add electric baseboard to zone."""

    async def _run():
        async with stdio_client(_get_server_params()) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            zones = await _create_and_load(session, "lo_addbb")

            result = await session.call_tool(
                "add_zone_equipment",
                {
                    "zone_name": zones[0],
                    "equipment_type": "ZoneHVACBaseboardConvectiveElectric",
                    "equipment_name": "Test Baseboard",
                },
            )
            data = _unwrap(result)
            assert data["ok"] is True
            assert data["equipment_name"] == "Test Baseboard"

            # Independent query verification
            ze = await session.call_tool("list_zone_hvac_equipment", {})
            zd = _unwrap(ze)
            equip_names = [eq["name"] for eq in zd.get("zone_hvac_equipment", [])]
            assert "Test Baseboard" in equip_names

    asyncio.run(_run())


def test_remove_zone_equipment():
    """Remove baseboard from zone."""

    async def _run():
        async with stdio_client(_get_server_params()) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            zones = await _create_and_load(session, "lo_rmbb")

            await session.call_tool(
                "add_zone_equipment",
                {
                    "zone_name": zones[0],
                    "equipment_type": "ZoneHVACBaseboardConvectiveElectric",
                    "equipment_name": "Temp Baseboard",
                },
            )

            result = await session.call_tool(
                "remove_zone_equipment",
                {
                    "zone_name": zones[0],
                    "equipment_name": "Temp Baseboard",
                },
            )
            data = _unwrap(result)
            assert data["ok"] is True
            assert data["removed"] == "Temp Baseboard"

            # Independent query verification
            ze = await session.call_tool("list_zone_hvac_equipment", {})
            zd = _unwrap(ze)
            equip_names = [eq["name"] for eq in zd.get("zone_hvac_equipment", [])]
            assert "Temp Baseboard" not in equip_names

    asyncio.run(_run())


def test_add_zone_equipment_invalid_zone():
    """Bad zone name returns error."""

    async def _run():
        async with stdio_client(_get_server_params()) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            await _create_and_load(session, "lo_invzn")

            result = await session.call_tool(
                "add_zone_equipment",
                {
                    "zone_name": "Nonexistent Zone",
                    "equipment_type": "ZoneHVACBaseboardConvectiveElectric",
                    "equipment_name": "Bad BB",
                },
            )
            data = _unwrap(result)
            assert data["ok"] is False

    asyncio.run(_run())


def test_add_zone_equipment_invalid_type():
    """Bad equipment type returns error."""

    async def _run():
        async with stdio_client(_get_server_params()) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            zones = await _create_and_load(session, "lo_invzt")

            result = await session.call_tool(
                "add_zone_equipment",
                {
                    "zone_name": zones[0],
                    "equipment_type": "FakeEquipment",
                    "equipment_name": "Bad",
                },
            )
            data = _unwrap(result)
            assert data["ok"] is False

    asyncio.run(_run())
