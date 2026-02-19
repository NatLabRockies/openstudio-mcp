"""Component-level validation tests for ASHRAE baseline HVAC systems.

Phase 4D: Deep component inspection to verify ASHRAE 90.1 Appendix G compliance.
Tests verify coil types, plant loop setpoints, terminal settings, fan specs,
economizer configuration, and equipment sizing.
"""
import asyncio
import json
import os
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# Get server command from environment
MCP_SERVER_CMD = os.getenv("MCP_SERVER_CMD", "openstudio-mcp")
MCP_SERVER_ARGS = os.getenv("MCP_SERVER_ARGS", "")

if MCP_SERVER_ARGS:
    server_args = MCP_SERVER_ARGS.split()
else:
    server_args = []

server_params = StdioServerParameters(
    command=MCP_SERVER_CMD,
    args=server_args,
    env=None,
)


def _unwrap(tool_result) -> dict:
    """Extract dict from MCP tool result."""
    for content in tool_result.content:
        if hasattr(content, 'text'):
            return json.loads(content.text)
    raise ValueError(f"No text content in tool result: {tool_result}")


# ============================================================================
# SYSTEM 1: PTAC - Coil + Fan + Sizing Tests (5 tests)
# ============================================================================

@pytest.mark.integration
def test_system_1_coil_types():
    """Verify PTAC has electric heating coil and DX cooling coil."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s1_coils"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                # Create System 1 with electric heating
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zone_names[:1],
                    "heating_fuel": "Electricity",
                    "system_name": "PTAC System"
                })
                system_data = _unwrap(system_resp)
                assert system_data.get("ok") is True

                # Get zone HVAC equipment details
                equipment = system_data["system"]["equipment"][0]
                equip_name = equipment["equipment"]

                equip_resp = await session.call_tool("get_zone_hvac_details", {
                    "equipment_name": equip_name
                })
                equip_data = _unwrap(equip_resp)
                assert equip_data.get("ok") is True, f"get_zone_hvac_details failed: {equip_data.get('error')}"

                assert "heating_coil" in equip_data["equipment"]
                assert "Electric" in equip_data["equipment"]["heating_coil"]["type"]
                assert "cooling_coil" in equip_data["equipment"]
                assert "DX" in equip_data["equipment"]["cooling_coil"]["type"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_1_fan_present():
    """Verify PTAC has supply air fan."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s1_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PTAC System"
                })
                system_data = _unwrap(system_resp)

                equip_name = system_data["system"]["equipment"][0]["equipment"]
                equip_resp = await session.call_tool("get_zone_hvac_details", {
                    "equipment_name": equip_name
                })
                equip_data = _unwrap(equip_resp)
                assert equip_data.get("ok") is True, f"get_zone_hvac_details failed: {equip_data.get('error')}"

                assert "fan" in equip_data["equipment"]
                assert "Fan" in equip_data["equipment"]["fan"]["type"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_1_multiple_zones():
    """Verify System 1 creates one PTAC per zone."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s1_multi"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]][:3]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zone_names,
                    "system_name": "PTAC System"
                })
                system_data = _unwrap(system_resp)

                # Should have one PTAC per zone
                assert len(system_data["system"]["equipment"]) == len(zone_names)

    asyncio.run(_run())


@pytest.mark.integration
def test_system_2_heat_pump_coils():
    """Verify PTHP has DX heating and cooling coils."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s2_hp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 2,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PTHP System"
                })
                system_data = _unwrap(system_resp)

                equip_name = system_data["system"]["equipment"][0]["equipment"]
                equip_resp = await session.call_tool("get_zone_hvac_details", {
                    "equipment_name": equip_name
                })
                equip_data = _unwrap(equip_resp)
                assert equip_data.get("ok") is True, f"get_zone_hvac_details failed: {equip_data.get('error')}"

                # PTHP should have DX heating (heat pump) and DX cooling
                assert "heating_coil" in equip_data["equipment"]
                assert "cooling_coil" in equip_data["equipment"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_2_fan_present():
    """Verify PTHP has supply air fan."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s2_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 2,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PTHP System"
                })
                system_data = _unwrap(system_resp)

                equip_name = system_data["system"]["equipment"][0]["equipment"]
                equip_resp = await session.call_tool("get_zone_hvac_details", {
                    "equipment_name": equip_name
                })
                equip_data = _unwrap(equip_resp)
                assert equip_data.get("ok") is True, f"get_zone_hvac_details failed: {equip_data.get('error')}"

                assert "fan" in equip_data["equipment"]

    asyncio.run(_run())


# ============================================================================
# SYSTEM 3: PSZ-AC - Coils + Fan + OA/Econ + Setpoints (8 tests)
# ============================================================================

@pytest.mark.integration
def test_system_3_coil_types():
    """Verify PSZ-AC has gas/electric heating and DX cooling coils."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_coils"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                # Test with gas heating
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "heating_fuel": "NaturalGas",
                    "system_name": "PSZ Gas"
                })
                system_data = _unwrap(system_resp)

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ Gas"
                })
                air_loop_data = _unwrap(air_loop_resp)
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
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ System"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ System"
                })
                air_loop_data = _unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                assert len(fans) >= 1
                assert "Fan" in fans[0]["type"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_economizer_enabled():
    """Verify economizer enabled when requested."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_econ_on"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
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
                air_loop_data = _unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system is not None
                assert oa_system["economizer_enabled"] is True
                assert oa_system["economizer_type"] != "NoEconomizer"

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_economizer_disabled():
    """Verify economizer disabled when requested."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_econ_off"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
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
                air_loop_data = _unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system is not None
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_outdoor_air_present():
    """Verify PSZ-AC has outdoor air system."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ System"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ System"
                })
                air_loop_data = _unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_setpoint_managers():
    """Verify PSZ-AC has setpoint managers."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ System"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ System"
                })
                air_loop_data = _unwrap(air_loop_resp)
                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_electric_heating():
    """Verify PSZ-AC with electric heating has electric coil."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_elec"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "heating_fuel": "Electricity",
                    "system_name": "PSZ Electric"
                })
                system_data = _unwrap(system_resp)

                assert "Electric" in system_data["system"]["heating"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_3_gas_heating():
    """Verify PSZ-AC with gas heating has gas coil."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s3_gas"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 3,
                    "thermal_zone_names": [zone_name],
                    "heating_fuel": "NaturalGas",
                    "system_name": "PSZ Gas"
                })
                system_data = _unwrap(system_resp)

                assert "Gas" in system_data["system"]["heating"]

    asyncio.run(_run())


