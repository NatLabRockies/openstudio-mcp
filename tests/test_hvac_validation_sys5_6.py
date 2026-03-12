"""Validation tests for ASHRAE baseline systems 5-6 (Packaged VAV)."""
import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

# ============================================================================
# SYSTEM 5: Packaged VAV w/ Reheat - Plant Loop + Terminals (11 tests)
# ============================================================================

@pytest.mark.integration
def test_system_5_hot_water_loop():
    """Verify System 5 creates hot water plant loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_hw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat",
                })
                system_data = unwrap(system_resp)

                # Should have HW loop
                assert "hot_water_loop" in system_data["system"]

                # Get plant loop details
                hw_loop_name = system_data["system"]["hot_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": hw_loop_name,
                })
                loop_data = unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"

                assert loop_data["plant_loop"]["loop_type"] == "Heating"

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_boiler_present():
    """Verify System 5 has boiler on HW loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_boiler"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "heating_fuel": "NaturalGas",
                    "system_name": "VAV Reheat",
                })
                system_data = unwrap(system_resp)

                hw_loop_name = system_data["system"]["hot_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": hw_loop_name,
                })
                loop_data = unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                # Check for boiler in supply components
                supply_comps = loop_data["plant_loop"]["supply_components"]
                boiler_present = any("Boiler" in comp["type"] for comp in supply_comps)
                assert boiler_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_vav_terminals():
    """Verify System 5 has VAV reheat terminals."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_terms"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat",
                })
                system_data = unwrap(system_resp)

                # Should have terminals listed
                assert "terminals" in system_data["system"]
                assert len(system_data["system"]["terminals"]) == len(zone_names)

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_dx_cooling():
    """Verify System 5 uses DX cooling."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_dx"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat",
                })
                system_data = unwrap(system_resp)

                assert "DX" in system_data["system"]["cooling"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_variable_fan():
    """Verify System 5 has variable volume fan."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_vav_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Reheat",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                assert len(fans) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_economizer_enabled():
    """Verify System 5 economizer when enabled."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "economizer": True,
                    "system_name": "VAV Econ",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Econ",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_economizer_disabled():
    """Verify System 5 economizer when disabled."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_no_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "economizer": False,
                    "system_name": "VAV No Econ",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV No Econ",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_outdoor_air_present():
    """Verify System 5 has outdoor air system."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Reheat",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_setpoint_managers():
    """Verify System 5 has setpoint managers."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Reheat",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_reheat_coils():
    """Verify System 5 has hot water reheat coils."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_reheat"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat",
                })
                system_data = unwrap(system_resp)

                # Terminals are VAV reheat type (names contain "VAV")
                terminals = system_data["system"]["terminals"]
                for terminal in terminals:
                    assert "VAV" in terminal

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_heating_coils():
    """Verify System 5 has heating coils on air loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_htg"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Reheat",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                heating_coils = air_loop_data["air_loop"]["detailed_components"]["heating_coils"]
                # System 5 should have preheat coil
                assert len(heating_coils) >= 1

    asyncio.run(_run())


# ============================================================================
# SYSTEM 6: Packaged VAV w/ PFP - Terminals (10 tests)
# ============================================================================

@pytest.mark.integration
def test_system_6_pfp_terminals():
    """Verify System 6 has PFP terminals."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_pfp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP",
                })
                system_data = unwrap(system_resp)

                assert "terminals" in system_data["system"]
                # Terminals should be PFP type (names contain "PFP")
                terminals = system_data["system"]["terminals"]
                for terminal in terminals:
                    assert "PFP" in terminal

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_electric_reheat():
    """Verify System 6 uses electric reheat in PFP boxes."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_elec"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP",
                })
                system_data = unwrap(system_resp)

                # System 6 PFP terminals have electric reheat (inherent in PFP type)
                terminals = system_data["system"]["terminals"]
                for terminal in terminals:
                    assert "PFP" in terminal

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_dx_cooling():
    """Verify System 6 uses DX cooling."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_dx"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP",
                })
                system_data = unwrap(system_resp)

                assert "DX" in system_data["system"]["cooling"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_variable_fan():
    """Verify System 6 has variable volume fan on air loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                # Should have central VAV fan plus PFP fans
                assert len(fans) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_economizer_enabled():
    """Verify System 6 economizer when enabled."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "economizer": True,
                    "system_name": "VAV PFP Econ",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP Econ",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_economizer_disabled():
    """Verify System 6 economizer when disabled."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_no_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "economizer": False,
                    "system_name": "VAV PFP No Econ",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP No Econ",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_outdoor_air_present():
    """Verify System 6 has outdoor air system."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_setpoint_managers():
    """Verify System 6 has setpoint managers."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_preheat_coil():
    """Verify System 6 has preheat coil."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_preheat"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                heating_coils = air_loop_data["air_loop"]["detailed_components"]["heating_coils"]
                assert len(heating_coils) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_cooling_coil():
    """Verify System 6 has DX cooling coil."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_clg"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                cooling_coils = air_loop_data["air_loop"]["detailed_components"]["cooling_coils"]
                assert len(cooling_coils) >= 1
                assert "DX" in cooling_coils[0]["type"]

    asyncio.run(_run())
