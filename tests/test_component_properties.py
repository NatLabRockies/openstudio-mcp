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
                assert len(comps) > 0, "No heating coils found"

                result = await session.call_tool("get_component_properties", {
                    "component_name": comps[0]["name"],
                })
                data = unwrap(result)
                assert data["ok"] is True
                assert "efficiency" in data["properties"]
    asyncio.run(_run())


def test_get_cooling_coil_properties():
    """Get PTAC DX cooling coil, verify rated_cop exists."""
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
                assert len(comps) > 0

                result = await session.call_tool("get_component_properties", {
                    "component_name": comps[0]["name"],
                })
                data = unwrap(result)
                assert data["ok"] is True
                assert "rated_cop" in data["properties"]
    asyncio.run(_run())


def test_get_fan_properties():
    """Get FanConstantVolume properties."""
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
                assert len(comps) > 0

                result = await session.call_tool("get_component_properties", {
                    "component_name": comps[0]["name"],
                })
                data = unwrap(result)
                assert data["ok"] is True
                assert "pressure_rise_pa" in data["properties"]
    asyncio.run(_run())


def test_set_fan_pressure_rise():
    """Set fan pressure_rise_pa to 400, verify round-trip."""
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
                assert data["ok"] is True
                assert abs(data["changes"]["pressure_rise_pa"]["new"] - 400.0) < 0.01

                # Independent query verification
                vr = await session.call_tool("get_component_properties", {
                    "component_name": fan["name"],
                })
                vd = unwrap(vr)
                assert vd["ok"] is True
                assert abs(vd["properties"]["pressure_rise_pa"]["value"] - 400.0) < 0.01
    asyncio.run(_run())


def test_set_invalid_property():
    """Unknown property name returns error."""
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
                assert "errors" in data
    asyncio.run(_run())


def test_get_nonexistent_component():
    """Bad component name returns error."""
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
    asyncio.run(_run())


# --- Baseline model tests (System 7) ---

def test_get_chiller_properties():
    """Get ChillerElectricEIR reference_cop."""
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
                assert data["ok"] is True
                assert "reference_cop" in data["properties"]
                assert data["properties"]["reference_cop"]["value"] > 0
    asyncio.run(_run())


def test_set_chiller_cop():
    """Set chiller reference_cop to 6.0, verify round-trip."""
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
                assert data["ok"] is True
                assert abs(data["changes"]["reference_cop"]["new"] - 6.0) < 0.01

                # Independent query verification
                vr = await session.call_tool("get_component_properties", {
                    "component_name": chiller["name"],
                })
                vd = unwrap(vr)
                assert vd["ok"] is True
                assert abs(vd["properties"]["reference_cop"]["value"] - 6.0) < 0.01
    asyncio.run(_run())


def test_get_boiler_properties():
    """Get BoilerHotWater efficiency."""
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
                assert data["ok"] is True
                assert "nominal_thermal_efficiency" in data["properties"]
    asyncio.run(_run())


def test_set_boiler_efficiency():
    """Set boiler nominal_thermal_efficiency to 0.95."""
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
                assert data["ok"] is True
                assert abs(data["changes"]["nominal_thermal_efficiency"]["new"] - 0.95) < 0.01

                # Independent query verification
                vr = await session.call_tool("get_component_properties", {
                    "component_name": boiler["name"],
                })
                vd = unwrap(vr)
                assert vd["ok"] is True
                assert abs(vd["properties"]["nominal_thermal_efficiency"]["value"] - 0.95) < 0.01
    asyncio.run(_run())


def test_get_pump_properties():
    """Get PumpVariableSpeed rated_pump_head."""
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
                assert len(comps) > 0, "No pumps found"

                result = await session.call_tool("get_component_properties", {
                    "component_name": comps[0]["name"],
                })
                data = unwrap(result)
                assert data["ok"] is True
                assert "rated_pump_head_pa" in data["properties"]
    asyncio.run(_run())


def test_set_pump_head():
    """Set pump rated_pump_head to 200000."""
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
                assert data["ok"] is True
                assert abs(data["changes"]["rated_pump_head_pa"]["new"] - 200000) < 1

                # Independent query verification
                vr = await session.call_tool("get_component_properties", {
                    "component_name": pump["name"],
                })
                vd = unwrap(vr)
                assert vd["ok"] is True
                assert abs(vd["properties"]["rated_pump_head_pa"]["value"] - 200000) < 1
    asyncio.run(_run())
