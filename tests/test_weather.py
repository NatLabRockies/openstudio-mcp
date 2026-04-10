"""Integration tests for weather and design day tools (Phase 6C).

Tests get_weather_info, change_building_location, add_design_day.
Uses Boston EPW from ChangeBuildingLocation measure tests (has .stat + .ddy).
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


# EPW with companion .stat + .ddy (required by ChangeBuildingLocation measure)
EPW_PATH = (
    "/opt/comstock-measures/ChangeBuildingLocation"
    "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
)


# ---- Unit tests for climate zone estimation (no Docker needed) ----


def test_estimate_climate_zone_golden_co():
    """Golden CO EPW should estimate ASHRAE zone 5 (officially 5B)."""
    # Validates: climate zone estimator returns zone 5 for Golden CO EPW (HDD/CDD thresholds)
    from mcp_server.skills.weather.operations import _estimate_climate_zone_from_epw

    epw = Path(__file__).parent / "assets" / "USA_CO_Golden-NREL.724666_TMY3.epw"
    if not epw.exists():
        pytest.skip("Golden CO EPW not in test assets")
    cz = _estimate_climate_zone_from_epw(epw)
    assert cz == "5", f"Expected zone 5, got {cz}"


def test_estimate_climate_zone_bad_file(tmp_path):
    """Non-EPW file should return None, not crash."""
    # Validates: climate zone estimator returns None for malformed EPW instead of raising
    from mcp_server.skills.weather.operations import _estimate_climate_zone_from_epw

    bad = tmp_path / "bad.epw"
    bad.write_text("not,an,epw\n" * 20)
    assert _estimate_climate_zone_from_epw(bad) is None


# ---- Weather info tests ----

@pytest.mark.integration
def test_get_weather_info_no_weather():
    """Fresh example model has no weather file."""
    # Validates: get_weather_info returns weather_file=None on fresh model without EPW
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("get_weather_info", {}))
                assert res["ok"] is True, f"get_weather_info failed: {res.get('error')}"
                assert res["weather_file"] is None
    asyncio.run(_run())


@pytest.mark.integration
def test_change_building_location():
    """change_building_location sets weather, design days, and climate zone."""
    # Validates: change_building_location sets EPW and get_weather_info confirms it
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW_PATH,
                }))
                assert res["ok"] is True, f"change_building_location failed: {res.get('error')}"

                # Independent query verification
                wi = unwrap(await s.call_tool("get_weather_info", {}))
                assert wi["ok"] is True
                assert isinstance(wi["weather_file"], dict), "weather_file should be dict after setting EPW"
    asyncio.run(_run())


@pytest.mark.integration
def test_get_weather_info_after_set():
    """After setting location, weather info should have lat/lon."""
    # Validates: get_weather_info returns Boston lat/lon (~42.4) after setting Boston EPW
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                unwrap(await s.call_tool("change_building_location", {
                    "weather_file": EPW_PATH,
                }))
                res = unwrap(await s.call_tool("get_weather_info", {}))
                assert res["ok"] is True
                wf = res["weather_file"]
                assert isinstance(wf, dict), "weather_file should be dict after setting EPW"
                # Boston Logan — lat ~42.4
                assert 42.0 < wf["latitude"] < 43.0, \
                    f"Boston latitude should be ~42.4, got {wf['latitude']}"
                assert -72.0 < wf["longitude"] < -70.0, \
                    f"Boston longitude should be ~-71, got {wf['longitude']}"
    asyncio.run(_run())


# ---- Design day tests ----

@pytest.mark.integration
def test_add_design_day_heating():
    # Validates: add_design_day creates WinterDesignDay with correct name, type, and month
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
                assert res["ok"] is True, f"add_design_day failed: {res.get('error')}"
                dd = res["design_day"]
                assert dd["name"] == "Winter 99%"
                assert dd["day_type"] == "WinterDesignDay"
                assert dd["month"] == 1
    asyncio.run(_run())


@pytest.mark.integration
def test_add_design_day_cooling():
    # Validates: add_design_day creates SummerDesignDay with correct day_type
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
                assert res["ok"] is True, f"add_design_day failed: {res.get('error')}"
                assert res["design_day"]["day_type"] == "SummerDesignDay"
    asyncio.run(_run())


@pytest.mark.integration
def test_add_design_day_verify_count():
    """Add two design days and verify count."""
    # Validates: adding two design days increments total_design_days to >= 2
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
                assert r1["ok"] is True, f"add_design_day (heating) failed: {r1.get('error')}"
                # Add cooling DD
                r2 = unwrap(await s.call_tool("add_design_day", {
                    "name": "Cooling DD", "day_type": "SummerDesignDay",
                    "month": 7, "day": 21, "dry_bulb_max_c": 35.0,
                    "dry_bulb_range_c": 11.0,
                }))
                assert r2["ok"] is True, f"add_design_day (cooling) failed: {r2.get('error')}"
                # Example model may already have design days, so just check >= 2
                assert r2["total_design_days"] >= 2, \
                    f"Expected >= 2 design days after adding heating+cooling, got {r2['total_design_days']}"
    asyncio.run(_run())


@pytest.mark.integration
def test_add_design_day_properties():
    """Verify temperature and humidity set correctly."""
    # Validates: add_design_day stores exact temperature, wind, and pressure values
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
                assert res["ok"] is True, f"add_design_day failed: {res.get('error')}"
                dd = res["design_day"]
                assert dd["max_dry_bulb_c"] == pytest.approx(36.5, abs=0.01)
                assert dd["daily_dry_bulb_range_c"] == pytest.approx(12.3, abs=0.01)
                assert dd["wind_speed_ms"] == pytest.approx(3.5, abs=0.01)
                assert dd["barometric_pressure_pa"] == pytest.approx(100000.0, abs=1.0)
    asyncio.run(_run())


# ---- Simulation control tests ----


@pytest.mark.integration
def test_get_simulation_control_defaults():
    """Fresh model should return simulation control with default values."""
    # Validates: get_simulation_control returns boolean flags and positive timestep on fresh model
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("get_simulation_control", {}))
                assert res["ok"] is True, f"get_simulation_control failed: {res.get('error')}"
                sc = res["simulation_control"]
                # All flags should be booleans
                assert isinstance(sc["do_zone_sizing"], bool)
                assert isinstance(sc["do_system_sizing"], bool)
                assert isinstance(sc["do_plant_sizing"], bool)
                assert isinstance(sc["run_for_sizing_periods"], bool)
                assert isinstance(sc["run_for_weather_file"], bool)
                # Timestep should be a positive integer
                assert sc["timesteps_per_hour"] >= 1, \
                    f"timesteps_per_hour must be positive, got {sc['timesteps_per_hour']}"
    asyncio.run(_run())


@pytest.mark.integration
def test_set_simulation_control_sizing():
    """Set sizing flags and read back."""
    # Validates: set_simulation_control round-trips all 5 boolean sizing flags
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
                assert res["ok"] is True, f"set_simulation_control failed: {res.get('error')}"
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
    # Validates: set_simulation_control round-trips timesteps_per_hour=6 via independent get
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
                assert res["ok"] is True, f"set_simulation_control failed: {res.get('error')}"
                assert res["simulation_control"]["timesteps_per_hour"] == 6

                # Independent query verification
                gc = unwrap(await s.call_tool("get_simulation_control", {}))
                assert gc["simulation_control"]["timesteps_per_hour"] == 6
    asyncio.run(_run())


# ---- Run period tests ----


@pytest.mark.integration
def test_get_run_period_default():
    """Fresh model should have a default RunPeriod."""
    # Validates: get_run_period returns begin_month and end_month on fresh model
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("get_run_period", {}))
                assert res["ok"] is True, f"get_run_period failed: {res.get('error')}"
                rp = res["run_period"]
                assert isinstance(rp["begin_month"], int), "begin_month should be int"
                assert isinstance(rp["end_month"], int), "end_month should be int"
                assert rp["begin_month"] == 1, f"Default begin_month should be 1 (Jan), got {rp['begin_month']}"
                assert rp["end_month"] == 12, f"Default end_month should be 12 (Dec), got {rp['end_month']}"
    asyncio.run(_run())


@pytest.mark.integration
def test_set_run_period():
    """Set Jan-Mar run period and read back."""
    # Validates: set_run_period round-trips Jan 1 to Mar 31 via independent get
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
                assert res["ok"] is True, f"set_run_period failed: {res.get('error')}"
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
    # Validates: set_run_period round-trips full year (Jan 1 - Dec 31) via independent get
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
                assert res["ok"] is True, f"set_run_period failed: {res.get('error')}"
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
