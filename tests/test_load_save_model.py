import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_load_save") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_load_osm_model():
    """Test loading an OSM file into the current model state."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                print("create_example_osm:", create_result)
                assert isinstance(create_result, dict)
                assert create_result.get("ok") is True
                osm_path = create_result.get("osm_path")
                assert osm_path and str(osm_path).endswith(".osm")

                # Load it into current model state
                load_resp = await session.call_tool("load_osm_model", {"osm_path": osm_path})
                load_result = unwrap(load_resp)
                print("load_osm_model:", load_result)

                assert isinstance(load_result, dict)
                assert load_result.get("ok") is True, load_result
                assert load_result.get("osm_path") == osm_path
                assert load_result.get("building_name") == "Building 1"
                assert load_result.get("spaces") == 4
                assert load_result.get("thermal_zones") == 1
                assert "message" in load_result
                assert "successfully" in load_result["message"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_save_osm_model():
    """Test saving a loaded model to a new location."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create example model
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                print("create_example_osm:", create_result)
                assert isinstance(create_result, dict)
                assert create_result.get("ok") is True
                osm_path = create_result.get("osm_path")
                out_dir = create_result.get("out_dir")
                assert osm_path and str(osm_path).endswith(".osm")

                # Load it
                load_resp = await session.call_tool("load_osm_model", {"osm_path": osm_path})
                load_result = unwrap(load_resp)
                print("load_osm_model:", load_result)
                assert load_result.get("ok") is True

                # Save to same location (no save_path argument)
                save1_resp = await session.call_tool("save_osm_model", {})
                save1_result = unwrap(save1_resp)
                print("save_osm_model (same path):", save1_result)

                assert isinstance(save1_result, dict)
                assert save1_result.get("ok") is True, save1_result
                assert save1_result.get("osm_path") == osm_path
                assert "message" in save1_result
                assert "successfully" in save1_result["message"].lower()

                # Save to new location
                # Use forward slashes for Docker/Linux paths
                new_path = f"{out_dir}/saved_copy.osm"
                save2_resp = await session.call_tool("save_osm_model", {"osm_path": new_path})
                save2_result = unwrap(save2_resp)
                print("save_osm_model (new path):", save2_result)

                assert isinstance(save2_result, dict)
                assert save2_result.get("ok") is True, save2_result
                # Check that the path ends with the expected file
                assert save2_result.get("osm_path", "").endswith("saved_copy.osm"), save2_result

                # Verify the new file can be inspected
                inspect_resp = await session.call_tool("inspect_osm_summary", {"osm_path": new_path})
                inspect_result = unwrap(inspect_resp)
                print("inspect_osm_summary (saved copy):", inspect_result)
                assert inspect_result.get("ok") is True
                assert inspect_result.get("building_name") == "Building 1"

    asyncio.run(_run())


@pytest.mark.integration
def test_save_without_load_fails():
    """Test that save_osm_model fails when no model is loaded."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to save without loading first
                save_resp = await session.call_tool("save_osm_model", {})
                save_result = unwrap(save_resp)
                print("save_osm_model (no model loaded):", save_result)

                assert isinstance(save_result, dict)
                assert save_result.get("ok") is False
                assert "error" in save_result
                assert "no model loaded" in save_result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_load_nonexistent_file_fails():
    """Test that load_osm_model fails gracefully for nonexistent file."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to load a file that doesn't exist
                fake_path = "/runs/nonexistent_model_xyz123.osm"
                load_resp = await session.call_tool("load_osm_model", {"osm_path": fake_path})
                load_result = unwrap(load_resp)
                print("load_osm_model (nonexistent file):", load_result)

                assert isinstance(load_result, dict)
                assert load_result.get("ok") is False
                assert "error" in load_result
                assert "not found" in load_result["error"].lower()

    asyncio.run(_run())


@pytest.mark.integration
def test_list_files():
    """Test list_files discovers files in /runs after creating an example model."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    name = _unique_name("pytest_list_files")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Create a model so /runs has something in it
                create_resp = await session.call_tool("create_example_osm", {"name": name})
                create_result = unwrap(create_resp)
                assert create_result.get("ok") is True

                # List all files — should find the OSM we just created
                list_resp = await session.call_tool("list_files", {"max_results": 0})
                list_result = unwrap(list_resp)
                print("list_files (all):", list_result)
                assert list_result.get("ok") is True
                assert list_result.get("total", 0) >= 1
                names = [f["name"] for f in list_result["items"]]
                assert "example_model.osm" in names

                # Filter by pattern
                osm_resp = await session.call_tool("list_files", {"pattern": "*.osm", "max_results": 0})
                osm_result = unwrap(osm_resp)
                print("list_files (*.osm):", osm_result)
                assert osm_result.get("ok") is True
                osm_files = [f for f in osm_result["items"] if f["type"] == "file"]
                assert all(f["name"].endswith(".osm") for f in osm_files)

                # Filter by pattern with no matches
                epw_resp = await session.call_tool("list_files", {"pattern": "*.xyz_no_match", "max_results": 0})
                epw_result = unwrap(epw_resp)
                print("list_files (no match):", epw_result)
                assert epw_result.get("ok") is True
                assert epw_result.get("total") == 0

                # Specific directory
                runs_resp = await session.call_tool("list_files", {"directory": "/runs", "max_results": 0})
                runs_result = unwrap(runs_resp)
                print("list_files (/runs):", runs_result)
                assert runs_result.get("ok") is True
                assert runs_result.get("total", 0) >= 1

                # Disallowed directory
                bad_resp = await session.call_tool("list_files", {"directory": "/etc", "max_results": 0})
                bad_result = unwrap(bad_resp)
                print("list_files (/etc):", bad_result)
                assert bad_result.get("ok") is False
                assert "not allowed" in bad_result.get("error", "").lower()

    asyncio.run(_run())
