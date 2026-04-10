import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_constructions") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_list_materials():
    """Test listing all materials."""
    # Validates: example model has materials with name and type fields
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # List materials
                materials_resp = await session.call_tool("list_materials", {"max_results": 0})
                materials_result = unwrap(materials_resp)
                assert materials_result["ok"] is True
                assert materials_result["count"] > 0
                mat = materials_result["materials"][0]
                assert mat["name"], "Material should have a name"
                assert mat["type"], "Material should have a type"

    asyncio.run(_run())


@pytest.mark.integration
def test_list_constructions_via_generic():
    """Test listing all constructions via list_model_objects."""
    # Validates: list_model_objects(Construction) returns objects with name field
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create and load model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result["ok"] is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True

                # List constructions via generic access
                constructions_resp = await session.call_tool("list_model_objects", {"object_type": "Construction", "max_results": 0})
                constructions_result = unwrap(constructions_resp)
                assert constructions_result["ok"] is True
                assert constructions_result["count"] > 0
                assert constructions_result["objects"][0]["name"], "Construction should have a name"

    asyncio.run(_run())


@pytest.mark.integration
def test_constructions_baseline():
    """Test constructions in baseline model with full construction set."""
    # Validates: baseline has >= 5 materials, >= 4 constructions, >= 1 construction set
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_constr")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                # Materials — baseline has walls, roof, floor materials
                mr = await session.call_tool("list_materials", {"max_results": 0})
                md = unwrap(mr)
                print("baseline materials:", md)
                assert md["ok"] is True
                assert md["count"] >= 5  # Multiple materials from construction library

                # Constructions via generic access
                cr2 = await session.call_tool("list_model_objects", {"object_type": "Construction", "max_results": 0})
                cd2 = unwrap(cr2)
                print("baseline constructions:", cd2)
                assert cd2["ok"] is True
                assert cd2["count"] >= 4  # Ext wall, roof, floor, int wall at minimum

                # Construction sets via generic access
                csr = await session.call_tool("list_model_objects", {"object_type": "DefaultConstructionSet"})
                csd = unwrap(csr)
                print("baseline construction sets:", csd)
                assert csd["ok"] is True
                assert csd["count"] >= 1  # DefaultConstructionSet from library

    asyncio.run(_run())
