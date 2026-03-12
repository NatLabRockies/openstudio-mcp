"""Validation tests for ASHRAE baseline systems 9-10 (Unit Heaters)."""

import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

# ============================================================================
# SYSTEM 9: Gas Unit Heaters - Zone Equipment (2 tests)
# ============================================================================

@pytest.mark.integration
def test_system_9_unit_heaters():
    """Verify System 9 creates gas unit heaters."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s9_heaters"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 9,
                    "thermal_zone_names": zone_names,
                    "system_name": "Gas Heaters",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert "equipment" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_9_no_cooling():
    """Verify System 9 has no cooling."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s9_no_clg"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 9,
                    "thermal_zone_names": zone_names,
                    "system_name": "Gas Heaters",
                })
                system_data = unwrap(system_resp)

                # System 9 should have no cooling or "None"
                cooling = system_data["system"].get("cooling", "None")
                assert cooling == "None" or cooling is None

    asyncio.run(_run())


# ============================================================================
# SYSTEM 10: Electric Unit Heaters - Zone Equipment (2 tests)
# ============================================================================

@pytest.mark.integration
def test_system_10_unit_heaters():
    """Verify System 10 creates electric unit heaters."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s10_heaters"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 10,
                    "thermal_zone_names": zone_names,
                    "system_name": "Electric Heaters",
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is True
                assert "equipment" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_10_no_cooling():
    """Verify System 10 has no cooling."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s10_no_clg"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 10,
                    "thermal_zone_names": zone_names,
                    "system_name": "Electric Heaters",
                })
                system_data = unwrap(system_resp)

                # System 10 should have no cooling or "None"
                cooling = system_data["system"].get("cooling", "None")
                assert cooling == "None" or cooling is None

    asyncio.run(_run())
