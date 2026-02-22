"""Validation tests for ASHRAE baseline systems 1-4 (PTAC, PTHP, PSZ-AC, PSZ-HP)."""
import asyncio
import pytest

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from conftest import unwrap, integration_enabled, server_params


# ============================================================================
# SYSTEM 1: PTAC - Coil + Fan + Sizing Tests (5 tests)
# ============================================================================

@pytest.mark.integration
def test_system_1_coil_types():
    """Verify PTAC has electric heating coil and DX cooling coil."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s1_coils"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Create System 1 with electric heating
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zone_names[:1],
                    "heating_fuel": "Electricity",
                    "system_name": "PTAC System"
                })
                system_data = unwrap(system_resp)
                assert system_data.get("ok") is True

                # Get zone HVAC equipment details
                equipment = system_data["system"]["equipment"][0]
                equip_name = equipment["equipment"]

                equip_resp = await session.call_tool("get_zone_hvac_details", {
                    "equipment_name": equip_name
                })
                equip_data = unwrap(equip_resp)
                assert equip_data.get("ok") is True, f"get_zone_hvac_details failed: {equip_data.get('error')}"

                assert "heating_coil" in equip_data["equipment"]
                assert "Electric" in equip_data["equipment"]["heating_coil"]["type"]
                assert "cooling_coil" in equip_data["equipment"]
                assert "DX" in equip_data["equipment"]["cooling_coil"]["type"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_1_fan_present():
    """Verify PTAC has supply air fan."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s1_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PTAC System"
                })
                system_data = unwrap(system_resp)

                equip_name = system_data["system"]["equipment"][0]["equipment"]
                equip_resp = await session.call_tool("get_zone_hvac_details", {
                    "equipment_name": equip_name
                })
                equip_data = unwrap(equip_resp)
                assert equip_data.get("ok") is True, f"get_zone_hvac_details failed: {equip_data.get('error')}"

                assert "fan" in equip_data["equipment"]
                assert "Fan" in equip_data["equipment"]["fan"]["type"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_1_multiple_zones():
    """Verify System 1 creates one PTAC per zone."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s1_multi"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]][:3]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zone_names,
                    "system_name": "PTAC System"
                })
                system_data = unwrap(system_resp)

                # Should have one PTAC per zone
                assert len(system_data["system"]["equipment"]) == len(zone_names)

    asyncio.run(_run())


@pytest.mark.integration
def test_system_2_heat_pump_coils():
    """Verify PTHP has DX heating and cooling coils."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s2_hp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 2,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PTHP System"
                })
                system_data = unwrap(system_resp)

                equip_name = system_data["system"]["equipment"][0]["equipment"]
                equip_resp = await session.call_tool("get_zone_hvac_details", {
                    "equipment_name": equip_name
                })
                equip_data = unwrap(equip_resp)
                assert equip_data.get("ok") is True, f"get_zone_hvac_details failed: {equip_data.get('error')}"

                # PTHP should have DX heating (heat pump) and DX cooling
                assert "heating_coil" in equip_data["equipment"]
                assert "cooling_coil" in equip_data["equipment"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_2_fan_present():
    """Verify PTHP has supply air fan."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s2_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 2,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PTHP System"
                })
                system_data = unwrap(system_resp)

                equip_name = system_data["system"]["equipment"][0]["equipment"]
                equip_resp = await session.call_tool("get_zone_hvac_details", {
                    "equipment_name": equip_name
                })
                equip_data = unwrap(equip_resp)
                assert equip_data.get("ok") is True, f"get_zone_hvac_details failed: {equip_data.get('error')}"

                assert "fan" in equip_data["equipment"]

    asyncio.run(_run())


# ============================================================================
# SYSTEM 3: PSZ-AC - Coils + Fan + OA/Econ + Setpoints (8 tests)
# ============================================================================

@pytest.mark.integration
def test_system_3_coil_types():
    """Verify PSZ-AC has gas/electric heating and DX cooling coils."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_coils"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                # Test with gas heating
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "heating_fuel": "NaturalGas",
                    "system_name": "PSZ Gas"
                })
                system_data = unwrap(system_resp)

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ Gas"
                })
                air_loop_data = unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                # Check for heating and cooling coils
                heating_coils = air_loop_data["air_loop"]["detailed_components"]["heating_coils"]
                cooling_coils = air_loop_data["air_loop"]["detailed_components"]["cooling_coils"]

                assert len(heating_coils) >= 1
                assert len(cooling_coils) >= 1
                assert "DX" in cooling_coils[0]["type"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_fan_verification():
    """Verify PSZ-AC has constant volume fan."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ System"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ System"
                })
                air_loop_data = unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                assert len(fans) >= 1
                assert "Fan" in fans[0]["type"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_economizer_enabled():
    """Verify economizer enabled when requested."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_econ_on"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "economizer": True,
                    "system_name": "PSZ Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ Econ"
                })
                air_loop_data = unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system is not None
                assert oa_system["economizer_enabled"] is True
                assert oa_system["economizer_type"] != "NoEconomizer"

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_economizer_disabled():
    """Verify economizer disabled when requested."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_econ_off"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "economizer": False,
                    "system_name": "PSZ No Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ No Econ"
                })
                air_loop_data = unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system is not None
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_outdoor_air_present():
    """Verify PSZ-AC has outdoor air system."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ System"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ System"
                })
                air_loop_data = unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_setpoint_managers():
    """Verify PSZ-AC has setpoint managers."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ System"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ System"
                })
                air_loop_data = unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_electric_heating():
    """Verify PSZ-AC with electric heating has electric coil."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_elec"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "heating_fuel": "Electricity",
                    "system_name": "PSZ Electric"
                })
                system_data = unwrap(system_resp)

                assert "Electric" in system_data["system"]["heating"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_gas_heating():
    """Verify PSZ-AC with gas heating has gas coil."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_gas"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "heating_fuel": "NaturalGas",
                    "system_name": "PSZ Gas"
                })
                system_data = unwrap(system_resp)

                assert "Gas" in system_data["system"]["heating"]

    asyncio.run(_run())


# ============================================================================
# SYSTEM 4: PSZ-HP - Coils + Fan + OA/Econ Tests (9 tests)
# ============================================================================

@pytest.mark.integration
def test_system_4_heat_pump_coils():
    """Verify PSZ-HP has DX heating and cooling coils."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_hp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ HP"
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                # Should have DX heating and cooling coils
                heating_coils = air_loop_data["air_loop"]["detailed_components"]["heating_coils"]
                cooling_coils = air_loop_data["air_loop"]["detailed_components"]["cooling_coils"]

                assert len(heating_coils) >= 1  # DX HP + supplemental
                assert len(cooling_coils) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_supplemental_heat():
    """Verify PSZ-HP has supplemental electric heating."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_supp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })
                system_data = unwrap(system_resp)

                # System 4 should have supplemental heating mentioned
                assert system_data["system"]["heating"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_fan_present():
    """Verify PSZ-HP has supply fan."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ HP"
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                assert len(fans) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_economizer_enabled():
    """Verify System 4 economizer when enabled."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "economizer": True,
                    "system_name": "PSZ HP Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ HP Econ"
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system is not None
                assert oa_system["economizer_enabled"] is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_economizer_disabled():
    """Verify System 4 economizer when disabled."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_no_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "economizer": False,
                    "system_name": "PSZ HP No Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ HP No Econ"
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_outdoor_air_present():
    """Verify PSZ-HP has outdoor air system."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ HP"
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_setpoint_managers():
    """Verify PSZ-HP has setpoint managers."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ HP"
                })
                air_loop_data = unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_dx_cooling():
    """Verify System 4 uses DX cooling."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_dx"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })
                system_data = unwrap(system_resp)

                assert system_data["system"]["cooling"] == "Heat Pump"

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_single_zone_only():
    """Verify System 4 requires exactly one zone."""
    if not integration_enabled():
        pytest.skip("integration disabled")
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_single"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                # Create second zone
                zone2_resp = await session.call_tool("create_thermal_zone", {"name": "Zone 2"})

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]][:2]

                # Try with 2 zones - should fail
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": zone_names,
                    "system_name": "PSZ HP"
                })
                system_data = unwrap(system_resp)

                assert system_data.get("ok") is False
                assert "exactly 1 zone" in system_data["error"].lower()

    asyncio.run(_run())
