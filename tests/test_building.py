import asyncio
import json
import os
import shlex
import uuid

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _integration_enabled() -> bool:
    return os.environ.get("RUN_OPENSTUDIO_INTEGRATION", "").strip() in ("1", "true", "TRUE", "yes", "YES")


def _unwrap(res):
    if isinstance(res, dict):
        return res
    content = getattr(res, "content", None)
    if not content:
        return res
    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        return str(first)
    t = text.strip()
    if not t:
        return t
    try:
        return json.loads(t)
    except Exception:
        return t


def _unique_name(prefix: str = "pytest_building") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_get_building_info():
    """Test getting detailed building information."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    name = _unique_name()

    async def _run():
        server_params = StdioServerParameters(
            command=server_cmd,
            args=server_args,
            env=os.environ.copy(),
        )

        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            # Create and load example model
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_result = _unwrap(create_resp)
            assert create_result.get("ok") is True

            load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
            load_result = _unwrap(load_resp)
            assert load_result.get("ok") is True

            # Get building info
            building_resp = await session.call_tool("get_building_info", {})
            building_result = _unwrap(building_resp)
            print("get_building_info:", building_result)

            assert isinstance(building_result, dict)
            assert building_result.get("ok") is True, building_result
            assert "building" in building_result

            building = building_result["building"]
            assert building["name"] == "Building 1"
            assert building["floor_area_m2"] == 400.0
            assert "conditioned_floor_area_m2" in building
            assert "exterior_surface_area_m2" in building
            assert "lighting_power_per_floor_area_w_m2" in building
            assert "number_of_people" in building
            assert isinstance(building["handle"], str)

    asyncio.run(_run())


@pytest.mark.integration
def test_get_model_summary():
    """Test getting model summary with object counts."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    name = _unique_name()

    async def _run():
        server_params = StdioServerParameters(
            command=server_cmd,
            args=server_args,
            env=os.environ.copy(),
        )

        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            # Create and load example model
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_result = _unwrap(create_resp)
            assert create_result.get("ok") is True

            load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
            load_result = _unwrap(load_resp)
            assert load_result.get("ok") is True

            # Get model summary
            summary_resp = await session.call_tool("get_model_summary", {})
            summary_result = _unwrap(summary_resp)
            print("get_model_summary:", summary_result)

            assert isinstance(summary_result, dict)
            assert summary_result.get("ok") is True, summary_result
            assert "summary" in summary_result

            summary = summary_result["summary"]
            # Known values from OpenStudio example model
            assert summary["building_name"] == "Building 1"
            assert summary["floor_area_m2"] == 400.0
            assert summary["spaces"] == 4
            assert summary["thermal_zones"] == 1
            assert summary["space_types"] == 1

            # Verify all expected keys are present
            expected_keys = [
                "building_name",
                "floor_area_m2",
                "conditioned_floor_area_m2",
                "spaces",
                "building_stories",
                "thermal_zones",
                "surfaces",
                "sub_surfaces",
                "shading_surfaces",
                "materials",
                "constructions",
                "construction_sets",
                "space_types",
                "people",
                "lights",
                "electric_equipment",
                "gas_equipment",
                "schedule_rulesets",
                "schedule_constants",
                "air_loops",
                "plant_loops",
                "zone_hvac_equipment",
            ]
            for key in expected_keys:
                assert key in summary, f"Missing key: {key}"

    asyncio.run(_run())


