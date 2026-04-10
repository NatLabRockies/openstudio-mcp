"""Integration tests for component_properties skill (Phase 5A).

list_hvac_components removed in Phase C — tests use list_model_objects instead.
"""
import asyncio
import json

import pytest
from conftest import create_and_load, create_baseline_and_load, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


async def _find_components(session, component_type, max_results=0):
    """Find components by type using list_model_objects."""
    res = unwrap(await session.call_tool("list_model_objects",
                 {"object_type": component_type, "max_results": max_results}))
    assert res["ok"] is True, res
    return res["objects"]


# --- Example model tests (System 1 PTAC) ---

def test_get_heating_coil_properties():
    """Get PTAC heating coil properties."""
    # Validates: get_component_properties returns efficiency for CoilHeatingElectric on System 1 PTAC
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "cp_htg")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "CoilHeatingElectric")
                assert len(comps) > 0, "System 1 PTAC should create at least one CoilHeatingElectric"

                result = await session.call_tool("get_component_properties", {
                    "component_name": comps[0]["name"],
                })
                data = unwrap(result)
                assert data["ok"] is True, f"get_component_properties failed: {data.get('error')}"
                assert data["properties"]["efficiency"]["value"] == pytest.approx(1.0, abs=0.01), \
                    "Electric heating coil default efficiency should be 1.0"
    asyncio.run(_run())


def test_get_cooling_coil_properties():
    """Get PTAC DX cooling coil, verify rated_cop exists."""
    # Validates: get_component_properties returns rated_cop for CoilCoolingDXSingleSpeed on System 1
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "cp_clg")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "CoilCoolingDXSingleSpeed")
                assert len(comps) > 0, "System 1 PTAC should create at least one DX cooling coil"

                result = await session.call_tool("get_component_properties", {
                    "component_name": comps[0]["name"],
                })
                data = unwrap(result)
                assert data["ok"] is True, f"get_component_properties failed: {data.get('error')}"
                assert data["properties"]["rated_cop"]["value"] > 0, "DX coil COP must be positive"
    asyncio.run(_run())


def test_get_fan_properties():
    """Get FanConstantVolume properties."""
    # Validates: get_component_properties returns pressure_rise_pa for FanConstantVolume on System 1
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "cp_fan")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "FanConstantVolume")
                assert len(comps) > 0, "System 1 PTAC should create at least one FanConstantVolume"

                result = await session.call_tool("get_component_properties", {
                    "component_name": comps[0]["name"],
                })
                data = unwrap(result)
                assert data["ok"] is True, f"get_component_properties failed: {data.get('error')}"
                assert data["properties"]["pressure_rise_pa"]["value"] > 0, \
                    "Fan pressure rise must be positive"
    asyncio.run(_run())


def test_set_fan_pressure_rise():
    """Set fan pressure_rise_pa to 400, verify round-trip."""
    # Validates: set_component_properties round-trips pressure_rise_pa on FanConstantVolume
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "cp_setfan")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "FanConstantVolume")
                fan = comps[0]

                result = await session.call_tool("set_component_properties", {
                    "component_name": fan["name"],
                    "properties": json.dumps({"pressure_rise_pa": 400.0}),
                })
                data = unwrap(result)
                assert data["ok"] is True, f"set_component_properties failed: {data.get('error')}"
                assert data["changes"]["pressure_rise_pa"]["new"] == pytest.approx(400.0, abs=0.01)

                # Independent query verification
                vr = await session.call_tool("get_component_properties", {
                    "component_name": fan["name"],
                })
                vd = unwrap(vr)
                assert vd["ok"] is True, f"get_component_properties failed: {vd.get('error')}"
                assert vd["properties"]["pressure_rise_pa"]["value"] == pytest.approx(400.0, abs=0.01)
    asyncio.run(_run())


def test_set_invalid_property():
    """Unknown property name returns error."""
    # Validates: set_component_properties rejects unknown property names with errors list
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_and_load(session, "cp_inv")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "FanConstantVolume")
                fan = comps[0]

                result = await session.call_tool("set_component_properties", {
                    "component_name": fan["name"],
                    "properties": json.dumps({"nonexistent_prop": 42}),
                })
                data = unwrap(result)
                assert data["ok"] is False
                assert len(data["errors"]) > 0, "Should report at least one error for unknown property"
    asyncio.run(_run())


def test_get_nonexistent_component():
    """Bad component name returns error."""
    # Validates: get_component_properties returns ok=False with error for nonexistent component
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await create_and_load(session, "cp_nocomp")

                result = await session.call_tool("get_component_properties", {
                    "component_name": "Nonexistent Widget",
                })
                data = unwrap(result)
                assert data["ok"] is False
                assert "error" in data, "Should include error message for missing component"
    asyncio.run(_run())


# --- Baseline model tests (System 7) ---

