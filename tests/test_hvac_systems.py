"""Integration tests for hvac_systems skill."""
import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


def test_list_baseline_systems():
    """Test listing all ASHRAE baseline system types."""
    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # List baseline systems
                result = await session.call_tool("list_baseline_systems", {})
                data = unwrap(result)

                assert data.get("ok") is True
                assert "baseline_systems" in data
                assert "modern_templates" in data
                assert data["total_count"] > 0

                # Verify we have 10 baseline systems
                assert len(data["baseline_systems"]) == 10

                # Verify System 1 is PTAC
                sys1 = next((s for s in data["baseline_systems"] if s["system_type"] == 1), None)
                assert sys1 is not None
                assert sys1["name"] == "PTAC"

    asyncio.run(_run())


def test_get_baseline_system_info():
    """Test getting info for specific baseline system."""
    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Get System 1 (PTAC) info
                result = await session.call_tool("get_baseline_system_info", {
                    "system_type": 1,
                })
                data = unwrap(result)

                assert data.get("ok") is True
                assert "system" in data
                assert data["system"]["name"] == "PTAC"
                assert data["system"]["full_name"] == "Packaged Terminal Air Conditioner"
                assert "heating" in data["system"]
                assert "cooling" in data["system"]

    asyncio.run(_run())


def test_add_baseline_system_1_ptac():
    """Test adding ASHRAE baseline System 1 (PTAC)."""
    name = "test_baseline_sys1"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create example model
                create_resp = await session.call_tool("create_example_osm", {
                    "name": name,
                })
                create_data = unwrap(create_resp)
                assert create_data.get("ok") is True

                # Load model
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })
                load_data = unwrap(load_resp)
                assert load_data.get("ok") is True

                # List thermal zones
                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                assert zones_data.get("ok") is True
                assert len(zones_data["thermal_zones"]) > 0

                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Add baseline System 1 (PTAC)
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zone_names,
                    "heating_fuel": "Electricity",
                    "cooling_fuel": "Electricity",
                    "economizer": False,
                    "system_name": "PTAC System",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "PTAC (Baseline System 1)"
                assert system_data["system"]["system_number"] == 1
                assert system_data["system"]["zones_served"] == len(zone_names)
                assert "equipment" in system_data["system"]
                assert len(system_data["system"]["equipment"]) == len(zone_names)

                # Verify each zone got PTAC equipment
                for equip in system_data["system"]["equipment"]:
                    assert "zone" in equip
                    assert "equipment" in equip
                    assert "PTAC" in equip["equipment"]
                    assert "heating_coil" in equip
                    assert "cooling_coil" in equip
                    assert "fan" in equip

                # Save model
                save_resp = await session.call_tool("save_osm_model", {})
                save_data = unwrap(save_resp)
                assert save_data.get("ok") is True

    asyncio.run(_run())


def test_add_baseline_system_2_pthp():
    """Test adding ASHRAE baseline System 2 (PTHP)."""
    name = "test_baseline_sys2"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {
                    "name": name,
                })
                create_data = unwrap(create_resp)
                assert create_data.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })
                assert unwrap(load_resp).get("ok") is True

                # Get zone names
                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Add baseline System 2 (PTHP)
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 2,
                    "thermal_zone_names": zone_names,
                    "system_name": "PTHP System",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "PTHP (Baseline System 2)"
                assert system_data["system"]["heating"] == "Heat Pump"
                assert system_data["system"]["cooling"] == "Heat Pump"

                # Verify PTHP equipment has supplemental heating
                for equip in system_data["system"]["equipment"]:
                    assert "supplemental_heating_coil" in equip

    asyncio.run(_run())


def test_add_baseline_system_3_psz_ac():
    """Test adding ASHRAE baseline System 3 (PSZ-AC)."""
    name = "test_baseline_sys3"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {
                    "name": name,
                })
                create_data = unwrap(create_resp)
                assert create_data.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })
                assert unwrap(load_resp).get("ok") is True

                # Get first zone only (PSZ = single zone)
                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                # Add baseline System 3 (PSZ-AC) with economizer
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "heating_fuel": "NaturalGas",
                    "cooling_fuel": "Electricity",
                    "economizer": True,
                    "system_name": "PSZ-AC System",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "PSZ-AC (Baseline System 3)"
                assert system_data["system"]["equipment_type"] == "Packaged Rooftop Unit"
                assert system_data["system"]["zones_served"] == 1
                assert system_data["system"]["heating"] == "Gas Furnace"
                assert system_data["system"]["economizer"] is True
                assert "air_loop" in system_data["system"]
                assert "outdoor_air_system" in system_data["system"]

                # Verify air loop was created
                air_loops_resp = await session.call_tool("list_air_loops", {})
                air_loops_data = unwrap(air_loops_resp)
                assert any(al["name"] == "PSZ-AC System" for al in air_loops_data["air_loops"])

    asyncio.run(_run())


