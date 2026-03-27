"""Integration tests for loads skill.

list_* tools removed in Phase C — use list_model_objects instead.
Kept: get_load_details, loads_baseline (converted to list_model_objects).
"""
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
def test_loads_baseline():
    """Test loads across 10 spaces in baseline model via list_model_objects."""
    # Validates: baseline model has People, Lights, ElectricEquipment, Infiltration objects
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    name = _unique_name("pytest_bl_loads")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                cr = await session.call_tool("create_baseline_osm", {"name": name})
                cd = unwrap(cr)
                assert cd["ok"] is True, cd
                lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
                assert unwrap(lr)["ok"] is True

                # People via list_model_objects
                pr = unwrap(await session.call_tool("list_model_objects",
                            {"object_type": "People", "max_results": 0}))
                print("baseline people:", pr)
                assert pr["ok"] is True
                assert pr["count"] >= 1

                # Lights
                lr2 = unwrap(await session.call_tool("list_model_objects",
                             {"object_type": "Lights", "max_results": 0}))
                assert lr2["ok"] is True
                assert lr2["count"] >= 1

                # Electric equipment
                er = unwrap(await session.call_tool("list_model_objects",
                            {"object_type": "ElectricEquipment", "max_results": 0}))
                assert er["ok"] is True
                assert er["count"] >= 1

                # Infiltration
                ir = unwrap(await session.call_tool("list_model_objects",
                            {"object_type": "SpaceInfiltrationDesignFlowRate", "max_results": 0}))
                assert ir["ok"] is True
                assert ir["count"] >= 1

    asyncio.run(_run())


@pytest.mark.integration
def test_loads_tools_without_loaded_model():
    """Test that list_model_objects fails gracefully when no model is loaded."""
    # Validates: list_model_objects returns ok:false with "no model loaded" when no model
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to list people without loading a model
                people_resp = await session.call_tool("list_model_objects",
                              {"object_type": "People", "max_results": 0})
                people_result = unwrap(people_resp)
                print("list_model_objects People (no model):", people_result)
                assert people_result["ok"] is False
                assert "no model loaded" in people_result["error"].lower()

    asyncio.run(_run())
