"""Integration tests for loads skill."""
import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_loads") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_list_people_loads():
    """Test listing all people loads."""
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

                # List people loads
                people_resp = await session.call_tool("list_people_loads", {})
                people_result = unwrap(people_resp)
                print("list_people_loads:", people_result)

                assert isinstance(people_result, dict)
                assert people_result.get("ok") is True, people_result
                assert "count" in people_result
                assert "people_loads" in people_result
                assert isinstance(people_result["people_loads"], list)

                # Example model has people loads
                if people_result["people_loads"]:
                    person = people_result["people_loads"][0]
                    assert "name" in person
                    assert "space" in person

                    print(f"Found {people_result['count']} people loads")

    asyncio.run(_run())


@pytest.mark.integration
def test_list_lighting_loads():
    """Test listing all lighting loads."""
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

                # List lighting loads
                lights_resp = await session.call_tool("list_lighting_loads", {})
                lights_result = unwrap(lights_resp)
                print("list_lighting_loads:", lights_result)

                assert isinstance(lights_result, dict)
                assert lights_result.get("ok") is True, lights_result
                assert "count" in lights_result
                assert "lighting_loads" in lights_result

                if lights_result["lighting_loads"]:
                    print(f"Found {lights_result['count']} lighting loads")

    asyncio.run(_run())


@pytest.mark.integration
def test_list_electric_equipment():
    """Test listing all electric equipment."""
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

                # List electric equipment
                equipment_resp = await session.call_tool("list_electric_equipment", {})
                equipment_result = unwrap(equipment_resp)
                print("list_electric_equipment:", equipment_result)

                assert isinstance(equipment_result, dict)
                assert equipment_result.get("ok") is True, equipment_result
                assert "count" in equipment_result
                assert "electric_equipment" in equipment_result

                if equipment_result["electric_equipment"]:
                    print(f"Found {equipment_result['count']} electric equipment items")

    asyncio.run(_run())


@pytest.mark.integration
def test_list_gas_equipment():
    """Test listing all gas equipment."""
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

                # List gas equipment
                equipment_resp = await session.call_tool("list_gas_equipment", {})
                equipment_result = unwrap(equipment_resp)
                print("list_gas_equipment:", equipment_result)

                assert isinstance(equipment_result, dict)
                assert equipment_result.get("ok") is True, equipment_result
                assert "count" in equipment_result
                assert "gas_equipment" in equipment_result

                if equipment_result["gas_equipment"]:
                    print(f"Found {equipment_result['count']} gas equipment items")

    asyncio.run(_run())


@pytest.mark.integration
def test_list_infiltration():
    """Test listing all infiltration objects."""
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

                # List infiltration
                infiltration_resp = await session.call_tool("list_infiltration", {})
                infiltration_result = unwrap(infiltration_resp)
                print("list_infiltration:", infiltration_result)

                assert isinstance(infiltration_result, dict)
                assert infiltration_result.get("ok") is True, infiltration_result
                assert "count" in infiltration_result
                assert "infiltration" in infiltration_result

                if infiltration_result["infiltration"]:
                    print(f"Found {infiltration_result['count']} infiltration objects")

    asyncio.run(_run())


@pytest.mark.integration
def test_loads_baseline():
    """Test loads across 10 spaces in baseline model."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_loads")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr).get("ok") is True

                # People loads - baseline has people via space type
                pr = await session.call_tool("list_people_loads", {})
                pd = unwrap(pr)
                print("baseline people:", pd)
                assert pd.get("ok") is True
                assert pd["count"] >= 1  # At least 1 People definition

                # Lights
                lr2 = await session.call_tool("list_lighting_loads", {})
                ld = unwrap(lr2)
                assert ld.get("ok") is True
                assert ld["count"] >= 1

                # Electric equipment
                er = await session.call_tool("list_electric_equipment", {})
                ed = unwrap(er)
                assert ed.get("ok") is True
                assert ed["count"] >= 1

                # Infiltration
                ir = await session.call_tool("list_infiltration", {})
                infiltration_data = unwrap(ir)
                assert infiltration_data.get("ok") is True
                assert infiltration_data["count"] >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_loads_tools_without_loaded_model():
    """Test that loads tools fail gracefully when no model is loaded."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to list people without loading a model
                people_resp = await session.call_tool("list_people_loads", {})
                people_result = unwrap(people_resp)
                print("list_people_loads (no model):", people_result)

                assert isinstance(people_result, dict)
                assert people_result.get("ok") is False
                assert "error" in people_result
                assert "no model loaded" in people_result["error"].lower()

    asyncio.run(_run())
