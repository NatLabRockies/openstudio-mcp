"""Integration tests for HVAC skill."""
import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_hvac") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_list_air_loops():
    """Test listing all air loop HVAC systems."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # List air loops
                air_loops_resp = await session.call_tool("list_air_loops", {"detailed": True})
                air_loops_result = unwrap(air_loops_resp)
                print("list_air_loops:", air_loops_result)

                assert isinstance(air_loops_result, dict)
                assert air_loops_result.get("ok") is True, air_loops_result
                assert "count" in air_loops_result
                assert "air_loops" in air_loops_result
                assert isinstance(air_loops_result["air_loops"], list)

                # Example model may not have air loops
                if air_loops_result["air_loops"]:
                    air_loop = air_loops_result["air_loops"][0]
                    assert "name" in air_loop
                    assert "num_thermal_zones" in air_loop
                    assert "thermal_zones" in air_loop
                    assert "num_supply_components" in air_loop
                    assert "supply_components" in air_loop

                    print(f"Found {air_loops_result['count']} air loops")
                    print(f"First air loop: {air_loop['name']} serving {air_loop['num_thermal_zones']} zones")
                else:
                    print("No air loops found in model (OK for example model)")

    asyncio.run(_run())


@pytest.mark.integration
def test_get_air_loop_details():
    """Test getting details for a specific air loop."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # First list air loops to see if any exist
                list_resp = await session.call_tool("list_air_loops", {})
                list_result = unwrap(list_resp)
                assert list_result.get("ok") is True

                if list_result["count"] == 0:
                    pytest.skip("No air loops in example model to test")

                air_loop_name = list_result["air_loops"][0]["name"]

                # Get details for the first air loop
                details_resp = await session.call_tool("get_air_loop_details", {"air_loop_name": air_loop_name})
                details_result = unwrap(details_resp)
                print("get_air_loop_details:", details_result)

                assert isinstance(details_result, dict)
                assert details_result.get("ok") is True, details_result
                assert "air_loop" in details_result

                air_loop = details_result["air_loop"]
                assert air_loop["name"] == air_loop_name
                assert "thermal_zones" in air_loop
                assert "supply_components" in air_loop

                print(f"Air loop '{air_loop_name}' has {len(air_loop['supply_components'])} supply components")

    asyncio.run(_run())


@pytest.mark.integration
def test_get_air_loop_details_not_found():
    """Test getting details for a non-existent air loop."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # Try to get non-existent air loop
                details_resp = await session.call_tool("get_air_loop_details", {"air_loop_name": "NonExistentAirLoop"})
                details_result = unwrap(details_resp)
                print("get_air_loop_details (not found):", details_result)

                assert isinstance(details_result, dict)
                assert details_result.get("ok") is False
                assert "error" in details_result
                assert "not found" in details_result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_list_plant_loops():
    """Test listing all plant loops."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # List plant loops
                plant_loops_resp = await session.call_tool("list_plant_loops", {})
                plant_loops_result = unwrap(plant_loops_resp)
                print("list_plant_loops:", plant_loops_result)

                assert isinstance(plant_loops_result, dict)
                assert plant_loops_result.get("ok") is True, plant_loops_result
                assert "count" in plant_loops_result
                assert "plant_loops" in plant_loops_result
                assert isinstance(plant_loops_result["plant_loops"], list)

                # Example model may not have plant loops
                if plant_loops_result["plant_loops"]:
                    plant_loop = plant_loops_result["plant_loops"][0]
                    assert "name" in plant_loop
                    assert "num_supply_components" in plant_loop
                    assert "supply_components" in plant_loop
                    assert "num_demand_components" in plant_loop
                    assert "demand_components" in plant_loop

                    print(f"Found {plant_loops_result['count']} plant loops")
                    print(f"First plant loop: {plant_loop['name']} with {plant_loop['num_supply_components']} supply components")
                else:
                    print("No plant loops found in model (OK for example model)")

    asyncio.run(_run())


@pytest.mark.integration
def test_list_zone_hvac_equipment():
    """Test listing all zone HVAC equipment."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # List zone HVAC equipment
                zone_hvac_resp = await session.call_tool("list_zone_hvac_equipment", {})
                zone_hvac_result = unwrap(zone_hvac_resp)
                print("list_zone_hvac_equipment:", zone_hvac_result)

                assert isinstance(zone_hvac_result, dict)
                assert zone_hvac_result.get("ok") is True, zone_hvac_result
                assert "count" in zone_hvac_result
                assert "zone_hvac_equipment" in zone_hvac_result
                assert isinstance(zone_hvac_result["zone_hvac_equipment"], list)

                # Example model may not have zone HVAC equipment
                if zone_hvac_result["zone_hvac_equipment"]:
                    equipment = zone_hvac_result["zone_hvac_equipment"][0]
                    assert "type" in equipment
                    assert "name" in equipment

                    print(f"Found {zone_hvac_result['count']} zone HVAC equipment items")
                    print(f"First equipment: {equipment['name']} (type: {equipment['type']})")
                else:
                    print("No zone HVAC equipment found in model (OK for example model)")

    asyncio.run(_run())


@pytest.mark.integration
def test_air_loops_baseline():
    """Test air loop queries on baseline model with System 7 HVAC."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_hvac")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name, "ashrae_sys_num": "07"})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr).get("ok") is True

                ar = await session.call_tool("list_air_loops", {})
                ad = unwrap(ar)
                print("baseline air loops:", ad)
                assert ad.get("ok") is True
                assert ad["count"] >= 1
                # System 7 = VAV, should serve multiple zones
                loop = ad["air_loops"][0]
                assert loop["num_thermal_zones"] == 10

                # Also check plant loops (System 7 has chiller+boiler)
                pr = await session.call_tool("list_plant_loops", {})
                pd = unwrap(pr)
                print("baseline plant loops:", pd)
                assert pd.get("ok") is True
                assert pd["count"] >= 2  # HW + CHW loops (+ condenser)

    asyncio.run(_run())


@pytest.mark.integration
def test_hvac_tools_without_loaded_model():
    """Test that HVAC tools fail gracefully when no model is loaded."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to list air loops without loading a model
                air_loops_resp = await session.call_tool("list_air_loops", {})
                air_loops_result = unwrap(air_loops_resp)
                print("list_air_loops (no model):", air_loops_result)

                assert isinstance(air_loops_result, dict)
                assert air_loops_result.get("ok") is False
                assert "error" in air_loops_result
                assert "no model loaded" in air_loops_result["error"].lower()

    asyncio.run(_run())


def test_add_air_loop_json_string_zones():
    """Test add_air_loop accepts thermal_zone_names as JSON string."""
    import json

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                create_resp = await session.call_tool("create_example_osm",
                                                     {"name": "test_airloop_json"})
                create_data = unwrap(create_resp)
                await session.call_tool("load_osm_model",
                                        {"osm_path": create_data["osm_path"]})

                zones_resp = await session.call_tool("list_thermal_zones", {})
                zone_name = unwrap(zones_resp)["thermal_zones"][0]["name"]

                loop_resp = await session.call_tool("add_air_loop", {
                    "name": "JSON Test Loop",
                    "thermal_zone_names": json.dumps([zone_name]),
                })
                loop_data = unwrap(loop_resp)

                assert loop_data.get("ok") is True, (
                    f"JSON-string zone names failed: {loop_data.get('error')}"
                )

    asyncio.run(_run())