@pytest.mark.integration
def test_list_building_stories():
    """Test listing building stories."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    name = _unique_name()

    async def _run():
        server_params = StdioServerParameters(
            command=server_cmd,
            args=server_args,
            env=os.environ.copy(),
        )

        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            # Create and load example model
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            create_result = _unwrap(create_resp)
            assert create_result.get("ok") is True

            load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
            load_result = _unwrap(load_resp)
            assert load_result.get("ok") is True

            # List building stories
            stories_resp = await session.call_tool("list_building_stories", {})
            stories_result = _unwrap(stories_resp)
            print("list_building_stories:", stories_result)

            assert isinstance(stories_result, dict)
            assert stories_result.get("ok") is True, stories_result
            assert "building_stories" in stories_result
            assert "count" in stories_result

            # Example model has 1 story
            assert stories_result["count"] == 1
            stories = stories_result["building_stories"]
            assert len(stories) == 1

            # Check story attributes
            story = stories[0]
            assert "name" in story
            assert "handle" in story
            assert "num_spaces" in story
            assert story["num_spaces"] == 4  # Example model has 4 spaces

    asyncio.run(_run())


@pytest.mark.integration
def test_building_info_baseline():
    """Test building info with 10-zone baseline model."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    name = _unique_name("pytest_bl_building")

    async def _run():
        server_params = StdioServerParameters(command=server_cmd, args=server_args, env=os.environ.copy())
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            cr = await session.call_tool("create_baseline_osm", {"name": name})
            cd = _unwrap(cr)
            assert cd.get("ok") is True, cd
            lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
            assert _unwrap(lr).get("ok") is True

            br = await session.call_tool("get_building_info", {})
            bd = _unwrap(br)
            print("baseline building_info:", bd)
            assert bd.get("ok") is True, bd
            b = bd["building"]
            assert b["floor_area_m2"] > 1000  # 2 floors * 100m * 50m = 10000 m²

    asyncio.run(_run())


@pytest.mark.integration
def test_building_stories_baseline():
    """Test building stories with 2-story baseline model."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    name = _unique_name("pytest_bl_stories")

    async def _run():
        server_params = StdioServerParameters(command=server_cmd, args=server_args, env=os.environ.copy())
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            cr = await session.call_tool("create_baseline_osm", {"name": name})
            cd = _unwrap(cr)
            assert cd.get("ok") is True, cd
            lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
            assert _unwrap(lr).get("ok") is True

            sr = await session.call_tool("list_building_stories", {})
            sd = _unwrap(sr)
            print("baseline stories:", sd)
            assert sd.get("ok") is True, sd
            assert sd["count"] == 2
            assert len(sd["building_stories"]) == 2
            # Each story has 5 spaces
            for story in sd["building_stories"]:
                assert story["num_spaces"] == 5

    asyncio.run(_run())


@pytest.mark.integration
def test_building_info_no_loads():
    """Regression: get_building_info must not crash with NaN/Inf when model has no loads.

    Bug: density fields (peoplePerFloorArea, etc.) return NaN/Inf from
    OpenStudio when the model has geometry but no people/lights/equipment.
    Pydantic rejects NaN in JSON, causing a hard crash.
    """
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []
    name = _unique_name("pytest_noloads")

    async def _run():
        server_params = StdioServerParameters(command=server_cmd, args=server_args, env=os.environ.copy())
        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            # Baseline model has geometry but no loads
            cr = await session.call_tool("create_baseline_osm", {"name": name})
            cd = _unwrap(cr)
            assert cd.get("ok") is True, cd
            lr = await session.call_tool("load_osm_model", {"osm_path": cd["osm_path"]})
            assert _unwrap(lr).get("ok") is True

            br = await session.call_tool("get_building_info", {})
            bd = _unwrap(br)
            print("no-loads building_info:", bd)
            assert bd.get("ok") is True, f"get_building_info crashed: {bd}"

            b = bd["building"]
            assert b["floor_area_m2"] > 0
            # Density fields should be None (not NaN/Inf) when no loads
            for key in [
                "people_per_floor_area",
                "lighting_power_per_floor_area_w_m2",
                "electric_equipment_power_per_floor_area_w_m2",
                "gas_equipment_power_per_floor_area_w_m2",
            ]:
                val = b[key]
                assert val is None or isinstance(val, (int, float)), f"{key} = {val!r}"

    asyncio.run(_run())


@pytest.mark.integration
def test_building_tools_without_loaded_model():
    """Test that building tools fail gracefully when no model is loaded."""
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    async def _run():
        server_params = StdioServerParameters(
            command=server_cmd,
            args=server_args,
            env=os.environ.copy(),
        )

        async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()

            # Try to get building info without loading a model
            building_resp = await session.call_tool("get_building_info", {})
            building_result = _unwrap(building_resp)
            print("get_building_info (no model):", building_result)

            assert isinstance(building_result, dict)
            assert building_result.get("ok") is False
            assert "error" in building_result
            assert "no model loaded" in building_result["error"].lower()

    asyncio.run(_run())