def test_get_chiller_properties():
    """Get ChillerElectricEIR reference_cop."""
    # Validates: get_component_properties returns positive reference_cop for System 7 chiller
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "cp_chill")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "ChillerElectricEIR")
                chiller = comps[0]

                result = await session.call_tool("get_component_properties", {
                    "component_name": chiller["name"],
                })
                data = unwrap(result)
                assert data["ok"] is True, f"get_component_properties failed: {data.get('error')}"
                assert data["properties"]["reference_cop"]["value"] > 0, \
                    "Chiller COP must be positive"
    asyncio.run(_run())


def test_set_chiller_cop():
    """Set chiller reference_cop to 6.0, verify round-trip."""
    # Validates: set_component_properties round-trips reference_cop on ChillerElectricEIR
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "cp_setcop")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "ChillerElectricEIR")
                chiller = comps[0]

                result = await session.call_tool("set_component_properties", {
                    "component_name": chiller["name"],
                    "properties": json.dumps({"reference_cop": 6.0}),
                })
                data = unwrap(result)
                assert data["ok"] is True, f"set_component_properties failed: {data.get('error')}"
                assert data["changes"]["reference_cop"]["new"] == pytest.approx(6.0, abs=0.01)

                # Independent query verification
                vr = await session.call_tool("get_component_properties", {
                    "component_name": chiller["name"],
                })
                vd = unwrap(vr)
                assert vd["ok"] is True, f"get_component_properties failed: {vd.get('error')}"
                assert vd["properties"]["reference_cop"]["value"] == pytest.approx(6.0, abs=0.01)
    asyncio.run(_run())


def test_get_boiler_properties():
    """Get BoilerHotWater efficiency."""
    # Validates: get_component_properties returns nominal_thermal_efficiency for System 7 boiler
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "cp_boiler")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "BoilerHotWater")
                boiler = comps[0]

                result = await session.call_tool("get_component_properties", {
                    "component_name": boiler["name"],
                })
                data = unwrap(result)
                assert data["ok"] is True, f"get_component_properties failed: {data.get('error')}"
                assert data["properties"]["nominal_thermal_efficiency"]["value"] > 0, \
                    "Boiler efficiency must be positive"
    asyncio.run(_run())


def test_set_boiler_efficiency():
    """Set boiler nominal_thermal_efficiency to 0.95."""
    # Validates: set_component_properties round-trips nominal_thermal_efficiency on BoilerHotWater
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "cp_setblr")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "BoilerHotWater")
                boiler = comps[0]

                result = await session.call_tool("set_component_properties", {
                    "component_name": boiler["name"],
                    "properties": json.dumps({"nominal_thermal_efficiency": 0.95}),
                })
                data = unwrap(result)
                assert data["ok"] is True, f"set_component_properties failed: {data.get('error')}"
                assert data["changes"]["nominal_thermal_efficiency"]["new"] == pytest.approx(0.95, abs=0.01)

                # Independent query verification
                vr = await session.call_tool("get_component_properties", {
                    "component_name": boiler["name"],
                })
                vd = unwrap(vr)
                assert vd["ok"] is True, f"get_component_properties failed: {vd.get('error')}"
                assert vd["properties"]["nominal_thermal_efficiency"]["value"] == pytest.approx(0.95, abs=0.01)
    asyncio.run(_run())


def test_get_pump_properties():
    """Get PumpVariableSpeed rated_pump_head."""
    # Validates: get_component_properties returns rated_pump_head_pa for System 7 variable speed pump
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "cp_pump")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "PumpVariableSpeed")
                assert len(comps) > 0, "System 7 should create variable speed pumps for plant loops"

                result = await session.call_tool("get_component_properties", {
                    "component_name": comps[0]["name"],
                })
                data = unwrap(result)
                assert data["ok"] is True, f"get_component_properties failed: {data.get('error')}"
                assert data["properties"]["rated_pump_head_pa"]["value"] > 0, \
                    "Pump head must be positive"
    asyncio.run(_run())


def test_set_pump_head():
    """Set pump rated_pump_head to 200000."""
    # Validates: set_component_properties round-trips rated_pump_head_pa on PumpVariableSpeed
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await create_baseline_and_load(session, "cp_setpmp")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                comps = await _find_components(session, "PumpVariableSpeed")
                pump = comps[0]

                result = await session.call_tool("set_component_properties", {
                    "component_name": pump["name"],
                    "properties": json.dumps({"rated_pump_head_pa": 200000}),
                })
                data = unwrap(result)
                assert data["ok"] is True, f"set_component_properties failed: {data.get('error')}"
                assert data["changes"]["rated_pump_head_pa"]["new"] == pytest.approx(200000, abs=1)

                # Independent query verification
                vr = await session.call_tool("get_component_properties", {
                    "component_name": pump["name"],
                })
                vd = unwrap(vr)
                assert vd["ok"] is True, f"get_component_properties failed: {vd.get('error')}"
                assert vd["properties"]["rated_pump_head_pa"]["value"] == pytest.approx(200000, abs=1)
    asyncio.run(_run())
