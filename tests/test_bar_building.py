"""Integration tests for bar building geometry tools.

Tests create_bar_building, create_new_building, and the bar→typical chain.
"""
import asyncio
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_bar") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


COMSTOCK_EPW = (
    "/opt/comstock-measures/create_typical_building_from_model"
    "/tests/USA_TX_Houston-Bush.Intercontinental.AP.722430_TMY3.epw"
)


# --- Test 1: create_bar_building with defaults (SmallOffice) ---
@pytest.mark.integration
def test_create_bar_building_default():
    """create_bar_building with defaults creates geometry from empty model."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("create_bar_building", {}))
                assert res.get("ok") is True, f"create_bar_building failed: {res}"
                # Should have created spaces, zones, surfaces
                assert res.get("spaces", 0) > 0, f"No spaces: {res}"
                assert res.get("thermal_zones", 0) > 0, f"No zones: {res}"
                assert res.get("surfaces", 0) > 0, f"No surfaces: {res}"
                assert res.get("building_stories", 0) > 0, f"No stories: {res}"

    asyncio.run(_run())


# --- Test 2: create_bar_building LargeOffice 3 stories ---
@pytest.mark.integration
def test_create_bar_building_large_office():
    """create_bar_building with LargeOffice, 3 stories."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("create_bar_building", {
                    "building_type": "LargeOffice",
                    "total_bldg_floor_area": 50000,
                    "num_stories_above_grade": 3,
                    "template": "90.1-2019",
                    "climate_zone": "4A",
                }))
                assert res.get("ok") is True, f"create_bar_building failed: {res}"
                assert res.get("spaces", 0) > 0
                assert res.get("building_stories", 0) >= 3

    asyncio.run(_run())


# --- Test 3: create_bar_building RetailStandalone ---
@pytest.mark.integration
def test_create_bar_building_retail():
    """create_bar_building with RetailStandalone."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("create_bar_building", {
                    "building_type": "RetailStandalone",
                    "total_bldg_floor_area": 25000,
                    "num_stories_above_grade": 1,
                    "wwr": 0.15,
                }))
                assert res.get("ok") is True, f"create_bar_building failed: {res}"
                assert res.get("spaces", 0) > 0

    asyncio.run(_run())


# --- Test 4: create_bar → create_typical chain ---
@pytest.mark.integration
def test_bar_then_typical_chain():
    """create_bar_building then create_typical_building produces complete model."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # Step 1: Create bar geometry
                bar = unwrap(await s.call_tool("create_bar_building", {
                    "building_type": "SmallOffice",
                    "climate_zone": "2A",
                }))
                assert bar.get("ok") is True, f"create_bar failed: {bar}"

                # Step 2: Set weather AFTER bar (apply_measure saves/reloads
                # model which breaks relative weather file paths)
                wr = unwrap(await s.call_tool("set_weather_file", {
                    "epw_path": COMSTOCK_EPW,
                }))
                assert wr.get("ok") is True, f"set_weather_file failed: {wr}"

                # Step 2b: Add design days (needed for HVAC autosizing).
                # In create_new_building, ChangeBuildingLocation handles this.
                # Here we add minimal design days manually.
                dd1 = unwrap(await s.call_tool("add_design_day", {
                    "name": "Houston Summer 1%",
                    "day_type": "SummerDesignDay",
                    "month": 7, "day": 21,
                    "dry_bulb_max_c": 35.0,
                    "dry_bulb_range_c": 10.0,
                    "humidity_type": "WetBulb",
                    "humidity_value": 25.0,
                }))
                assert dd1.get("ok") is True, f"add_design_day summer failed: {dd1}"
                dd2 = unwrap(await s.call_tool("add_design_day", {
                    "name": "Houston Winter 99%",
                    "day_type": "WinterDesignDay",
                    "month": 1, "day": 21,
                    "dry_bulb_max_c": 0.0,
                    "dry_bulb_range_c": 0.0,
                    "humidity_type": "WetBulb",
                    "humidity_value": -2.0,
                }))
                assert dd2.get("ok") is True, f"add_design_day winter failed: {dd2}"

                # Step 3: Apply typical
                typical = unwrap(await s.call_tool("create_typical_building", {
                    "climate_zone": "ASHRAE 169-2013-2A",
                }))
                assert typical.get("ok") is True, f"create_typical failed: {typical}"

                # Verify complete model
                summary = unwrap(await s.call_tool("get_model_summary", {}))
                assert summary.get("ok") is True
                counts = summary.get("counts", summary.get("summary", {}))
                total_hvac = counts.get("air_loops", 0) + counts.get("zone_hvac_equipment", 0)
                assert total_hvac > 0, f"No HVAC after bar+typical: {counts}"

    asyncio.run(_run())


# --- Test 5: create_new_building end-to-end ---
@pytest.mark.integration
def test_create_new_building_with_weather():
    """create_new_building creates complete model with weather in one call."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("create_new_building", {
                    "building_type": "SmallOffice",
                    "total_bldg_floor_area": 10000,
                    "num_stories_above_grade": 1,
                    "weather_file": COMSTOCK_EPW,
                    "template": "90.1-2019",
                }))
                assert res.get("ok") is True, f"create_new_building failed: {res}"
                assert res.get("spaces", 0) > 0, f"No spaces: {res}"
                assert res.get("thermal_zones", 0) > 0, f"No zones: {res}"
                assert res.get("air_loops", 0) + res.get("plant_loops", 0) > 0, (
                    f"No HVAC loops: {res}"
                )

    asyncio.run(_run())


# --- Test 6: create_new_building MediumOffice ---
@pytest.mark.integration
def test_create_new_building_medium_office():
    """create_new_building with MediumOffice, 3 stories."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("create_new_building", {
                    "building_type": "MediumOffice",
                    "total_bldg_floor_area": 50000,
                    "num_stories_above_grade": 3,
                    "weather_file": COMSTOCK_EPW,
                    "template": "90.1-2019",
                }))
                assert res.get("ok") is True, f"create_new_building failed: {res}"
                assert res.get("spaces", 0) > 0
                assert res.get("thermal_zones", 0) > 0

    asyncio.run(_run())


# --- Test 7: SDDC Office seed model loads with FloorspaceJS geometry ---
@pytest.mark.integration
def test_sddc_office_seed_loads():
    """Load SDDC Office seed.osm and verify FloorspaceJS geometry present.

    Phase B preview: confirms seed model with baked-in FloorspaceJS geometry
    loads correctly with expected spaces, surfaces, and space types.
    Full workflow (zones + create_typical) deferred to Phase B.
    """
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # Load the SDDC Office seed model (44 spaces, 328 surfaces, 0 zones)
                lr = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": "/repo/tests/assets/sddc_office/seed.osm",
                }))
                assert lr.get("ok") is True, f"load failed: {lr}"
                assert lr.get("spaces", 0) >= 40, f"Expected ~44 spaces: {lr}"
                assert lr.get("thermal_zones", 0) == 0, "Expected 0 zones in seed"

                # Verify surfaces exist
                surfaces = unwrap(await s.call_tool("list_surfaces", {}))
                assert surfaces.get("ok") is True
                assert surfaces["count"] >= 300, f"Expected ~328 surfaces: {surfaces['count']}"

                # Verify space types exist
                sts = unwrap(await s.call_tool("list_space_types", {}))
                assert sts.get("ok") is True
                assert sts["count"] >= 10, f"Expected ~12 space types: {sts['count']}"

    asyncio.run(_run())