def test_add_baseline_system_json_string_zones():
    """Test that thermal_zone_names works when passed as a JSON string.

    Some MCP clients (including Claude Code) may serialize array parameters
    as JSON strings rather than native arrays. The _parse_str_list helper
    in tools.py handles this coercion.
    """
    import json
    name = "test_json_string_zones"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                assert create_data.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_name = unwrap(zones_resp)["thermal_zones"][0]["name"]

                # Pass thermal_zone_names as a JSON-encoded string instead of list
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": json.dumps([zone_name]),
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True, (
                    f"JSON-string zone names failed: {system_data.get('error')}"
                )
                assert system_data["system"]["zones_served"] == 1

    asyncio.run(_run())


def test_add_baseline_system_error_no_model():
    """Test error when adding system without loaded model."""
    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to add system without loading model
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": ["Zone 1"],
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is False
                assert "error" in system_data

    asyncio.run(_run())


def test_add_baseline_system_error_invalid_zone():
    """Test error when specifying non-existent zone."""
    name = "test_invalid_zone"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {
                    "name": name,
                })
                create_data = unwrap(create_resp)
                assert create_data.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })
                assert unwrap(load_resp).get("ok") is True

                # Try to add system with non-existent zone
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": ["NonExistentZone"],
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is False
                assert "not found" in system_data["error"]

    asyncio.run(_run())


# ============================================================================
# System 4 (PSZ-HP) Tests - Comprehensive Coverage
# ============================================================================

def test_add_baseline_system_4_psz_hp():
    """Test adding System 4 (PSZ-HP) - basic success."""
    name = "test_sys4_basic"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                assert create_data.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "economizer": True,
                    "system_name": "PSZ-HP Test",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "PSZ-HP (Baseline System 4)"
                assert system_data["system"]["heating"] == "Heat Pump"
                assert system_data["system"]["cooling"] == "Heat Pump"

    asyncio.run(_run())


