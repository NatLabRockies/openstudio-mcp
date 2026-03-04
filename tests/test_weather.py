"""Integration tests for weather and design day tools (Phase 6C).

Tests get_weather_info, set_weather_file, add_design_day.
EPW files at tests/assets/SEB_model/SEB4_baseboard/files/.
"""
import asyncio
import uuid
from pathlib import Path

import pytest
from conftest import integration_enabled, server_params, setup_example, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_weather") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# EPW path — inside the container, the repo is at /repo
EPW_PATH = "/repo/tests/assets/SEB_model/SEB4_baseboard/files/SRRL_2012AMY_60min.epw"

# Golden CO EPW — available on host and in container
GOLDEN_EPW = "/repo/tests/assets/USA_CO_Golden-NREL.724666_TMY3.epw"


# ---- Unit tests for climate zone estimation (no Docker needed) ----


def test_estimate_climate_zone_golden_co():
    """Golden CO EPW should estimate ASHRAE zone 5 (officially 5B)."""
    from mcp_server.skills.weather.operations import _estimate_climate_zone_from_epw

    epw = Path(__file__).parent / "assets" / "USA_CO_Golden-NREL.724666_TMY3.epw"
    if not epw.exists():
        pytest.skip("Golden CO EPW not in test assets")
    cz = _estimate_climate_zone_from_epw(epw)
    assert cz == "5", f"Expected zone 5, got {cz}"


def test_estimate_climate_zone_bad_file(tmp_path):
    """Non-EPW file should return None, not crash."""
    from mcp_server.skills.weather.operations import _estimate_climate_zone_from_epw

    bad = tmp_path / "bad.epw"
    bad.write_text("not,an,epw\n" * 20)
    assert _estimate_climate_zone_from_epw(bad) is None


# ---- Weather info tests ----

@pytest.mark.integration
def test_get_weather_info_no_weather():
    """Fresh example model has no weather file."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("get_weather_info", {}))
                assert res.get("ok") is True
                assert res["weather_file"] is None
    asyncio.run(_run())


@pytest.mark.integration
def test_set_weather_file():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("set_weather_file", {
                    "epw_path": EPW_PATH,
                }))
                assert res.get("ok") is True
                assert res["weather_file"] is not None

                # Independent query verification
                wi = unwrap(await s.call_tool("get_weather_info", {}))
                assert wi.get("ok") is True
                assert wi["weather_file"] is not None
                assert "SRRL" in wi["weather_file"].get("path", "") or wi["weather_file"].get("latitude") is not None
    asyncio.run(_run())


@pytest.mark.integration
def test_set_weather_file_not_found():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("set_weather_file", {
                    "epw_path": "/nonexistent/weather.epw",
                }))
                assert res.get("ok") is False
    asyncio.run(_run())


@pytest.mark.integration
def test_get_weather_info_after_set():
    """After setting EPW, weather info should have lat/lon."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                unwrap(await s.call_tool("set_weather_file", {"epw_path": EPW_PATH}))
                res = unwrap(await s.call_tool("get_weather_info", {}))
                assert res.get("ok") is True
                wf = res["weather_file"]
                assert wf is not None
                assert "latitude" in wf
                assert "longitude" in wf
                # SRRL is in Golden, CO — lat ~39.7
                assert 39.0 < wf["latitude"] < 40.5
    asyncio.run(_run())


@pytest.mark.integration
def test_set_weather_file_sets_climate_zone():
    """set_weather_file with no .stat file should estimate climate zone from EPW."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("set_weather_file", {
                    "epw_path": GOLDEN_EPW,
                }))
                assert res.get("ok") is True
                # Golden CO is ASHRAE 5B — numeric fallback returns "5"
                assert res.get("climate_zone") == "5", (
                    f"Expected climate_zone='5', got {res.get('climate_zone')}"
                )
    asyncio.run(_run())


# ---- Design day tests ----

@pytest.mark.integration
def test_add_design_day_heating():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("add_design_day", {
                    "name": "Winter 99%",
                    "day_type": "WinterDesignDay",
                    "month": 1, "day": 21,
                    "dry_bulb_max_c": -17.3,
                    "dry_bulb_range_c": 0.0,
                    "humidity_type": "WetBulb",
                    "humidity_value": -17.3,
                    "wind_speed_ms": 4.9,
                }))
                assert res.get("ok") is True
                dd = res["design_day"]
                assert dd["name"] == "Winter 99%"
                assert dd["day_type"] == "WinterDesignDay"
                assert dd["month"] == 1
    asyncio.run(_run())


@pytest.mark.integration
def test_add_design_day_cooling():
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("add_design_day", {
                    "name": "Summer 1%",
                    "day_type": "SummerDesignDay",
                    "month": 7, "day": 21,
                    "dry_bulb_max_c": 33.3,
                    "dry_bulb_range_c": 10.7,
                    "humidity_type": "WetBulb",
                    "humidity_value": 23.8,
                }))
                assert res.get("ok") is True
                assert res["design_day"]["day_type"] == "SummerDesignDay"
    asyncio.run(_run())


@pytest.mark.integration
def test_add_design_day_verify_count():
    """Add two design days and verify count."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Add heating DD
                r1 = unwrap(await s.call_tool("add_design_day", {
                    "name": "Heating DD", "day_type": "WinterDesignDay",
                    "month": 1, "day": 21, "dry_bulb_max_c": -20.0,
                    "dry_bulb_range_c": 0.0,
                }))
                assert r1.get("ok") is True
                # Add cooling DD
                r2 = unwrap(await s.call_tool("add_design_day", {
                    "name": "Cooling DD", "day_type": "SummerDesignDay",
                    "month": 7, "day": 21, "dry_bulb_max_c": 35.0,
                    "dry_bulb_range_c": 11.0,
                }))
                assert r2.get("ok") is True
                # Example model may already have design days, so just check >= 2
                assert r2["total_design_days"] >= 2
    asyncio.run(_run())


