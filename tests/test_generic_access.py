"""Integration tests for generic model object access (W1-W3) and equivalence (Phase B).

Tests:
  W1: list_model_objects with dynamic fallback + type name normalization
  W2: get_object_fields — generic property read
  W3: set_object_property — generic property write
  W4: demand terminals in get_air_loop_details
  Phase B: equivalence between old explicit tools and new generic tools
"""
import asyncio
import uuid

import pytest
from conftest import (
    integration_enabled,
    server_params,
    setup_example,
    unwrap,
)
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_generic") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


async def _create_baseline_with_hvac(s, name, sys_num="07"):
    """Create baseline model with HVAC system (default: System 7 = VAV w/ boiler+chiller)."""
    cr = unwrap(await s.call_tool("create_baseline_osm",
                {"name": name, "ashrae_sys_num": sys_num}))
    assert cr.get("ok") is True, cr
    lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr.get("ok") is True


# ---------------------------------------------------------------------------
# W1: list_model_objects dynamic fallback + type normalization
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_list_model_objects_dynamic_fallback():
    """list_model_objects accepts types not in MANAGED_TYPES via dynamic getter."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())

                # SizingSystem is not in MANAGED_TYPES but model.getSizingSystems() exists
                res = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "SizingSystem", "max_results": 0}))
                print("dynamic fallback SizingSystem:", res)
                assert res["ok"] is True, res
                assert res["type"] == "SizingSystem"

    asyncio.run(_run())


@pytest.mark.integration
def test_list_model_objects_idd_colon_format():
    """list_model_objects accepts IDD colon format (OS:Coil:Cooling:Water)."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _create_baseline_with_hvac(s, _unique("pytest_idd"))

                # Use IDD colon format
                res = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "OS:Coil:Cooling:Water", "max_results": 0}))
                print("IDD colon:", res)
                assert res["ok"] is True, res
                assert res["type"] == "CoilCoolingWater"

    asyncio.run(_run())


@pytest.mark.integration
def test_list_model_objects_idd_underscore_format():
    """list_model_objects accepts IDD underscore format."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _create_baseline_with_hvac(s, _unique("pytest_idd_us"))

                res = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "OS_Coil_Cooling_Water", "max_results": 0}))
                print("IDD underscore:", res)
                assert res["ok"] is True, res
                assert res["type"] == "CoilCoolingWater"

    asyncio.run(_run())


@pytest.mark.integration
def test_list_model_objects_unknown_type_error():
    """list_model_objects returns helpful error for truly unknown types."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())

                res = unwrap(await s.call_tool("list_model_objects",
                             {"object_type": "TotallyFakeWidget"}))
                print("unknown type:", res)
                assert res["ok"] is False
                assert "TotallyFakeWidget" in res["error"]

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# W2: get_object_fields
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_object_fields_boiler():
    """get_object_fields reads properties from a BoilerHotWater."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _create_baseline_with_hvac(s, _unique("pytest_fields"))

                # Find a boiler
                boilers = unwrap(await s.call_tool("list_model_objects",
                                 {"object_type": "BoilerHotWater", "max_results": 1}))
                assert boilers["ok"] is True and boilers["count"] >= 1, boilers
                boiler_name = boilers["objects"][0]["name"]

                # Get fields
                res = unwrap(await s.call_tool("get_object_fields",
                             {"object_type": "BoilerHotWater",
                              "object_name": boiler_name}))
                print("get_object_fields boiler:", list(res.get("properties", {}).keys())[:10])
                assert res["ok"] is True, res
                assert "properties" in res
                assert "setters" in res
                assert len(res["properties"]) > 0
                assert len(res["setters"]) > 0
                # Should find efficiency-related property
                prop_names = list(res["properties"].keys())
                assert any("fficiency" in p for p in prop_names), \
                    f"No efficiency property found in {prop_names}"

    asyncio.run(_run())


@pytest.mark.integration
def test_get_object_fields_by_handle():
    """get_object_fields works with handle lookup."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())

                # Get a space handle
                spaces = unwrap(await s.call_tool("list_model_objects",
                                {"object_type": "Space", "max_results": 1}))
                assert spaces["ok"] is True and spaces["count"] >= 1
                handle = spaces["objects"][0]["handle"]

                res = unwrap(await s.call_tool("get_object_fields",
                             {"object_type": "Space", "object_handle": handle}))
                print("get_object_fields by handle:", res.get("name"))
                assert res["ok"] is True, res
                assert res["handle"] == handle

    asyncio.run(_run())


