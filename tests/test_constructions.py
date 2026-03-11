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
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # List materials
                materials_resp = await session.call_tool("list_materials", {"max_results": 0})
                materials_result = unwrap(materials_resp)

                assert isinstance(materials_result, dict)
                assert materials_result.get("ok") is True
                assert materials_result["count"] > 0
                assert "name" in materials_result["materials"][0]
                assert "type" in materials_result["materials"][0]

    asyncio.run(_run())


@pytest.mark.integration
def test_list_constructions():
    """Test listing all constructions."""
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
                assert create_result.get("ok") is True

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result.get("ok") is True

                # List constructions
                constructions_resp = await session.call_tool("list_constructions", {"max_results": 0})
                constructions_result = unwrap(constructions_resp)

                assert isinstance(constructions_result, dict)
                assert constructions_result.get("ok") is True
                assert constructions_result["count"] > 0
                assert "name" in constructions_result["constructions"][0]
                assert "layers" in constructions_result["constructions"][0]

    asyncio.run(_run())


@pytest.mark.integration
def test_constructions_baseline():
    """Test constructions in baseline model with full construction set."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_constr")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr).get("ok") is True

                # Materials — baseline has walls, roof, floor materials
                mr = await session.call_tool("list_materials", {"max_results": 0})
                md = unwrap(mr)
                print("baseline materials:", md)
                assert md.get("ok") is True
                assert md["count"] >= 5  # Multiple materials from construction library

                # Constructions
                cr2 = await session.call_tool("list_constructions", {"max_results": 0})
                cd2 = unwrap(cr2)
                print("baseline constructions:", cd2)
                assert cd2.get("ok") is True
                assert cd2["count"] >= 4  # Ext wall, roof, floor, int wall at minimum

                # Construction sets
                csr = await session.call_tool("list_construction_sets", {})
                csd = unwrap(csr)
                print("baseline construction sets:", csd)
                assert csd.get("ok") is True
                assert csd["count"] >= 1  # DefaultConstructionSet from library

    asyncio.run(_run())
