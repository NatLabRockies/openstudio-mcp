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

                # List spaces
                spaces_resp = await session.call_tool("list_spaces", {})
                spaces_result = unwrap(spaces_resp)

                assert isinstance(spaces_result, dict)
                assert spaces_result.get("ok") is True
                assert spaces_result["count"] == 4
                assert len(spaces_result["spaces"]) == 4
                assert "name" in spaces_result["spaces"][0]
                assert "floor_area_m2" in spaces_result["spaces"][0]

    asyncio.run(_run())


@pytest.mark.integration
def test_list_spaces_baseline():
    """Test listing spaces in 10-zone baseline model."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_spaces")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr).get("ok") is True

                sr = await session.call_tool("list_spaces", {})
                sd = unwrap(sr)
                print("baseline spaces:", sd)
                assert sd.get("ok") is True
                assert sd["count"] == 10  # 2 floors * 5 zones
                # Check perimeter/core naming
                names = [s["name"] for s in sd["spaces"]]
                assert any("Core" in n for n in names)
                assert any("Perimeter" in n for n in names)

    asyncio.run(_run())


@pytest.mark.integration
def test_thermal_zones_baseline():
    """Test listing thermal zones in baseline model."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_zones")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd.get("ok") is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr).get("ok") is True

                zr = await session.call_tool("list_thermal_zones", {})
                zd = unwrap(zr)
                print("baseline zones:", zd)
                assert zd.get("ok") is True
                assert zd["count"] == 10
                # Each zone has 1 space
                for z in zd["thermal_zones"]:
                    assert z["num_spaces"] == 1

    asyncio.run(_run())


@pytest.mark.integration
def test_list_thermal_zones():
    """Test listing all thermal zones."""
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

                # List zones
                zones_resp = await session.call_tool("list_thermal_zones", {})
                zones_result = unwrap(zones_resp)

                assert isinstance(zones_result, dict)
                assert zones_result.get("ok") is True
                assert zones_result["count"] == 1
                assert "name" in zones_result["thermal_zones"][0]
                assert "num_spaces" in zones_result["thermal_zones"][0]

    asyncio.run(_run())