def test_system_4_multi_zone_rejection():
    """Test System 4 rejects multiple zones."""
    name = "test_sys4_multi_zone"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                # Create a second thermal zone
                zone2_resp = await session.call_tool("create_thermal_zone", {"name": "Zone 2"})
                assert unwrap(zone2_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Ensure we have at least 2 zones
                assert len(zone_names) >= 2

                # Try to add PSZ-HP with 2 zones (should fail)
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": zone_names[:2],
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is False
                assert "requires exactly 1 zone" in system_data["error"]

    asyncio.run(_run())


def test_add_baseline_system_5_vav_reheat():
    """Test adding System 5 (Packaged VAV w/ Reheat)."""
    name = "test_sys5_basic"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_names = [z["name"] for z in unwrap(zones_resp)["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "heating_fuel": "NaturalGas",
                    "system_name": "VAV Reheat System",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "Packaged VAV w/ Reheat (Baseline System 5)"
                assert system_data["system"]["heating"] == "Hot Water Reheat"
                assert "hot_water_loop" in system_data["system"]
                assert "terminals" in system_data["system"]

    asyncio.run(_run())


def test_add_baseline_system_6_vav_pfp():
    """Test adding System 6 (Packaged VAV w/ PFP)."""
    name = "test_sys6_basic"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_names = [z["name"] for z in unwrap(zones_resp)["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP System",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "Packaged VAV w/ PFP (Baseline System 6)"
                assert system_data["system"]["heating"] == "Electric Reheat in PFP Boxes"
                assert "terminals" in system_data["system"]

    asyncio.run(_run())


def test_unimplemented_system_type():
    """System types >10 should fail gracefully."""
    name = "test_unimplemented"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_names = [z["name"] for z in unwrap(zones_resp)["thermal_zones"]]

                # Try System 11 (doesn't exist)
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 11,
                    "thermal_zone_names": zone_names,
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is False
                assert "not yet implemented" in system_data["error"] or "Invalid system_type" in system_data["error"]

    asyncio.run(_run())


# ============================================================================
# System 7 (Central VAV w/ Reheat) Tests - Comprehensive Coverage
# ============================================================================

def test_add_baseline_system_7_central_vav_reheat():
    """Test adding System 7 (Central VAV w/ Reheat) - basic success."""
    name = "test_sys7_basic"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_names = [z["name"] for z in unwrap(zones_resp)["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "heating_fuel": "NaturalGas",
                    "system_name": "Central VAV System",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "VAV w/ Reheat (Baseline System 7)"
                assert system_data["system"]["equipment_type"] == "Built-up VAV"
                assert system_data["system"]["heating"] == "Hot Water"
                assert system_data["system"]["cooling"] == "Chilled Water"
                assert "air_loop" in system_data["system"]
                assert "chilled_water_loop" in system_data["system"]
                assert "hot_water_loop" in system_data["system"]
                assert "condenser_loop" in system_data["system"]
                assert "terminals" in system_data["system"]

    asyncio.run(_run())


def test_system_7_plant_loop_verification():
    """Verify System 7 creates all 3 plant loops."""
    name = "test_sys7_plants"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_names = [z["name"] for z in unwrap(zones_resp)["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })
                system_data = unwrap(system_resp)
                assert system_data.get("ok") is True

                # Verify plant loops created
                plant_loops_resp = await session.call_tool("list_plant_loops", {})
                plant_loop_names = [pl["name"] for pl in unwrap(plant_loops_resp)["plant_loops"]]

                # Should have chilled water, hot water, and condenser loops
                assert any("Chilled Water" in name for name in plant_loop_names)
                assert any("Hot Water" in name for name in plant_loop_names)
                assert any("Condenser" in name for name in plant_loop_names)

    asyncio.run(_run())


# ============================================================================
# System 8 (Central VAV w/ PFP) Tests - Comprehensive Coverage
# ============================================================================

def test_add_baseline_system_8_central_vav_pfp():
    """Test adding System 8 (Central VAV w/ PFP) - basic success."""
    name = "test_sys8_basic"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_names = [z["name"] for z in unwrap(zones_resp)["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV PFP",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "VAV w/ PFP (Baseline System 8)"
                assert system_data["system"]["equipment_type"] == "Built-up VAV"
                assert system_data["system"]["heating"] == "Hot Water"
                assert system_data["system"]["cooling"] == "Chilled Water"
                assert "chilled_water_loop" in system_data["system"]
                assert "hot_water_loop" in system_data["system"]
                assert "condenser_loop" in system_data["system"]
                assert "terminals" in system_data["system"]

    asyncio.run(_run())


def test_system_8_pfp_terminals():
    """Verify System 8 creates PFP terminals (not VAV reheat)."""
    name = "test_sys8_pfp"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_names = [z["name"] for z in unwrap(zones_resp)["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "PFP System",
                })
                system_data = unwrap(system_resp)
                assert system_data.get("ok") is True

                # Verify terminals are PFP type
                terminals = system_data["system"]["terminals"]
                assert all("PFP Terminal" in t for t in terminals)

    asyncio.run(_run())


# ============================================================================
# System 9 (Gas Unit Heaters) Tests
# ============================================================================

def test_add_baseline_system_9_gas_unit_heaters():
    """Test adding System 9 (Gas Unit Heaters) - basic success."""
    name = "test_sys9_basic"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_names = [z["name"] for z in unwrap(zones_resp)["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 9,
                    "thermal_zone_names": zone_names,
                    "heating_fuel": "NaturalGas",
                    "system_name": "Gas Heaters",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "Heating & Ventilation (Baseline System 9)"
                assert system_data["system"]["equipment_type"] == "Zone Unit Heaters"
                assert system_data["system"]["heating"] == "Gas Unit Heaters"
                assert system_data["system"]["cooling"] == "None"
                assert "equipment" in system_data["system"]
                assert len(system_data["system"]["equipment"]) == len(zone_names)

    asyncio.run(_run())


# ============================================================================
# System 10 (Electric Unit Heaters) Tests
# ============================================================================

def test_add_baseline_system_10_electric_unit_heaters():
    """Test adding System 10 (Electric Unit Heaters) - basic success."""
    name = "test_sys10_basic"

    async def _run():
        sp = server_params()

        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_data["osm_path"]})
                assert unwrap(load_resp).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_names = [z["name"] for z in unwrap(zones_resp)["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 10,
                    "thermal_zone_names": zone_names,
                    "heating_fuel": "Electricity",
                    "system_name": "Electric Heaters",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["type"] == "Heating & Ventilation (Baseline System 10)"
                assert system_data["system"]["equipment_type"] == "Zone Unit Heaters"
                assert system_data["system"]["heating"] == "Electric Unit Heaters"
                assert system_data["system"]["cooling"] == "None"
                assert "equipment" in system_data["system"]
                assert len(system_data["system"]["equipment"]) == len(zone_names)

    asyncio.run(_run())


def test_baseline_system_07_multi_zone():
    """Test System 7 (Central VAV) on 10-zone baseline model."""
    import uuid
    name = f"test_sys7_bl_{uuid.uuid4().hex[:8]}"

    async def _run():
        sp = server_params()
        async with stdio_client(sp) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr).get("ok") is True

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]
                assert len(zone_names) == 10

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "heating_fuel": "NaturalGas",
                    "system_name": "Baseline VAV",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert system_data["system"]["zones_served"] == 10
                assert "chilled_water_loop" in system_data["system"]
                assert "hot_water_loop" in system_data["system"]
                assert "condenser_loop" in system_data["system"]
                assert len(system_data["system"]["terminals"]) == 10

    asyncio.run(_run())