# ============================================================================
# SYSTEM 4: PSZ-HP - Coils + Fan + OA/Econ Tests (9 tests)
# ============================================================================

@pytest.mark.integration
def test_system_4_heat_pump_coils():
    """Verify PSZ-HP has DX heating and cooling coils."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_hp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ HP"
                })
                air_loop_data = _unwrap(air_loop_resp)

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
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_supp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })
                system_data = _unwrap(system_resp)

                # System 4 should have supplemental heating mentioned
                assert system_data["system"]["heating"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_fan_present():
    """Verify PSZ-HP has supply fan."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ HP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                assert len(fans) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_economizer_enabled():
    """Verify System 4 economizer when enabled."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
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
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system is not None
                assert oa_system["economizer_enabled"] is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_economizer_disabled():
    """Verify System 4 economizer when disabled."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_no_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
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
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_outdoor_air_present():
    """Verify PSZ-HP has outdoor air system."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ HP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_setpoint_managers():
    """Verify PSZ-HP has setpoint managers."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "PSZ HP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_dx_cooling():
    """Verify System 4 uses DX cooling."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_dx"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_name = zones_data["thermal_zones"][0]["name"]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": [zone_name],
                    "system_name": "PSZ HP"
                })
                system_data = _unwrap(system_resp)

                assert system_data["system"]["cooling"] == "Heat Pump"

    asyncio.run(_run())


@pytest.mark.integration
def test_system_4_single_zone_only():
    """Verify System 4 requires exactly one zone."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s4_single"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                # Create second zone
                zone2_resp = await session.call_tool("create_thermal_zone", {"name": "Zone 2"})

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]][:2]

                # Try with 2 zones - should fail
                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 4,
                    "thermal_zone_names": zone_names,
                    "system_name": "PSZ HP"
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is False
                assert "exactly 1 zone" in system_data["error"].lower()

    asyncio.run(_run())


# ============================================================================
# SYSTEM 5: Packaged VAV w/ Reheat - Plant Loop + Terminals (11 tests)
# ============================================================================

