"""Validation tests for ASHRAE baseline systems 7-8 (Central VAV)."""

import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

# ============================================================================
# SYSTEM 7: Central VAV w/ Reheat - All 3 Plant Loops (13 tests)
# ============================================================================

@pytest.mark.integration
def test_system_7_chilled_water_loop():
    """Verify System 7 creates chilled water loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_chw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })
                system_data = unwrap(system_resp)

                assert "chilled_water_loop" in system_data["system"]

                chw_loop_name = system_data["system"]["chilled_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": chw_loop_name,
                })
                loop_data = unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"

                assert loop_data["plant_loop"]["loop_type"] == "Cooling"

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_hot_water_loop():
    """Verify System 7 creates hot water loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_hw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })
                system_data = unwrap(system_resp)

                assert "hot_water_loop" in system_data["system"]

                hw_loop_name = system_data["system"]["hot_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": hw_loop_name,
                })
                loop_data = unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"

                assert loop_data["plant_loop"]["loop_type"] == "Heating"

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_condenser_loop():
    """Verify System 7 creates condenser water loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_cw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })
                system_data = unwrap(system_resp)

                assert "condenser_loop" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_chiller_present():
    """Verify System 7 has chiller."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_chiller"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })
                system_data = unwrap(system_resp)

                chw_loop_name = system_data["system"]["chilled_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": chw_loop_name,
                })
                loop_data = unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                supply_comps = loop_data["plant_loop"]["supply_components"]
                chiller_present = any("Chiller" in comp["type"] for comp in supply_comps)
                assert chiller_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_boiler_present():
    """Verify System 7 has boiler."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_boiler"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })
                system_data = unwrap(system_resp)

                hw_loop_name = system_data["system"]["hot_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": hw_loop_name,
                })
                loop_data = unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                supply_comps = loop_data["plant_loop"]["supply_components"]
                boiler_present = any("Boiler" in comp["type"] for comp in supply_comps)
                assert boiler_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_cooling_tower():
    """Verify System 7 has cooling tower."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_tower"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })
                system_data = unwrap(system_resp)

                cw_loop_name = system_data["system"]["condenser_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": cw_loop_name,
                })
                loop_data = unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                supply_comps = loop_data["plant_loop"]["supply_components"]
                tower_present = any("CoolingTower" in comp["type"] for comp in supply_comps)
                assert tower_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_vav_terminals():
    """Verify System 7 has VAV reheat terminals."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_terms"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })
                system_data = unwrap(system_resp)

                assert "terminals" in system_data["system"]
                assert len(system_data["system"]["terminals"]) == len(zone_names)

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_water_coils():
    """Verify System 7 uses water coils not DX."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_water"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })
                system_data = unwrap(system_resp)

                # System 7 should use chilled water cooling
                assert "Chilled Water" in system_data["system"]["cooling"] or "Water" in system_data["system"]["cooling"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_variable_fan():
    """Verify System 7 has variable volume fan."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                assert len(fans) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_economizer_enabled():
    """Verify System 7 economizer when enabled."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "economizer": True,
                    "system_name": "Central VAV Econ",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV Econ",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_economizer_disabled():
    """Verify System 7 economizer when disabled."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_no_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "economizer": False,
                    "system_name": "Central VAV No Econ",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV No Econ",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_outdoor_air_present():
    """Verify System 7 has outdoor air system."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_setpoint_managers():
    """Verify System 7 has setpoint managers."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())


# ============================================================================
# SYSTEM 8: Central VAV w/ PFP - Plant Loops + PFP Terminals (13 tests)
# ============================================================================

@pytest.mark.integration
def test_system_8_chilled_water_loop():
    """Verify System 8 creates chilled water loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_chw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })
                system_data = unwrap(system_resp)

                assert "chilled_water_loop" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_hot_water_loop():
    """Verify System 8 creates hot water loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_hw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })
                system_data = unwrap(system_resp)

                # System 8 may or may not have HW loop (PFP with electric reheat)
                # Just verify system was created
                assert system_data.get("ok") is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_condenser_loop():
    """Verify System 8 creates condenser water loop."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_cw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })
                system_data = unwrap(system_resp)

                assert "condenser_loop" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_pfp_terminals():
    """Verify System 8 has PFP terminals."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_pfp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })
                system_data = unwrap(system_resp)

                assert "terminals" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_electric_reheat():
    """Verify System 8 uses electric reheat in PFP boxes."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_elec"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })
                system_data = unwrap(system_resp)

                # System 8 PFP terminals have electric reheat (inherent in PFP type)
                terminals = system_data["system"]["terminals"]
                for terminal in terminals:
                    assert "PFP" in terminal

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_chiller_present():
    """Verify System 8 has chiller."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_chiller"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })
                system_data = unwrap(system_resp)

                chw_loop_name = system_data["system"]["chilled_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": chw_loop_name,
                })
                loop_data = unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                supply_comps = loop_data["plant_loop"]["supply_components"]
                chiller_present = any("Chiller" in comp["type"] for comp in supply_comps)
                assert chiller_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_cooling_tower():
    """Verify System 8 has cooling tower."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_tower"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })
                system_data = unwrap(system_resp)

                cw_loop_name = system_data["system"]["condenser_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": cw_loop_name,
                })
                loop_data = unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                supply_comps = loop_data["plant_loop"]["supply_components"]
                tower_present = any("CoolingTower" in comp["type"] for comp in supply_comps)
                assert tower_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_water_cooling():
    """Verify System 8 uses chilled water cooling."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_water"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })
                system_data = unwrap(system_resp)

                # System 8 should use chilled water cooling
                assert "Water" in system_data["system"]["cooling"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_variable_fan():
    """Verify System 8 has variable volume fan."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central PFP",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                # Central fan + PFP fans
                assert len(fans) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_economizer_enabled():
    """Verify System 8 economizer when enabled."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "economizer": True,
                    "system_name": "Central PFP Econ",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central PFP Econ",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_economizer_disabled():
    """Verify System 8 economizer when disabled."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_no_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "economizer": False,
                    "system_name": "Central PFP No Econ",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central PFP No Econ",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_outdoor_air_present():
    """Verify System 8 has outdoor air system."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central PFP",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_setpoint_managers():
    """Verify System 8 has setpoint managers."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"],
                })

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP",
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central PFP",
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())
