"""Integration tests for HVAC supply equipment auto-wiring (H-25/H-26/H-27).

Tests verify:
- DOAS plant loops get boiler + chiller + condenser tower (default fuels)
- DOAS with DistrictHeating/DistrictCooling wires district objects
- Radiant plant loops get boiler + chiller + condenser tower (default fuels)
- Radiant with DistrictHeating/DistrictCooling wires district objects
- Return dicts include condenser_water_loop, heating_fuel, cooling_fuel
- H-28: validation.validate_system returns valid=None for non-air-loop systems
"""
from __future__ import annotations

import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _setup_model(session, name):
    """Create + load example model, return zone names."""
    cr = await session.call_tool("create_example_osm", {"name": name})
    cd = unwrap(cr)
    await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
    zr = await session.call_tool("list_thermal_zones", {"max_results": 0})
    zd = unwrap(zr)
    return [z["name"] for z in zd["thermal_zones"]]


async def _get_supply_types(session, loop_name):
    """Return set of supply component type strings for a plant loop."""
    resp = await session.call_tool("get_plant_loop_details", {
        "plant_loop_name": loop_name,
    })
    data = unwrap(resp)
    assert data.get("ok") is True, f"get_plant_loop_details failed: {data.get('error')}"
    return {comp["type"] for comp in data["plant_loop"]["supply_components"]}


# ===================================================================
# DOAS — default fuels (NaturalGas / Electricity)
# ===================================================================

@pytest.mark.integration
def test_doas_default_supply_equipment():
    """DOAS FanCoil with default fuels gets boiler + chiller + condenser."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_doas_supply")

                resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Sup",
                    "zone_equipment_type": "FanCoil",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]

                # Return dict includes new fields
                assert sys["heating_fuel"] == "NaturalGas"
                assert sys["cooling_fuel"] == "Electricity"
                assert sys["condenser_water_loop"] is not None

                # HW loop has boiler
                hw_types = await _get_supply_types(session, sys["hot_water_loop"])
                assert any("Boiler" in t for t in hw_types), f"No boiler on HW loop: {hw_types}"

                # CHW loop has chiller
                chw_types = await _get_supply_types(session, sys["chilled_water_loop"])
                assert any("Chiller" in t for t in chw_types), f"No chiller on CHW loop: {chw_types}"

                # Condenser loop has cooling tower
                cw_types = await _get_supply_types(session, sys["condenser_water_loop"])
                assert any("CoolingTower" in t for t in cw_types), f"No tower on CW loop: {cw_types}"

    asyncio.run(_run())


# ===================================================================
# DOAS — district heating
# ===================================================================

@pytest.mark.integration
def test_doas_district_heating():
    """DOAS with DistrictHeating puts DistrictHeating on HW loop."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_doas_dh")

                resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS DH",
                    "zone_equipment_type": "FanCoil",
                    "heating_fuel": "DistrictHeating",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]
                assert sys["heating_fuel"] == "DistrictHeating"

                hw_types = await _get_supply_types(session, sys["hot_water_loop"])
                assert any("DistrictHeating" in t for t in hw_types), \
                    f"No DistrictHeating on HW loop: {hw_types}"

    asyncio.run(_run())


# ===================================================================
# DOAS — district cooling
# ===================================================================

@pytest.mark.integration
def test_doas_district_cooling():
    """DOAS with DistrictCooling puts DistrictCooling on CHW loop, no condenser."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_doas_dc")

                resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS DC",
                    "zone_equipment_type": "FanCoil",
                    "cooling_fuel": "DistrictCooling",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]
                assert sys["cooling_fuel"] == "DistrictCooling"
                assert sys["condenser_water_loop"] is None  # no condenser for district

                chw_types = await _get_supply_types(session, sys["chilled_water_loop"])
                assert any("DistrictCooling" in t for t in chw_types), \
                    f"No DistrictCooling on CHW loop: {chw_types}"

    asyncio.run(_run())


# ===================================================================
# DOAS — both district
# ===================================================================

@pytest.mark.integration
def test_doas_both_district():
    """DOAS with both district fuels — no condenser, no boiler, no chiller."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_doas_dd")

                resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS DD",
                    "zone_equipment_type": "FanCoil",
                    "heating_fuel": "DistrictHeating",
                    "cooling_fuel": "DistrictCooling",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]
                assert sys["condenser_water_loop"] is None

                hw_types = await _get_supply_types(session, sys["hot_water_loop"])
                assert any("DistrictHeating" in t for t in hw_types)
                assert not any("Boiler" in t for t in hw_types)

                chw_types = await _get_supply_types(session, sys["chilled_water_loop"])
                assert any("DistrictCooling" in t for t in chw_types)
                assert not any("Chiller" in t for t in chw_types)

    asyncio.run(_run())


# ===================================================================
# Radiant — default fuels
# ===================================================================

