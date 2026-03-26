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
    # Validates: list_air_loops returns air loop details with zone/component info
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create baseline model with System 7 HVAC (guarantees air loops)
                cr = await session.call_tool("create_baseline_osm", {"name": name, "ashrae_sys_num": "07"})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                # List air loops
                air_loops_result = unwrap(await session.call_tool("list_air_loops", {"detailed": True}))
                assert air_loops_result["ok"] is True, air_loops_result
                assert air_loops_result["count"] >= 1, "System 7 must create at least 1 air loop"
                assert isinstance(air_loops_result["air_loops"], list)

                air_loop = air_loops_result["air_loops"][0]
                assert air_loop["name"], "Air loop should have a name"
                assert air_loop["num_thermal_zones"] >= 1, "System 7 air loop should serve zones"
                assert isinstance(air_loop["thermal_zones"], list)
                assert isinstance(air_loop["supply_components"], list)

    asyncio.run(_run())


@pytest.mark.integration
def test_get_air_loop_details():
    """Test getting details for a specific air loop."""
    # Validates: get_air_loop_details returns loop name, zones, supply components
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create baseline model with System 7 HVAC (guarantees air loops)
                cr = await session.call_tool("create_baseline_osm", {"name": name, "ashrae_sys_num": "07"})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                # List air loops — System 7 guarantees at least 1
                list_result = unwrap(await session.call_tool("list_air_loops", {}))
                assert list_result["ok"] is True
                assert list_result["count"] >= 1, "System 7 must create at least 1 air loop"

                air_loop_name = list_result["air_loops"][0]["name"]

                # Get details for the first air loop
                dr = await session.call_tool(
                    "get_air_loop_details", {"air_loop_name": air_loop_name},
                )
                details_result = unwrap(dr)
                assert details_result["ok"] is True, details_result

                air_loop = details_result["air_loop"]
                assert air_loop["name"] == air_loop_name
                assert isinstance(air_loop["thermal_zones"], list)
                assert len(air_loop["thermal_zones"]) >= 1, "System 7 air loop should serve zones"
                assert isinstance(air_loop["supply_components"], list)
                assert len(air_loop["supply_components"]) >= 1, "Air loop should have supply components"

    asyncio.run(_run())


@pytest.mark.integration
def test_get_air_loop_details_not_found():
    """Test getting details for a non-existent air loop."""
    # Validates: get_air_loop_details returns ok:false with "not found" for bad name
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
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # Try to get non-existent air loop
                details_resp = await session.call_tool("get_air_loop_details", {"air_loop_name": "NonExistentAirLoop"})
                details_result = unwrap(details_resp)
                print("get_air_loop_details (not found):", details_result)
                assert details_result["ok"] is False
                assert "not found" in details_result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_list_plant_loops():
    """Test listing all plant loops."""
    # Validates: list_plant_loops returns plant loop details with supply/demand info
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create baseline model with System 7 HVAC (guarantees HW + CHW plant loops)
                cr = await session.call_tool("create_baseline_osm", {"name": name, "ashrae_sys_num": "07"})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                # List plant loops
                plant_loops_result = unwrap(await session.call_tool("list_plant_loops", {}))
                assert plant_loops_result["ok"] is True, plant_loops_result
                assert plant_loops_result["count"] >= 2, "System 7 needs HW + CHW loops"
                assert isinstance(plant_loops_result["plant_loops"], list)

                plant_loop = plant_loops_result["plant_loops"][0]
                assert plant_loop["name"], "Plant loop should have a name"
                assert plant_loop["num_supply_components"] >= 0
                assert plant_loop["num_demand_components"] >= 0

    asyncio.run(_run())


@pytest.mark.integration
def test_list_zone_hvac_equipment():
    """Test listing all zone HVAC equipment."""
    # Validates: list_zone_hvac_equipment returns equipment type and name fields
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create baseline model with System 1 PTAC (zone-level HVAC equipment)
                cr = await session.call_tool("create_baseline_osm", {"name": name, "ashrae_sys_num": "01"})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                # List zone HVAC equipment
                zone_hvac_result = unwrap(await session.call_tool("list_zone_hvac_equipment", {"max_results": 0}))
                assert zone_hvac_result["ok"] is True, zone_hvac_result
                assert zone_hvac_result["count"] > 0, "System 1 PTAC should produce zone HVAC equipment"
                assert isinstance(zone_hvac_result["zone_hvac_equipment"], list)

                equipment = zone_hvac_result["zone_hvac_equipment"][0]
                assert equipment["type"], "Equipment should have a type"
                assert equipment["name"], "Equipment should have a name"

    asyncio.run(_run())


@pytest.mark.integration
def test_air_loops_baseline():
    """Test air loop queries on baseline model with System 7 HVAC."""
    # Validates: System 7 baseline has 1 air loop serving 10 zones + >= 2 plant loops
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_hvac")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name, "ashrae_sys_num": "07"})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                ar = await session.call_tool("list_air_loops", {})
                ad = unwrap(ar)
                print("baseline air loops:", ad)
                assert ad["ok"] is True
                assert ad["count"] >= 1
                # System 7 = VAV, should serve multiple zones
                loop = ad["air_loops"][0]
                assert loop["num_thermal_zones"] == 10

                # Also check plant loops (System 7 has chiller+boiler)
                pr = await session.call_tool("list_plant_loops", {})
                pd = unwrap(pr)
                print("baseline plant loops:", pd)
                assert pd["ok"] is True
                assert pd["count"] >= 2  # HW + CHW loops (+ condenser)

    asyncio.run(_run())


@pytest.mark.integration
def test_hvac_tools_without_loaded_model():
    """Test that HVAC tools fail gracefully when no model is loaded."""
    # Validates: HVAC tools return ok:false with "no model loaded" when no model
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
                assert air_loops_result["ok"] is False
                assert "no model loaded" in air_loops_result["error"].lower()

    asyncio.run(_run())


def test_add_air_loop_json_string_zones():
    """Test add_air_loop accepts thermal_zone_names as JSON string."""
    # Regression: MCP clients sent zone names as JSON string, caused TypeError in add_air_loop
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

                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zone_name = unwrap(zones_resp)["thermal_zones"][0]["name"]

                loop_resp = await session.call_tool("add_air_loop", {
                    "name": "JSON Test Loop",
                    "thermal_zone_names": json.dumps([zone_name]),
                })
                loop_data = unwrap(loop_resp)

                assert loop_data["ok"] is True, (
                    f"JSON-string zone names failed: {loop_data.get('error')}"
                )

    asyncio.run(_run())
