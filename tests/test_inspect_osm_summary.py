import asyncio
import os
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique_name(prefix: str = "pytest_demo1b") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_inspect_osm_summary_exact_values():
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

                # Inspect it
                insp_resp = await session.call_tool("inspect_osm_summary", {"osm_path": osm_path})
                summary = unwrap(insp_resp)
                print("inspect_osm_summary:", summary)

                assert isinstance(summary, dict)
                assert summary.get("ok") is True, summary

                # Exact expectations for OpenStudio's example model (3.11.0)
                assert summary.get("building_name") == "Building 1"
                assert summary.get("spaces") == 4
                assert summary.get("thermal_zones") == 1
                assert summary.get("space_types_count") == 1
                assert summary.get("space_types") == ["Space Type 1"]
                assert summary.get("floor_area_m2") == 400.0
                assert summary.get("openstudio_version") == "3.11.0"

    asyncio.run(_run())
