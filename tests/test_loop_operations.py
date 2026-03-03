"""Integration tests for loop_operations skill (Phase 5C)."""
import asyncio
import json

import pytest
from conftest import create_and_load, create_baseline_and_load, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


# --- Baseline model tests (System 7 w/ plant loops) ---

def test_add_second_boiler():
    """Add second BoilerHotWater to HW loop."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "lo_addblr")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                # Find HW plant loop
                plr = await session.call_tool("list_plant_loops", {})
                loops = unwrap(plr)["plant_loops"]
                hw = next(l for l in loops if "hw" in l["name"].lower() or "hot" in l["name"].lower() or "heat" in l["name"].lower())

                result = await session.call_tool("add_supply_equipment", {
                    "plant_loop_name": hw["name"],
                    "equipment_type": "BoilerHotWater",
                    "equipment_name": "Backup Boiler",
                    "properties": json.dumps({"nominal_thermal_efficiency": 0.85}),
                })
                data = unwrap(result)
                assert data["ok"] is True
                assert data["equipment_name"] == "Backup Boiler"

                # Verify 2 boilers exist
                cr = await session.call_tool("list_hvac_components", {"category": "plant"})
                comps = unwrap(cr)["components"]
                boilers = [c for c in comps if c["type"] == "BoilerHotWater"]
                assert len(boilers) >= 2
    asyncio.run(_run())


def test_add_second_chiller():
    """Add second ChillerElectricEIR to CHW loop."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "lo_addchl")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                plr = await session.call_tool("list_plant_loops", {})
                loops = unwrap(plr)["plant_loops"]
                chw = next(l for l in loops if "chw" in l["name"].lower() or "chill" in l["name"].lower() or "cool" in l["name"].lower())

                result = await session.call_tool("add_supply_equipment", {
                    "plant_loop_name": chw["name"],
                    "equipment_type": "ChillerElectricEIR",
                    "equipment_name": "Backup Chiller",
                    "properties": json.dumps({"reference_cop": 5.5}),
                })
                data = unwrap(result)
                assert data["ok"] is True

                cr = await session.call_tool("list_hvac_components", {"category": "plant"})
                chillers = [c for c in unwrap(cr)["components"] if c["type"] == "ChillerElectricEIR"]
                assert len(chillers) >= 2
    asyncio.run(_run())


def test_remove_boiler():
    """Remove named boiler from HW loop."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "lo_rmblr")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                # Add a second boiler first
                plr = await session.call_tool("list_plant_loops", {})
                loops = unwrap(plr)["plant_loops"]
                hw = next(l for l in loops if "hw" in l["name"].lower() or "hot" in l["name"].lower() or "heat" in l["name"].lower())

                await session.call_tool("add_supply_equipment", {
                    "plant_loop_name": hw["name"],
                    "equipment_type": "BoilerHotWater",
                    "equipment_name": "Temp Boiler",
                })

                # Now remove it
                result = await session.call_tool("remove_supply_equipment", {
                    "plant_loop_name": hw["name"],
                    "equipment_name": "Temp Boiler",
                })
                data = unwrap(result)
                assert data["ok"] is True
                assert data["removed"] == "Temp Boiler"

                # Independent query verification
                cr = await session.call_tool("list_hvac_components", {"category": "plant"})
                names = [c["name"] for c in unwrap(cr)["components"]]
                assert "Temp Boiler" not in names
    asyncio.run(_run())


def test_add_equipment_invalid_type():
    """Bad equipment type returns error."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "lo_invtyp")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                plr = await session.call_tool("list_plant_loops", {})
                loops = unwrap(plr)["plant_loops"]
                hw = next(l for l in loops if "hw" in l["name"].lower() or "hot" in l["name"].lower() or "heat" in l["name"].lower())

                result = await session.call_tool("add_supply_equipment", {
                    "plant_loop_name": hw["name"],
                    "equipment_type": "FakeEquipment",
                    "equipment_name": "Bad",
                })
                data = unwrap(result)
                assert data["ok"] is False
    asyncio.run(_run())


def test_add_equipment_invalid_loop():
    """Bad loop name returns error."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_and_load(session, "lo_invlp")

                result = await session.call_tool("add_supply_equipment", {
                    "plant_loop_name": "Nonexistent Loop",
                    "equipment_type": "BoilerHotWater",
                    "equipment_name": "Bad Boiler",
                })
                data = unwrap(result)
                assert data["ok"] is False
    asyncio.run(_run())


def test_remove_equipment_not_found():
    """Bad equipment name returns error."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "lo_rmnf")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                plr = await session.call_tool("list_plant_loops", {})
                loops = unwrap(plr)["plant_loops"]
                hw = next(l for l in loops if "hw" in l["name"].lower() or "hot" in l["name"].lower() or "heat" in l["name"].lower())

                result = await session.call_tool("remove_supply_equipment", {
                    "plant_loop_name": hw["name"],
                    "equipment_name": "Ghost Equipment",
                })
                data = unwrap(result)
                assert data["ok"] is False
    asyncio.run(_run())


# --- Example model tests (zone equipment) ---

def test_add_baseboard_to_zone():
    """Add electric baseboard to zone."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "lo_addbb")

                result = await session.call_tool("add_zone_equipment", {
                    "zone_name": zones[0],
                    "equipment_type": "ZoneHVACBaseboardConvectiveElectric",
                    "equipment_name": "Test Baseboard",
                })
                data = unwrap(result)
                assert data["ok"] is True
                assert data["equipment_name"] == "Test Baseboard"

                # Independent query verification
                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = unwrap(ze)
                equip_names = [eq["name"] for eq in zd.get("zone_hvac_equipment", [])]
                assert "Test Baseboard" in equip_names
    asyncio.run(_run())


def test_remove_zone_equipment():
    """Remove baseboard from zone."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "lo_rmbb")

                await session.call_tool("add_zone_equipment", {
                    "zone_name": zones[0],
                    "equipment_type": "ZoneHVACBaseboardConvectiveElectric",
                    "equipment_name": "Temp Baseboard",
                })

                result = await session.call_tool("remove_zone_equipment", {
                    "zone_name": zones[0],
                    "equipment_name": "Temp Baseboard",
                })
                data = unwrap(result)
                assert data["ok"] is True
                assert data["removed"] == "Temp Baseboard"

                # Independent query verification
                ze = await session.call_tool("list_zone_hvac_equipment", {})
                zd = unwrap(ze)
                equip_names = [eq["name"] for eq in zd.get("zone_hvac_equipment", [])]
                assert "Temp Baseboard" not in equip_names
    asyncio.run(_run())


def test_add_zone_equipment_invalid_zone():
    """Bad zone name returns error."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_and_load(session, "lo_invzn")

                result = await session.call_tool("add_zone_equipment", {
                    "zone_name": "Nonexistent Zone",
                    "equipment_type": "ZoneHVACBaseboardConvectiveElectric",
                    "equipment_name": "Bad BB",
                })
                data = unwrap(result)
                assert data["ok"] is False
    asyncio.run(_run())


def test_add_zone_equipment_invalid_type():
    """Bad equipment type returns error."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "lo_invzt")

                result = await session.call_tool("add_zone_equipment", {
                    "zone_name": zones[0],
                    "equipment_type": "FakeEquipment",
                    "equipment_name": "Bad",
                })
                data = unwrap(result)
                assert data["ok"] is False
    asyncio.run(_run())
