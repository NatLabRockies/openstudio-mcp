"""Integration tests for list_weather_files tool."""
import asyncio

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_list_weather_files():
    """list_weather_files returns ok with EPW entries and expected keys."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resp = await session.call_tool("list_weather_files", {})
                result = unwrap(resp)
                print("list_weather_files:", result)
                assert result.get("ok") is True
                assert result.get("count", 0) > 0

                wf = result["weather_files"][0]
                assert "name" in wf
                assert "path" in wf
                assert "has_ddy" in wf
                assert "has_stat" in wf

                # At least one file should have both companions
                has_both = [f for f in result["weather_files"] if f["has_ddy"] and f["has_stat"]]
                assert len(has_both) > 0, "Expected at least one EPW with .ddy + .stat"

    asyncio.run(_run())


@pytest.mark.integration
def test_list_weather_files_known_city():
    """Boston EPW should be discoverable (from ChangeBuildingLocation tests)."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resp = await session.call_tool("list_weather_files", {})
                result = unwrap(resp)
                assert result.get("ok") is True

                names = [f["name"].lower() for f in result["weather_files"]]
                found = any("boston" in n for n in names)
                assert found, f"Boston EPW not found in {names[:10]}..."

    asyncio.run(_run())


@pytest.mark.integration
def test_weather_file_paths_absolute():
    """All returned paths should be absolute and end with .epw."""
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resp = await session.call_tool("list_weather_files", {})
                result = unwrap(resp)
                assert result.get("ok") is True

                for wf in result["weather_files"]:
                    assert wf["path"].startswith("/"), f"Not absolute: {wf['path']}"
                    assert wf["path"].endswith(".epw"), f"Not .epw: {wf['path']}"

    asyncio.run(_run())