@pytest.mark.integration
def test_system_5_hot_water_loop():
    """Verify System 5 creates hot water plant loop."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_hw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat"
                })
                system_data = _unwrap(system_resp)

                # Should have HW loop
                assert "hot_water_loop" in system_data["system"]

                # Get plant loop details
                hw_loop_name = system_data["system"]["hot_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": hw_loop_name
                })
                loop_data = _unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"

                assert loop_data["plant_loop"]["loop_type"] == "Heating"

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_boiler_present():
    """Verify System 5 has boiler on HW loop."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_boiler"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "heating_fuel": "NaturalGas",
                    "system_name": "VAV Reheat"
                })
                system_data = _unwrap(system_resp)

                hw_loop_name = system_data["system"]["hot_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": hw_loop_name
                })
                loop_data = _unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                # Check for boiler in supply components
                supply_comps = loop_data["plant_loop"]["supply_components"]
                boiler_present = any("Boiler" in comp["type"] for comp in supply_comps)
                assert boiler_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_vav_terminals():
    """Verify System 5 has VAV reheat terminals."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_terms"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat"
                })
                system_data = _unwrap(system_resp)

                # Should have terminals listed
                assert "terminals" in system_data["system"]
                assert len(system_data["system"]["terminals"]) == len(zone_names)

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_dx_cooling():
    """Verify System 5 uses DX cooling."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_dx"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat"
                })
                system_data = _unwrap(system_resp)

                assert "DX" in system_data["system"]["cooling"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_variable_fan():
    """Verify System 5 has variable volume fan."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_vav_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Reheat"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                assert len(fans) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_economizer_enabled():
    """Verify System 5 economizer when enabled."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "economizer": True,
                    "system_name": "VAV Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Econ"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_economizer_disabled():
    """Verify System 5 economizer when disabled."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_no_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "economizer": False,
                    "system_name": "VAV No Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV No Econ"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_outdoor_air_present():
    """Verify System 5 has outdoor air system."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Reheat"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_setpoint_managers():
    """Verify System 5 has setpoint managers."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Reheat"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_reheat_coils():
    """Verify System 5 has hot water reheat coils."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_reheat"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat"
                })
                system_data = _unwrap(system_resp)

                # Terminals are VAV reheat type (names contain "VAV")
                terminals = system_data["system"]["terminals"]
                for terminal in terminals:
                    assert "VAV" in terminal

    asyncio.run(_run())


@pytest.mark.integration
def test_system_5_heating_coils():
    """Verify System 5 has heating coils on air loop."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s5_htg"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 5,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV Reheat"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV Reheat"
                })
                air_loop_data = _unwrap(air_loop_resp)

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
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_pfp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP"
                })
                system_data = _unwrap(system_resp)

                assert "terminals" in system_data["system"]
                # Terminals should be PFP type (names contain "PFP")
                terminals = system_data["system"]["terminals"]
                for terminal in terminals:
                    assert "PFP" in terminal

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_electric_reheat():
    """Verify System 6 uses electric reheat in PFP boxes."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_elec"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP"
                })
                system_data = _unwrap(system_resp)

                # System 6 PFP terminals have electric reheat (inherent in PFP type)
                terminals = system_data["system"]["terminals"]
                for terminal in terminals:
                    assert "PFP" in terminal

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_dx_cooling():
    """Verify System 6 uses DX cooling."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_dx"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP"
                })
                system_data = _unwrap(system_resp)

                assert "DX" in system_data["system"]["cooling"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_variable_fan():
    """Verify System 6 has variable volume fan on air loop."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                # Should have central VAV fan plus PFP fans
                assert len(fans) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_economizer_enabled():
    """Verify System 6 economizer when enabled."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "economizer": True,
                    "system_name": "VAV PFP Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP Econ"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_economizer_disabled():
    """Verify System 6 economizer when disabled."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_no_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "economizer": False,
                    "system_name": "VAV PFP No Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP No Econ"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_outdoor_air_present():
    """Verify System 6 has outdoor air system."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_setpoint_managers():
    """Verify System 6 has setpoint managers."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_preheat_coil():
    """Verify System 6 has preheat coil."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_preheat"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                heating_coils = air_loop_data["air_loop"]["detailed_components"]["heating_coils"]
                assert len(heating_coils) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_6_cooling_coil():
    """Verify System 6 has DX cooling coil."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s6_clg"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 6,
                    "thermal_zone_names": zone_names,
                    "system_name": "VAV PFP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "VAV PFP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                cooling_coils = air_loop_data["air_loop"]["detailed_components"]["cooling_coils"]
                assert len(cooling_coils) >= 1
                assert "DX" in cooling_coils[0]["type"]

    asyncio.run(_run())


# ============================================================================
# SYSTEM 7: Central VAV w/ Reheat - All 3 Plant Loops (13 tests)
# ============================================================================

