import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_spaces") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_list_spaces():
    """Test listing all spaces."""
    # Validates: example model has exactly 4 spaces with name and floor_area_m2
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

                # List spaces
                spaces_resp = await session.call_tool("list_spaces", {"max_results": 0})
                spaces_result = unwrap(spaces_resp)
                assert spaces_result["ok"] is True
                assert spaces_result["count"] == 4
                assert len(spaces_result["spaces"]) == 4
                assert spaces_result["spaces"][0]["name"], "Space should have a name"
                assert spaces_result["spaces"][0]["floor_area_m2"] > 0, "Space should have area"

    asyncio.run(_run())


@pytest.mark.integration
def test_list_spaces_baseline():
    """Test listing spaces in 10-zone baseline model."""
    # Validates: baseline model has exactly 10 spaces with Core and Perimeter names
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_spaces")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                sr = await session.call_tool("list_spaces", {"max_results": 0})
                sd = unwrap(sr)
                print("baseline spaces:", sd)
                assert sd["ok"] is True
                assert sd["count"] == 10  # 2 floors * 5 zones
                # Check perimeter/core naming
                names = [s["name"] for s in sd["spaces"]]
                assert any("Core" in n for n in names)
                assert any("Perimeter" in n for n in names)

    asyncio.run(_run())


@pytest.mark.integration
def test_thermal_zones_baseline():
    """Test listing thermal zones in baseline model."""
    # Validates: baseline model has exactly 10 thermal zones with name+floor_area fields
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_zones")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                zr = await session.call_tool("list_thermal_zones", {"detailed": True, "max_results": 0})
                zd = unwrap(zr)
                print("baseline zones:", zd)
                assert zd["ok"] is True
                assert zd["count"] == 10
                # Verify zone fields present
                for z in zd["thermal_zones"]:
                    assert z["name"], "Zone should have a name"
                    assert z["floor_area_m2"] > 0, f"Zone {z['name']} should have positive area"

    asyncio.run(_run())


@pytest.mark.integration
def test_list_thermal_zones():
    """Test listing all thermal zones."""
    # Validates: example model has exactly 1 thermal zone with name and floor_area_m2
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

                # List zones
                zones_resp = await session.call_tool("list_thermal_zones", {"detailed": True, "max_results": 0})
                zones_result = unwrap(zones_resp)
                assert zones_result["ok"] is True
                assert zones_result["count"] == 1
                zone = zones_result["thermal_zones"][0]
                assert zone["name"], "Zone should have a name"
                assert zone["floor_area_m2"] > 0, "Zone should have positive area"

    asyncio.run(_run())