@pytest.mark.integration
def test_get_object_fields_not_found():
    """get_object_fields returns error for non-existent object."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())

                res = unwrap(await s.call_tool("get_object_fields",
                             {"object_type": "BoilerHotWater",
                              "object_name": "NonExistent"}))
                assert res["ok"] is False
                assert "not found" in res["error"]

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# W3: set_object_property
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_set_object_property_boiler_efficiency():
    """set_object_property changes a boiler's nominal thermal efficiency."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _create_baseline_with_hvac(s, _unique("pytest_set"))

                boilers = unwrap(await s.call_tool("list_model_objects",
                                 {"object_type": "BoilerHotWater", "max_results": 1}))
                assert boilers["ok"] and boilers["count"] >= 1
                boiler_name = boilers["objects"][0]["name"]

                # Set efficiency to 0.92
                res = unwrap(await s.call_tool("set_object_property", {
                    "object_type": "BoilerHotWater",
                    "property_name": "nominalThermalEfficiency",
                    "value": 0.92,
                    "object_name": boiler_name,
                }))
                print("set_object_property:", res)
                assert res["ok"] is True, res
                assert res["setter_method"] == "setNominalThermalEfficiency"
                assert res["new_value"] == 0.92

    asyncio.run(_run())


@pytest.mark.integration
def test_set_object_property_with_set_prefix():
    """set_object_property accepts setter name with 'set' prefix."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _create_baseline_with_hvac(s, _unique("pytest_setpfx"))

                boilers = unwrap(await s.call_tool("list_model_objects",
                                 {"object_type": "BoilerHotWater", "max_results": 1}))
                assert boilers["ok"] and boilers["count"] >= 1
                boiler_name = boilers["objects"][0]["name"]

                res = unwrap(await s.call_tool("set_object_property", {
                    "object_type": "BoilerHotWater",
                    "property_name": "setNominalThermalEfficiency",
                    "value": 0.85,
                    "object_name": boiler_name,
                }))
                assert res["ok"] is True, res
                assert res["new_value"] == 0.85

    asyncio.run(_run())


@pytest.mark.integration
def test_set_object_property_invalid_setter():
    """set_object_property returns error for non-existent setter."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _create_baseline_with_hvac(s, _unique("pytest_badsetter"))

                boilers = unwrap(await s.call_tool("list_model_objects",
                                 {"object_type": "BoilerHotWater", "max_results": 1}))
                assert boilers["ok"] and boilers["count"] >= 1
                boiler_name = boilers["objects"][0]["name"]

                res = unwrap(await s.call_tool("set_object_property", {
                    "object_type": "BoilerHotWater",
                    "property_name": "totallyFakeProperty",
                    "value": 99,
                    "object_name": boiler_name,
                }))
                assert res["ok"] is False
                assert "No setter" in res["error"]

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# W4: demand terminals in get_air_loop_details
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_air_loop_demand_terminals():
    """get_air_loop_details includes demand_terminals with zone/type/name."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _create_baseline_with_hvac(s, _unique("pytest_terminals"))

                loops = unwrap(await s.call_tool("list_air_loops", {}))
                assert loops["ok"] and loops["count"] >= 1
                loop_name = loops["air_loops"][0]["name"]

                details = unwrap(await s.call_tool("get_air_loop_details",
                                 {"air_loop_name": loop_name}))
                assert details["ok"] is True, details
                al = details["air_loop"]
                assert "demand_terminals" in al, f"Missing demand_terminals: {al.keys()}"
                assert len(al["demand_terminals"]) > 0
                term = al["demand_terminals"][0]
                assert "zone" in term
                assert "terminal_type" in term
                assert "terminal_name" in term
                print(f"demand_terminals ({len(al['demand_terminals'])}): {term}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Phase C: Definition traversal via get_object_fields
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_object_fields_people_definition():
    """get_object_fields for People returns inline definition fields."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _create_baseline_with_hvac(s, _unique("pytest_defn_ppl"))

                # Find a People object
                people = unwrap(await s.call_tool("list_model_objects",
                                {"object_type": "People", "max_results": 1}))
                assert people["ok"] and people["count"] >= 1
                ppl_name = people["objects"][0]["name"]

                # get_object_fields should follow the peopleDefinition link
                res = unwrap(await s.call_tool("get_object_fields",
                             {"object_type": "People", "object_name": ppl_name}))
                assert res["ok"] is True, res
                props = res["properties"]
                # Should have a definition field with nested scalar values
                defn_keys = [k for k, v in props.items()
                             if v.get("type", "").startswith("definition(")]
                assert len(defn_keys) >= 1, (
                    f"No definition fields found in People properties: "
                    f"{list(props.keys())}"
                )
                # The definition should contain numeric fields
                defn_val = props[defn_keys[0]]["value"]
                assert isinstance(defn_val, dict), f"Definition value is not dict: {defn_val}"
                print(f"People definition fields: {list(defn_val.keys())}")

    asyncio.run(_run())


