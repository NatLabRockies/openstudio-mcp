"""Integration tests for component_properties skill (Phase 5A)."""
import asyncio
import json
import pytest

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from conftest import unwrap, integration_enabled, server_params

pytestmark = pytest.mark.skipif(not integration_enabled(), reason="integration disabled")


async def _create_and_load(session, name):
    """Create example model, load it, return zone names."""
    cr = await session.call_tool("create_example_osm", {"name": name})
    cd = unwrap(cr)
    assert cd.get("ok") is True, cd
    lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
    assert unwrap(lr).get("ok") is True
    zr = await session.call_tool("list_thermal_zones", {})
    zd = unwrap(zr)
    return [z["name"] for z in zd["thermal_zones"]]


async def _create_baseline_and_load(session, name):
    """Create baseline 10-zone model, load it, return zone names."""
    cr = await session.call_tool("create_baseline_osm", {"name": name})
    cd = unwrap(cr)
    assert cd.get("ok") is True, cd
    lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
    assert unwrap(lr).get("ok") is True
    zr = await session.call_tool("list_thermal_zones", {})
    zd = unwrap(zr)
    return [z["name"] for z in zd["thermal_zones"]]


# --- Example model tests (System 1 PTAC) ---

def test_list_components():
    """List all components, verify count > 0."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await _create_and_load(session, "cp_list")
                # Add System 1 PTAC
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                result = await session.call_tool("list_hvac_components", {})
                data = unwrap(result)
                assert data["ok"] is True
                assert data["count"] > 0
                assert len(data["components"]) > 0
    asyncio.run(_run())


def test_list_components_by_category():
    """Filter components by category 'coil'."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await _create_and_load(session, "cp_cat")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                result = await session.call_tool("list_hvac_components", {"category": "coil"})
                data = unwrap(result)
                assert data["ok"] is True
                for c in data["components"]:
                    assert c["category"] == "coil"
    asyncio.run(_run())


def test_get_heating_coil_properties():
    """Get PTAC heating coil properties."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await _create_and_load(session, "cp_htg")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                # Find heating coil name
                lr = await session.call_tool("list_hvac_components", {"category": "coil"})
                comps = unwrap(lr)["components"]
                htg = next((c for c in comps if "Heating" in c["name"] and c["type"] == "CoilHeatingElectric"), None)
                assert htg is not None, f"No heating coil found in {comps}"

                result = await session.call_tool("get_component_properties", {
                    "component_name": htg["name"],
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
                zones = await _create_and_load(session, "cp_clg")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                lr = await session.call_tool("list_hvac_components", {"category": "coil"})
                comps = unwrap(lr)["components"]
                clg = next((c for c in comps if "Cooling" in c["name"] and "DXSingleSpeed" in c["type"]), None)
                assert clg is not None

                result = await session.call_tool("get_component_properties", {
                    "component_name": clg["name"],
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
                zones = await _create_and_load(session, "cp_fan")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                lr = await session.call_tool("list_hvac_components", {"category": "fan"})
                comps = unwrap(lr)["components"]
                fan = next((c for c in comps if "Fan" in c["name"]), None)
                assert fan is not None

                result = await session.call_tool("get_component_properties", {
                    "component_name": fan["name"],
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
                zones = await _create_and_load(session, "cp_setfan")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                lr = await session.call_tool("list_hvac_components", {"category": "fan"})
                fan = next(c for c in unwrap(lr)["components"] if "Fan" in c["name"])

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
                zones = await _create_and_load(session, "cp_inv")
                await session.call_tool("add_baseline_system", {
                    "system_type": 1,
                    "thermal_zone_names": zones,
                })
                lr = await session.call_tool("list_hvac_components", {"category": "fan"})
                fan = next(c for c in unwrap(lr)["components"] if "Fan" in c["name"])

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
                await _create_and_load(session, "cp_nocomp")

                result = await session.call_tool("get_component_properties", {
                    "component_name": "Nonexistent Widget",
                })
                data = unwrap(result)
                assert data["ok"] is False
    asyncio.run(_run())


# --- Baseline model tests (System 7) ---

def test_list_components_system7():
    """System 7 has chiller, boiler, tower, pumps."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await _create_baseline_and_load(session, "cp_sys7")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                result = await session.call_tool("list_hvac_components", {})
                data = unwrap(result)
                assert data["ok"] is True
                types = {c["type"] for c in data["components"]}
                assert "ChillerElectricEIR" in types
                assert "BoilerHotWater" in types
                assert "CoolingTowerSingleSpeed" in types
    asyncio.run(_run())


def test_get_chiller_properties():
    """Get ChillerElectricEIR reference_cop."""
    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                zones = await _create_baseline_and_load(session, "cp_chill")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                lr = await session.call_tool("list_hvac_components", {"category": "plant"})
                chiller = next(c for c in unwrap(lr)["components"] if c["type"] == "ChillerElectricEIR")

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
                zones = await _create_baseline_and_load(session, "cp_setcop")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                lr = await session.call_tool("list_hvac_components", {"category": "plant"})
                chiller = next(c for c in unwrap(lr)["components"] if c["type"] == "ChillerElectricEIR")

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
                zones = await _create_baseline_and_load(session, "cp_boiler")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                lr = await session.call_tool("list_hvac_components", {"category": "plant"})
                boiler = next(c for c in unwrap(lr)["components"] if c["type"] == "BoilerHotWater")

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
                zones = await _create_baseline_and_load(session, "cp_setblr")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                lr = await session.call_tool("list_hvac_components", {"category": "plant"})
                boiler = next(c for c in unwrap(lr)["components"] if c["type"] == "BoilerHotWater")

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
                zones = await _create_baseline_and_load(session, "cp_pump")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                lr = await session.call_tool("list_hvac_components", {"category": "pump"})
                comps = unwrap(lr)["components"]
                pump = next((c for c in comps if "Pump" in c["type"]), None)
                assert pump is not None, f"No pump found: {comps}"

                result = await session.call_tool("get_component_properties", {
                    "component_name": pump["name"],
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
                zones = await _create_baseline_and_load(session, "cp_setpmp")
                await session.call_tool("add_baseline_system", {
                    "system_type": 7,
                    "thermal_zone_names": zones,
                })
                lr = await session.call_tool("list_hvac_components", {"category": "pump"})
                comps = unwrap(lr)["components"]
                pump = next(c for c in comps if "Pump" in c["type"])

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
