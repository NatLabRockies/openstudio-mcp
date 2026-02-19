"""Integration tests for ComStock measure tools.

Tests list_comstock_measures, create_typical_building, and ComStock
measures working with the generic apply_measure / list_measure_arguments.
"""
import asyncio
import json
import os
import shlex
import uuid

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def _integration_enabled() -> bool:
    return os.environ.get("RUN_OPENSTUDIO_INTEGRATION", "").strip() in (
        "1", "true", "TRUE", "yes", "YES",
    )


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


def _unique(prefix: str = "pytest_comstock") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _server_params():
    cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    args = shlex.split(args_env) if args_env else []
    return StdioServerParameters(command=cmd, args=args, env=os.environ.copy())


async def _setup_baseline(session, model_name, set_weather=False):
    """Create and load a baseline model (has geometry + space types)."""
    cr = _unwrap(await session.call_tool("create_baseline_osm", {"name": model_name}))
    assert cr.get("ok") is True, f"create_baseline_osm failed: {cr}"
    lr = _unwrap(await session.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
    assert lr.get("ok") is True, f"load_osm_model failed: {lr}"
    if set_weather:
        # Use bundled Houston EPW from ComStock measures
        wr = _unwrap(await session.call_tool("set_weather_file", {
            "epw_path": "/opt/comstock-measures/create_typical_building_from_model"
                        "/tests/USA_TX_Houston-Bush.Intercontinental.AP.722430_TMY3.epw"
        }))
        assert wr.get("ok") is True, f"set_weather_file failed: {wr}"


# --- Test 1: list_comstock_measures returns measures ---
@pytest.mark.integration
def test_list_comstock_measures():
    """Verify list_comstock_measures returns >50 measures with expected fields."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = _unwrap(await s.call_tool("list_comstock_measures", {}))
                assert res.get("ok") is True, f"Failed: {res}"
                assert res["count"] > 50, f"Expected >50 measures, got {res['count']}"
                # Check each measure has required fields
                for m in res["measures"]:
                    assert "name" in m
                    assert "path" in m
                    assert "category" in m
                    assert m["category"] in ("baseline", "upgrade", "setup", "other")

    asyncio.run(_run())


# --- Test 2: list_comstock_measures with category filter ---
@pytest.mark.integration
def test_list_comstock_measures_filter_baseline():
    """Verify category filter returns only baseline measures."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = _unwrap(await s.call_tool("list_comstock_measures", {
                    "category": "baseline"
                }))
                assert res.get("ok") is True, f"Failed: {res}"
                assert res["count"] > 0, "Expected at least 1 baseline measure"
                for m in res["measures"]:
                    assert m["category"] == "baseline", f"Got {m['category']} for {m['name']}"

    asyncio.run(_run())


# --- Test 3: list_measure_arguments on a ComStock measure ---
@pytest.mark.integration
def test_list_measure_arguments_comstock():
    """Call list_measure_arguments on a ComStock measure (set_wall_template)."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # First get the path from list_comstock_measures
                listing = _unwrap(await s.call_tool("list_comstock_measures", {
                    "category": "baseline"
                }))
                assert listing.get("ok") is True
                # Find set_wall_template
                wall_measures = [m for m in listing["measures"]
                                 if m["name"] == "set_wall_template"]
                assert len(wall_measures) == 1, "set_wall_template not found"
                measure_path = wall_measures[0]["path"]
                # Now list its arguments
                res = _unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": measure_path
                }))
                assert res.get("ok") is True, f"Failed: {res}"
                assert len(res["arguments"]) >= 1, "Expected at least 1 argument"

    asyncio.run(_run())


# ComStock measure test model — has geometry, space types, and weather already set
COMSTOCK_TEST_OSM = "/opt/comstock-measures/create_typical_building_from_model/tests/SmallOffice.osm"


# --- Test 4: create_typical_building adds HVAC/constructions ---
@pytest.mark.integration
def test_create_typical_building_default():
    """Load ComStock test model, apply create_typical_building, verify model enriched."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # Load a ComStock test model that has geometry + space types +
                # standards info already configured
                lr = _unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": COMSTOCK_TEST_OSM
                }))
                assert lr.get("ok") is True, f"load_osm_model failed: {lr}"

                # Set weather file with absolute path (model has relative ref)
                wr = _unwrap(await s.call_tool("set_weather_file", {
                    "epw_path": "/opt/comstock-measures/create_typical_building_from_model"
                               "/tests/USA_TX_Houston-Bush.Intercontinental.AP.722430_TMY3.epw"
                }))
                assert wr.get("ok") is True, f"set_weather_file failed: {wr}"

                # Apply create_typical_building
                res = _unwrap(await s.call_tool("create_typical_building", {
                    "climate_zone": "ASHRAE 169-2013-2A",
                }))
                assert res.get("ok") is True, f"create_typical_building failed: {res}"

                # Verify the model now has HVAC and constructions
                summary = _unwrap(await s.call_tool("get_model_summary", {}))
                assert summary.get("ok") is True
                counts = summary.get("counts", summary.get("summary", {}))
                # Should have air loops or zone equipment from HVAC
                total_hvac = counts.get("air_loops", 0) + counts.get("zone_hvac_equipment", 0)
                assert total_hvac > 0, f"Expected HVAC after typical building, got counts: {counts}"

    asyncio.run(_run())


# --- Test 5: apply_measure with a ComStock measure directly ---
@pytest.mark.integration
def test_apply_comstock_measure_direct():
    """Apply simulation_settings ComStock measure via generic apply_measure."""
    if not _integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(_server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _setup_baseline(s, _unique())

                # Find simulation_settings measure path
                listing = _unwrap(await s.call_tool("list_comstock_measures", {
                    "category": "setup"
                }))
                assert listing.get("ok") is True
                sim_measures = [m for m in listing["measures"]
                                if m["name"] == "simulation_settings"]
                assert len(sim_measures) == 1, (
                    f"simulation_settings not found in setup measures: "
                    f"{[m['name'] for m in listing['measures']]}"
                )
                measure_path = sim_measures[0]["path"]

                # Apply it via generic apply_measure
                res = _unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": measure_path
                }))
                assert res.get("ok") is True, f"apply_measure failed: {res}"

    asyncio.run(_run())
