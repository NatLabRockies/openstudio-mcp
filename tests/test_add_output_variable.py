import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_output_var") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_add_output_variable_default():
    """Test adding an output variable with default parameters."""
    # Validates: add_output_variable creates Zone Mean Air Temperature with key=* and Hourly frequency
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
                assert create_result["ok"] is True, f"create_example_osm failed: {create_result.get('error')}"

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True, f"load_osm_model failed: {load_result.get('error')}"

                # Add output variable
                output_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Mean Air Temperature",
                })
                output_result = unwrap(output_resp)

                assert output_result["ok"] is True, f"add_output_variable failed: {output_result.get('error')}"
                assert output_result["output_variable"]["variable_name"] == "Zone Mean Air Temperature"
                assert output_result["output_variable"]["key_value"] == "*"
                assert output_result["output_variable"]["reporting_frequency"] == "Hourly"

    asyncio.run(_run())


@pytest.mark.integration
def test_add_output_variable_with_key():
    """Test adding an output variable for a specific object."""
    # Validates: add_output_variable with key_value targets specific zone
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
                assert create_result["ok"] is True, f"create_example_osm failed: {create_result.get('error')}"

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True, f"load_osm_model failed: {load_result.get('error')}"

                # Get a thermal zone name
                zones_resp = await session.call_tool("list_thermal_zones", {"max_results": 0})
                zones_result = unwrap(zones_resp)
                assert len(zones_result["thermal_zones"]) > 0, "Example model should have thermal zones"
                zone_name = zones_result["thermal_zones"][0]["name"]

                # Add output variable for specific zone
                output_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Mean Air Temperature",
                    "key_value": zone_name,
                })
                output_result = unwrap(output_resp)

                assert output_result["ok"] is True, f"add_output_variable failed: {output_result.get('error')}"
                assert output_result["output_variable"]["key_value"] == zone_name

    asyncio.run(_run())


@pytest.mark.integration
def test_add_output_variable_monthly():
    """Test adding an output variable with monthly reporting."""
    # Validates: add_output_variable respects reporting_frequency=Monthly parameter
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
                assert create_result["ok"] is True, f"create_example_osm failed: {create_result.get('error')}"

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True, f"load_osm_model failed: {load_result.get('error')}"

                # Add output variable with monthly reporting
                output_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Surface Outside Face Temperature",
                    "reporting_frequency": "Monthly",
                })
                output_result = unwrap(output_resp)

                assert output_result["ok"] is True, f"add_output_variable failed: {output_result.get('error')}"
                assert output_result["output_variable"]["reporting_frequency"] == "Monthly"

    asyncio.run(_run())


@pytest.mark.integration
def test_add_output_variable_no_model_loaded():
    """Test error when no model is loaded."""
    # Validates: add_output_variable returns ok=False with "No model loaded" when no model is loaded
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Try to add output variable without loading model
                output_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Mean Air Temperature",
                })
                output_result = unwrap(output_resp)

                assert output_result["ok"] is False
                assert "No model loaded" in output_result["error"]

    asyncio.run(_run())


@pytest.mark.integration
def test_add_multiple_output_variables():
    """Test adding multiple output variables."""
    # Validates: two output variables get distinct handles
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
                assert create_result["ok"] is True, f"create_example_osm failed: {create_result.get('error')}"

                load_resp = await session.call_tool("load_osm_model", {"osm_path": create_result["osm_path"]})
                load_result = unwrap(load_resp)
                assert load_result["ok"] is True, f"load_osm_model failed: {load_result.get('error')}"

                # Add multiple output variables
                var1_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Mean Air Temperature",
                })
                var1_result = unwrap(var1_resp)
                assert var1_result["ok"] is True, f"add var1 failed: {var1_result.get('error')}"

                var2_resp = await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Air System Sensible Heating Rate",
                })
                var2_result = unwrap(var2_resp)
                assert var2_result["ok"] is True, f"add var2 failed: {var2_result.get('error')}"

                # Both should have unique handles
                assert var1_result["output_variable"]["handle"] != var2_result["output_variable"]["handle"], \
                    "Two output variables should have distinct handles"

    asyncio.run(_run())


@pytest.mark.integration
def test_query_timeseries_excludes_design_day_rows():
    """Sizing design-day rows must not blend into run-period query results."""
    # Regression: #87 — Boston's cooling design days fall on 7/21; query_timeseries
    # returned their rows interleaved with run-period rows (duplicate timestamps,
    # phantom peaks identical across runs)
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    from conftest import EPW_PATH, poll_until_done

    name = _unique_name("pytest_qts_dd")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # --- Arrange: 10-zone baseline, Boston weather (DDs on 7/21),
                # run period spanning the design-day date ---
                create_result = unwrap(await session.call_tool(
                    "create_baseline_osm", {"name": name}))
                assert create_result["ok"] is True, create_result
                load_result = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": create_result["osm_path"]}))
                assert load_result["ok"] is True, load_result
                loc_result = unwrap(await session.call_tool(
                    "change_building_location", {"weather_file": EPW_PATH}))
                assert loc_result["ok"] is True, loc_result
                rp_result = unwrap(await session.call_tool("set_run_period", {
                    "begin_month": 7, "begin_day": 20, "end_month": 7, "end_day": 22,
                }))
                assert rp_result["ok"] is True, rp_result
                var_result = unwrap(await session.call_tool("add_output_variable", {
                    "variable_name": "Zone Mean Air Temperature",
                    "key_value": "*", "reporting_frequency": "Hourly",
                }))
                assert var_result["ok"] is True, var_result
                save_result = unwrap(await session.call_tool(
                    "save_osm_model", {"osm_path": f"/runs/{name}/model.osm"}))
                assert save_result["ok"] is True, save_result

                # --- Act: simulate, query one zone across the DD-overlapping window ---
                sim_result = unwrap(await session.call_tool("run_simulation", {
                    "osm_path": f"/runs/{name}/model.osm", "epw_path": EPW_PATH,
                }))
                assert sim_result["ok"] is True, sim_result
                status = await poll_until_done(session, sim_result["run_id"])
                assert status["run"]["status"] == "success", status
                query_args = {
                    "run_id": sim_result["run_id"],
                    "variable_name": "Zone Mean Air Temperature",
                    "key_value": "Story 1 Core Thermal Zone",
                    "start_month": 7, "start_day": 20,
                    "end_month": 7, "end_day": 22, "max_points": 2000,
                }
                result = unwrap(await session.call_tool("query_timeseries", query_args))

                # --- Assert: exactly 3 days x 24 hourly rows, no duplicates ---
                assert result["ok"] is True, result
                assert result["count"] == 72, (
                    f"3 run-period days x 24 hourly rows expected, got "
                    f"{result['count']} — design-day rows blended in")
                stamps = [(d["month"], d["day"], d["hour"], d["minute"])
                          for d in result["data"]]
                assert len(set(stamps)) == len(stamps), (
                    "duplicate timestamps = sizing environments in results")

                # environment='all' must expose the DD rows on 7/21 (proves the
                # sizing data existed and the default filter did the work)
                all_result = unwrap(await session.call_tool(
                    "query_timeseries", {**query_args, "environment": "all"}))
                assert all_result["ok"] is True, all_result
                assert all_result["count"] > 72, (
                    f"environment='all' should include design-day rows on 7/21, "
                    f"got {all_result['count']}")

    asyncio.run(_run())