@pytest.mark.integration
def test_add_design_day_properties():
    """Verify temperature and humidity set correctly."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("add_design_day", {
                    "name": "Test DD", "day_type": "SummerDesignDay",
                    "month": 8, "day": 15,
                    "dry_bulb_max_c": 36.5, "dry_bulb_range_c": 12.3,
                    "humidity_type": "DewPoint", "humidity_value": 18.0,
                    "wind_speed_ms": 3.5,
                    "barometric_pressure_pa": 100000.0,
                }))
                assert res.get("ok") is True
                dd = res["design_day"]
                assert abs(dd["max_dry_bulb_c"] - 36.5) < 0.01
                assert abs(dd["daily_dry_bulb_range_c"] - 12.3) < 0.01
                assert abs(dd["wind_speed_ms"] - 3.5) < 0.01
                assert abs(dd["barometric_pressure_pa"] - 100000.0) < 1.0
    asyncio.run(_run())


# ---- Simulation control tests ----


@pytest.mark.integration
def test_get_simulation_control_defaults():
    """Fresh model should return simulation control with default values."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("get_simulation_control", {}))
                assert res.get("ok") is True
                sc = res["simulation_control"]
                # All flags should be booleans
                assert isinstance(sc["do_zone_sizing"], bool)
                assert isinstance(sc["do_system_sizing"], bool)
                assert isinstance(sc["do_plant_sizing"], bool)
                assert isinstance(sc["run_for_sizing_periods"], bool)
                assert isinstance(sc["run_for_weather_file"], bool)
                # Timestep should be a positive integer
                assert sc["timesteps_per_hour"] >= 1
    asyncio.run(_run())


@pytest.mark.integration
def test_set_simulation_control_sizing():
    """Set sizing flags and read back."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("set_simulation_control", {
                    "do_zone_sizing": True,
                    "do_system_sizing": True,
                    "do_plant_sizing": True,
                    "run_for_sizing_periods": True,
                    "run_for_weather_file": False,
                }))
                assert res.get("ok") is True
                sc = res["simulation_control"]
                assert sc["do_zone_sizing"] is True
                assert sc["do_system_sizing"] is True
                assert sc["do_plant_sizing"] is True
                assert sc["run_for_sizing_periods"] is True
                assert sc["run_for_weather_file"] is False
    asyncio.run(_run())


@pytest.mark.integration
def test_set_simulation_control_timestep():
    """Set timesteps_per_hour=6 and read back."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("set_simulation_control", {
                    "timesteps_per_hour": 6,
                }))
                assert res.get("ok") is True
                assert res["simulation_control"]["timesteps_per_hour"] == 6

                # Independent query verification
                gc = unwrap(await s.call_tool("get_simulation_control", {}))
                assert gc["simulation_control"]["timesteps_per_hour"] == 6
    asyncio.run(_run())


# ---- Run period tests ----


@pytest.mark.integration
def test_get_run_period_default():
    """Fresh model should have a default RunPeriod."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("get_run_period", {}))
                assert res.get("ok") is True
                rp = res["run_period"]
                assert "begin_month" in rp
                assert "end_month" in rp
    asyncio.run(_run())


@pytest.mark.integration
def test_set_run_period():
    """Set Jan-Mar run period and read back."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("set_run_period", {
                    "begin_month": 1, "begin_day": 1,
                    "end_month": 3, "end_day": 31,
                    "name": "Jan-Mar",
                }))
                assert res.get("ok") is True
                rp = res["run_period"]
                assert rp["begin_month"] == 1
                assert rp["begin_day"] == 1
                assert rp["end_month"] == 3
                assert rp["end_day"] == 31

                # Independent query verification
                gr = unwrap(await s.call_tool("get_run_period", {}))
                grp = gr["run_period"]
                assert grp["begin_month"] == 1
                assert grp["end_month"] == 3
                assert grp["end_day"] == 31
    asyncio.run(_run())


@pytest.mark.integration
def test_set_run_period_full_year():
    """Set full year and read back."""
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("set_run_period", {
                    "begin_month": 1, "begin_day": 1,
                    "end_month": 12, "end_day": 31,
                }))
                assert res.get("ok") is True
                rp = res["run_period"]
                assert rp["begin_month"] == 1
                assert rp["end_month"] == 12
                assert rp["end_day"] == 31

                # Independent query verification
                gr = unwrap(await s.call_tool("get_run_period", {}))
                grp = gr["run_period"]
                assert grp["begin_month"] == 1
                assert grp["begin_day"] == 1
                assert grp["end_month"] == 12
                assert grp["end_day"] == 31
    asyncio.run(_run())
