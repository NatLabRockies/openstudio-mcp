"""Integration tests for import_gbxml (gbXML -> OSM via gbxml-to-openstudio measures).

Fixture: tests/assets/gbxml/25_SpacesOneZE.xml — a scaled-down copy of the
same fixture the upstream gbxml_import_advanced/gbxml_import_hvac measures use
in their own test suites (200_SpacesOneZE.xml). The gbXML.org "Standard Test
Model 2016" (schema conformance fixture) was tried first but isn't compatible
with the full pipeline: gbxml_import_advanced's schedule-building code crashes
on it (it lacks populated Schedule data the advanced/hvac measures expect —
that fixture is meant for basic schema-structure testing, not a full building
import).
"""
import asyncio
import os
import shutil
import uuid
from pathlib import Path

import pytest
from conftest import EPW_PATH, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

GBXML_PATH = "/repo/tests/assets/gbxml/25_SpacesOneZE.xml"
RUN_ROOT = Path(os.environ.get("OPENSTUDIO_MCP_RUN_ROOT", os.environ.get("OSMCP_RUN_ROOT", "/runs")))


def _unique_name(prefix: str = "pytest_gbxml") -> str:
    token = uuid.uuid4().hex[:10]
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip()
    if worker:
        return f"{prefix}_{worker}_{token}"
    return f"{prefix}_{token}"


@pytest.mark.integration
def test_import_gbxml_basic():
    """Test translating a 25-space gbXML fixture with a user-supplied EPW."""
    # Validates: import_gbxml runs all 6 gbxml-to-openstudio measures via
    # --measures_only with zero errors/warnings, embeds the EPW's location
    # (ChangeBuildingLocation as the first step), and produces an OSM with
    # exactly the fixture's 25 spaces/zones, 228 surfaces
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    run_name = _unique_name()

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH, "epw_path": EPW_PATH, "run_name": run_name},
                ))
                assert result["ok"] is True, result
                assert result["osm_path"].endswith(".osm")
                assert result["total_errors"] == 0, result
                assert result["total_warnings"] == 0, result
                step_names = [s["measure"] for s in result["step_messages"]["steps"]]
                assert step_names == [
                    "ChangeBuildingLocation", "gbxml_import", "gbxml_import_advanced",
                    "gbxml_import_hvac", "set_simulation_control", "gbxml_postprocess",
                ], step_names

                load_result = unwrap(await session.call_tool(
                    "load_osm_model", {"osm_path": result["osm_path"]},
                ))
                assert load_result["ok"] is True, load_result

                spaces_result = unwrap(await session.call_tool("list_spaces", {"max_results": 0}))
                assert spaces_result["ok"] is True
                assert spaces_result["count"] == 25, spaces_result

                zones_result = unwrap(await session.call_tool("list_thermal_zones", {"max_results": 0}))
                assert zones_result["count"] == 25, zones_result

                surfaces_result = unwrap(await session.call_tool("list_surfaces", {"max_results": 0}))
                assert surfaces_result["count"] == 228, surfaces_result

    asyncio.run(_run())


@pytest.mark.integration
def test_import_gbxml_missing_gbxml_file():
    """Test that a nonexistent gbXML path fails cleanly instead of crashing."""
    # Validates: missing gbxml_path returns ok=False with a specific error, no exception
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": "/inputs/does_not_exist.xml", "epw_path": EPW_PATH},
                ))
                assert result["ok"] is False
                assert result["error"] == "gbXML file not found: /inputs/does_not_exist.xml", result

    asyncio.run(_run())


@pytest.mark.integration
def test_import_gbxml_rejects_wrong_extension():
    """Test that a non-XML file extension is rejected before any measure runs."""
    # Validates: extension guard rejects e.g. a .osm passed as gbxml_path
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": "/repo/tests/assets/SystemD_baseline.osm", "epw_path": EPW_PATH},
                ))
                assert result["ok"] is False
                assert "Not a gbXML file" in result["error"], result

    asyncio.run(_run())


@pytest.mark.integration
def test_import_gbxml_missing_epw_companion():
    """Test that an EPW without a matching .stat file is rejected before any measure runs."""
    # Validates: an EPW copied without its .stat/.ddy siblings fails with a
    # clear "Missing companion .stat file" error instead of crashing inside
    # the ChangeBuildingLocation measure
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    orphan_dir = RUN_ROOT / _unique_name("orphan_epw")
    orphan_dir.mkdir(parents=True, exist_ok=True)
    orphan_epw = orphan_dir / "orphan.epw"
    shutil.copy2(EPW_PATH, orphan_epw)

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                result = unwrap(await session.call_tool(
                    "import_gbxml",
                    {"gbxml_path": GBXML_PATH, "epw_path": str(orphan_epw)},
                ))
                assert result["ok"] is False
                assert "Missing companion .stat file" in result["error"], result

    asyncio.run(_run())