@pytest.mark.integration
def test_radiant_default_supply_equipment():
    """Radiant with default fuels gets boiler + chiller + condenser."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_rad_supply")

                resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Rad Sup",
                    "radiant_type": "Floor",
                    "ventilation_system": "None",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]

                assert sys["heating_fuel"] == "NaturalGas"
                assert sys["cooling_fuel"] == "Electricity"
                assert sys["condenser_water_loop"] is not None

                hw_types = await _get_supply_types(session, sys["hot_water_loop"])
                assert any("Boiler" in t for t in hw_types)

                chw_types = await _get_supply_types(session, sys["chilled_water_loop"])
                assert any("Chiller" in t for t in chw_types)

                cw_types = await _get_supply_types(session, sys["condenser_water_loop"])
                assert any("CoolingTower" in t for t in cw_types)

    asyncio.run(_run())


# ===================================================================
# Radiant — district heating
# ===================================================================

@pytest.mark.integration
def test_radiant_district_heating():
    """Radiant with DistrictHeating puts DistrictHeating on HW loop."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_rad_dh")

                resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Rad DH",
                    "radiant_type": "Floor",
                    "ventilation_system": "None",
                    "heating_fuel": "DistrictHeating",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]
                assert sys["heating_fuel"] == "DistrictHeating"

                hw_types = await _get_supply_types(session, sys["hot_water_loop"])
                assert any("DistrictHeating" in t for t in hw_types)

    asyncio.run(_run())


# ===================================================================
# Radiant — district cooling
# ===================================================================

@pytest.mark.integration
def test_radiant_district_cooling():
    """Radiant with DistrictCooling — no condenser loop."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_rad_dc")

                resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Rad DC",
                    "radiant_type": "Floor",
                    "ventilation_system": "None",
                    "cooling_fuel": "DistrictCooling",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]
                assert sys["cooling_fuel"] == "DistrictCooling"
                assert sys["condenser_water_loop"] is None

                chw_types = await _get_supply_types(session, sys["chilled_water_loop"])
                assert any("DistrictCooling" in t for t in chw_types)

    asyncio.run(_run())


# ===================================================================
# Radiant — both district
# ===================================================================

@pytest.mark.integration
def test_radiant_both_district():
    """Radiant with both district fuels — district objects, no boiler/chiller."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_rad_dd")

                resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Rad DD",
                    "radiant_type": "Floor",
                    "ventilation_system": "None",
                    "heating_fuel": "DistrictHeating",
                    "cooling_fuel": "DistrictCooling",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]
                assert sys["condenser_water_loop"] is None

                hw_types = await _get_supply_types(session, sys["hot_water_loop"])
                assert any("DistrictHeating" in t for t in hw_types)
                assert not any("Boiler" in t for t in hw_types)

                chw_types = await _get_supply_types(session, sys["chilled_water_loop"])
                assert any("DistrictCooling" in t for t in chw_types)
                assert not any("Chiller" in t for t in chw_types)

    asyncio.run(_run())


# ===================================================================
# Radiant + DOAS — supply on both radiant AND ventilation loops
# ===================================================================

@pytest.mark.integration
def test_radiant_with_doas_has_supply():
    """Radiant+DOAS: radiant loops get supply equipment, DOAS loop exists."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_rad_doas_sup")

                resp = await session.call_tool("add_radiant_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "Rad DOAS Sup",
                    "radiant_type": "Floor",
                    "ventilation_system": "DOAS",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]

                # Radiant HW loop has boiler
                hw_types = await _get_supply_types(session, sys["hot_water_loop"])
                assert any("Boiler" in t for t in hw_types)

                # Radiant CHW loop has chiller
                chw_types = await _get_supply_types(session, sys["chilled_water_loop"])
                assert any("Chiller" in t for t in chw_types)

                # DOAS air loop exists
                alr = await session.call_tool("list_air_loops", {})
                ald = unwrap(alr)
                assert any("Ventilation" in lp["name"] for lp in ald["air_loops"])

    asyncio.run(_run())


# ===================================================================
# DOAS Chilled Beams — only CHW loop, verify supply
# ===================================================================

@pytest.mark.integration
def test_doas_chilled_beams_supply():
    """DOAS ChilledBeams: CHW loop has chiller, no HW loop."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_doas_beam_sup")

                resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Beam",
                    "zone_equipment_type": "ChilledBeams",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]

                # Chilled beams only need CHW, no HW
                assert sys["chilled_water_loop"] is not None
                assert sys["hot_water_loop"] is None

                chw_types = await _get_supply_types(session, sys["chilled_water_loop"])
                assert any("Chiller" in t for t in chw_types)

    asyncio.run(_run())


# ===================================================================
# DOAS electric boiler
# ===================================================================

@pytest.mark.integration
def test_doas_electric_boiler():
    """DOAS with Electricity heating gets electric boiler."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zone_names = await _setup_model(session, "test_doas_elec")

                resp = await session.call_tool("add_doas_system", {
                    "thermal_zone_names": zone_names,
                    "system_name": "DOAS Elec",
                    "zone_equipment_type": "FanCoil",
                    "heating_fuel": "Electricity",
                })
                data = unwrap(resp)
                assert data.get("ok") is True
                sys = data["system"]
                assert sys["heating_fuel"] == "Electricity"

                hw_types = await _get_supply_types(session, sys["hot_water_loop"])
                assert any("Boiler" in t for t in hw_types)

    asyncio.run(_run())