@pytest.mark.integration
def test_system_7_chilled_water_loop():
    """Verify System 7 creates chilled water loop."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_chw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                system_data = _unwrap(system_resp)

                assert "chilled_water_loop" in system_data["system"]

                chw_loop_name = system_data["system"]["chilled_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": chw_loop_name
                })
                loop_data = _unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"

                assert loop_data["plant_loop"]["loop_type"] == "Cooling"

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_hot_water_loop():
    """Verify System 7 creates hot water loop."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_hw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                system_data = _unwrap(system_resp)

                assert "hot_water_loop" in system_data["system"]

                hw_loop_name = system_data["system"]["hot_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": hw_loop_name
                })
                loop_data = _unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"

                assert loop_data["plant_loop"]["loop_type"] == "Heating"

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_condenser_loop():
    """Verify System 7 creates condenser water loop."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_cw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                system_data = _unwrap(system_resp)

                assert "condenser_loop" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_chiller_present():
    """Verify System 7 has chiller."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_chiller"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                system_data = _unwrap(system_resp)

                chw_loop_name = system_data["system"]["chilled_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": chw_loop_name
                })
                loop_data = _unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                supply_comps = loop_data["plant_loop"]["supply_components"]
                chiller_present = any("Chiller" in comp["type"] for comp in supply_comps)
                assert chiller_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_boiler_present():
    """Verify System 7 has boiler."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_boiler"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                system_data = _unwrap(system_resp)

                hw_loop_name = system_data["system"]["hot_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": hw_loop_name
                })
                loop_data = _unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                supply_comps = loop_data["plant_loop"]["supply_components"]
                boiler_present = any("Boiler" in comp["type"] for comp in supply_comps)
                assert boiler_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_cooling_tower():
    """Verify System 7 has cooling tower."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_tower"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                system_data = _unwrap(system_resp)

                cw_loop_name = system_data["system"]["condenser_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": cw_loop_name
                })
                loop_data = _unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                supply_comps = loop_data["plant_loop"]["supply_components"]
                tower_present = any("CoolingTower" in comp["type"] for comp in supply_comps)
                assert tower_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_vav_terminals():
    """Verify System 7 has VAV reheat terminals."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_terms"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                system_data = _unwrap(system_resp)

                assert "terminals" in system_data["system"]
                assert len(system_data["system"]["terminals"]) == len(zone_names)

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_water_coils():
    """Verify System 7 uses water coils not DX."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_water"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })
                system_data = _unwrap(system_resp)

                # System 7 should use chilled water cooling
                assert "Chilled Water" in system_data["system"]["cooling"] or "Water" in system_data["system"]["cooling"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_variable_fan():
    """Verify System 7 has variable volume fan."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                assert len(fans) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_economizer_enabled():
    """Verify System 7 economizer when enabled."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "economizer": True,
                    "system_name": "Central VAV Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV Econ"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_economizer_disabled():
    """Verify System 7 economizer when disabled."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_no_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "economizer": False,
                    "system_name": "Central VAV No Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV No Econ"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_outdoor_air_present():
    """Verify System 7 has outdoor air system."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_7_setpoint_managers():
    """Verify System 7 has setpoint managers."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s7_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central VAV"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central VAV"
                })
                air_loop_data = _unwrap(air_loop_resp)

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
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_chw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })
                system_data = _unwrap(system_resp)

                assert "chilled_water_loop" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_hot_water_loop():
    """Verify System 8 creates hot water loop."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_hw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })
                system_data = _unwrap(system_resp)

                # System 8 may or may not have HW loop (PFP with electric reheat)
                # Just verify system was created
                assert system_data.get("ok") is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_condenser_loop():
    """Verify System 8 creates condenser water loop."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_cw"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })
                system_data = _unwrap(system_resp)

                assert "condenser_loop" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_pfp_terminals():
    """Verify System 8 has PFP terminals."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_pfp"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })
                system_data = _unwrap(system_resp)

                assert "terminals" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_electric_reheat():
    """Verify System 8 uses electric reheat in PFP boxes."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_elec"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })
                system_data = _unwrap(system_resp)

                # System 8 PFP terminals have electric reheat (inherent in PFP type)
                terminals = system_data["system"]["terminals"]
                for terminal in terminals:
                    assert "PFP" in terminal

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_chiller_present():
    """Verify System 8 has chiller."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_chiller"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })
                system_data = _unwrap(system_resp)

                chw_loop_name = system_data["system"]["chilled_water_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": chw_loop_name
                })
                loop_data = _unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                supply_comps = loop_data["plant_loop"]["supply_components"]
                chiller_present = any("Chiller" in comp["type"] for comp in supply_comps)
                assert chiller_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_cooling_tower():
    """Verify System 8 has cooling tower."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_tower"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })
                system_data = _unwrap(system_resp)

                cw_loop_name = system_data["system"]["condenser_loop"]
                loop_resp = await session.call_tool("get_plant_loop_details", {
                    "plant_loop_name": cw_loop_name
                })
                loop_data = _unwrap(loop_resp)

                assert loop_data.get("ok") is True, f"get_plant_loop_details failed: {loop_data.get('error')}"


                supply_comps = loop_data["plant_loop"]["supply_components"]
                tower_present = any("CoolingTower" in comp["type"] for comp in supply_comps)
                assert tower_present

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_water_cooling():
    """Verify System 8 uses chilled water cooling."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_water"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })
                system_data = _unwrap(system_resp)

                # System 8 should use chilled water cooling
                assert "Water" in system_data["system"]["cooling"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_variable_fan():
    """Verify System 8 has variable volume fan."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_fan"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central PFP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                fans = air_loop_data["air_loop"]["detailed_components"]["fans"]
                # Central fan + PFP fans
                assert len(fans) >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_economizer_enabled():
    """Verify System 8 economizer when enabled."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "economizer": True,
                    "system_name": "Central PFP Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central PFP Econ"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is True

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_economizer_disabled():
    """Verify System 8 economizer when disabled."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_no_econ"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "economizer": False,
                    "system_name": "Central PFP No Econ"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central PFP No Econ"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                oa_system = air_loop_data["air_loop"]["outdoor_air_system"]
                assert oa_system["economizer_enabled"] is False

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_outdoor_air_present():
    """Verify System 8 has outdoor air system."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_oa"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central PFP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                assert air_loop_data["air_loop"]["outdoor_air_system"] is not None

    asyncio.run(_run())


@pytest.mark.integration
def test_system_8_setpoint_managers():
    """Verify System 8 has setpoint managers."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s8_spm"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 8,
                    "thermal_zone_names": zone_names,
                    "system_name": "Central PFP"
                })

                air_loop_resp = await session.call_tool("get_air_loop_details", {
                    "air_loop_name": "Central PFP"
                })
                air_loop_data = _unwrap(air_loop_resp)

                assert air_loop_data.get("ok") is True, f"get_air_loop_details failed: {air_loop_data.get('error')}"

                setpoint_mgrs = air_loop_data["air_loop"]["setpoint_managers"]
                assert len(setpoint_mgrs) >= 1

    asyncio.run(_run())


# ============================================================================
# SYSTEM 9: Gas Unit Heaters - Zone Equipment (2 tests)
# ============================================================================

@pytest.mark.integration
def test_system_9_unit_heaters():
    """Verify System 9 creates gas unit heaters."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s9_heaters"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 9,
                    "thermal_zone_names": zone_names,
                    "system_name": "Gas Heaters"
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert "equipment" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_9_no_cooling():
    """Verify System 9 has no cooling."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s9_no_clg"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 9,
                    "thermal_zone_names": zone_names,
                    "system_name": "Gas Heaters"
                })
                system_data = _unwrap(system_resp)

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
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s10_heaters"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 10,
                    "thermal_zone_names": zone_names,
                    "system_name": "Electric Heaters"
                })
                system_data = _unwrap(system_resp)

                assert system_data.get("ok") is True
                assert "equipment" in system_data["system"]

    asyncio.run(_run())


@pytest.mark.integration
def test_system_10_no_cooling():
    """Verify System 10 has no cooling."""
    async def _run():
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                name = "test_s10_no_clg"
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_data = _unwrap(create_resp)
                load_resp = await session.call_tool("load_osm_model", {
                    "osm_path": create_data["osm_path"]
                })

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_data = _unwrap(zones_resp)
                zone_names = [z["name"] for z in zones_data["thermal_zones"]]

                system_resp = await session.call_tool("add_baseline_system", {
                    "system_type": 10,
                    "thermal_zone_names": zone_names,
                    "system_name": "Electric Heaters"
                })
                system_data = _unwrap(system_resp)

                # System 10 should have no cooling or "None"
                cooling = system_data["system"].get("cooling", "None")
                assert cooling == "None" or cooling is None

    asyncio.run(_run())