@pytest.mark.integration
def test_get_object_fields_lights_definition():
    """get_object_fields for Lights returns inline definition fields."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _create_baseline_with_hvac(s, _unique("pytest_defn_lts"))

                lights = unwrap(await s.call_tool("list_model_objects",
                                {"object_type": "Lights", "max_results": 1}))
                assert lights["ok"] and lights["count"] >= 1
                lts_name = lights["objects"][0]["name"]

                res = unwrap(await s.call_tool("get_object_fields",
                             {"object_type": "Lights", "object_name": lts_name}))
                assert res["ok"] is True, res
                props = res["properties"]
                defn_keys = [k for k, v in props.items()
                             if v.get("type", "").startswith("definition(")]
                assert len(defn_keys) >= 1, (
                    f"No definition fields in Lights: {list(props.keys())}"
                )

    asyncio.run(_run())


@pytest.mark.integration
def test_equivalence_boiler_properties():
    """get_object_fields returns efficiency matching get_component_properties."""
    if not integration_enabled():
        pytest.skip("integration")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _create_baseline_with_hvac(s, _unique("pytest_equiv_cp"))

                # Find boiler
                boilers = unwrap(await s.call_tool("list_model_objects",
                                 {"object_type": "BoilerHotWater", "max_results": 1}))
                assert boilers["ok"] and boilers["count"] >= 1
                boiler_name = boilers["objects"][0]["name"]

                # Old: get_component_properties
                old = unwrap(await s.call_tool("get_component_properties",
                             {"component_name": boiler_name}))
                # New: get_object_fields
                new = unwrap(await s.call_tool("get_object_fields",
                             {"object_type": "BoilerHotWater",
                              "object_name": boiler_name}))

                assert old["ok"] is True and new["ok"] is True
                # Both should report efficiency
                old_eff = old.get("properties", {}).get(
                    "nominal_thermal_efficiency", {}).get("value")
                new_eff = new.get("properties", {}).get(
                    "nominalThermalEfficiency", {}).get("value")
                assert old_eff is not None, f"Old tool missing efficiency: {old}"
                assert new_eff is not None, f"New tool missing efficiency: {new}"
                assert abs(old_eff - new_eff) < 0.001, f"{old_eff} != {new_eff}"

    asyncio.run(_run())
