"""Integration tests for measures tools (Phase 6D).

Tests list_measure_arguments, apply_measure.
Uses a minimal test measure at tests/assets/measures/set_building_name/.
"""
import asyncio
import uuid
from pathlib import Path

import pytest
from conftest import integration_enabled, server_params, setup_example, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_measures") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# Measure path inside container (repo mounted at /repo)
MEASURE_DIR = "/repo/tests/assets/measures/set_building_name"

BOGUS_EPW_NAME = "ZZZ_Nowhere.Fake.999999_TMY3.epw"


def _bogus_weather_fixture() -> str:
    """Copy of SystemD_baseline.osm with its weather url renamed to an EPW
    that exists nowhere on disk. Returns the fixture's container path."""
    src = Path("/repo/tests/assets/SystemD_baseline.osm").read_text()
    fixture = Path("/runs") / f"{_unique('pytest_bogus_weather')}.osm"
    fixture.write_text(src.replace(
        "USA_MD_Baltimore-Washington.Intl.AP.724060_TMY3.epw", BOGUS_EPW_NAME))
    return str(fixture)


@pytest.mark.integration
def test_list_measure_arguments():
    # Validates: list_measure_arguments returns building_name arg for set_building_name measure
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": MEASURE_DIR,
                }))
                assert res["ok"] is True
                arg_names = [a["name"] for a in res["arguments"]]
                assert "building_name" in arg_names, f"Expected building_name in {arg_names}"
    asyncio.run(_run())


@pytest.mark.integration
def test_list_measure_not_found():
    # Validates: list_measure_arguments returns error for nonexistent measure directory
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = unwrap(await s.call_tool("list_measure_arguments", {
                    "measure_dir": "/nonexistent/measure",
                }))
                assert res["ok"] is False
                assert "error" in res, "Missing error message for nonexistent measure"
                assert res["error"].strip(), "Error should have non-empty message for nonexistent measure"
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_default_args():
    # Validates: apply_measure with default args sets building name to "Test Building"
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                }))
                assert res["ok"] is True
                # After measure, building name should be "Test Building" (default)
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg["ok"] is True
                assert bldg["building"]["name"] == "Test Building"
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_custom_args():
    # Validates: apply_measure passes custom arguments through to measure
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                    "arguments": {"building_name": "My Custom Building"},
                }))
                assert res["ok"] is True
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg["ok"] is True
                assert bldg["building"]["name"] == "My Custom Building"
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_invalid_dir():
    """Measure with bad directory path."""
    # Validates: apply_measure returns error for nonexistent measure directory
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": "/nonexistent/measure",
                }))
                assert res["ok"] is False
                assert "error" in res, "Missing error message for invalid measure dir"
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_bare_weather_filename():
    """Model whose OS:WeatherFile Url is a bare filename (the OSM convention)."""
    # Regression: apply_measure failed with "Weather file ... cannot be found" on models
    # with a bare-filename weather url (e.g. SystemD_baseline.osm) — operations.py only
    # added the EPW dir to OSW file_paths when the url resolved from server cwd, so the
    # OSW runner's Initialization state errored before the measure ran
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # SystemD_baseline.osm has OS:WeatherFile Url =
                # "USA_MD_Baltimore-Washington.Intl.AP.724060_TMY3.epw" (no path)
                load = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": "/repo/tests/assets/SystemD_baseline.osm",
                }))
                assert load["ok"] is True, f"load failed: {load.get('error')}"
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                    "arguments": {"building_name": "Beam Retrofit Candidate"},
                }))
                assert res["ok"] is True, (
                    f"apply_measure must not require a resolvable weather file for "
                    f"--measures_only runs: {res.get('error')}"
                )
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg["building"]["name"] == "Beam Retrofit Candidate"
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_unfindable_weather_stripped_and_restored():
    """Model EPW exists nowhere — weather stripped from seed, restored after."""
    # Validates: apply_measure succeeds when the model's EPW url resolves nowhere
    # (OS:WeatherFile stripped from the OSW seed for --measures_only) and the
    # reloaded model keeps its original weather reference afterward
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                load = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": _bogus_weather_fixture(),
                }))
                assert load["ok"] is True, f"load failed: {load.get('error')}"
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                    "arguments": {"building_name": "Stripped Weather Building"},
                }))
                assert res["ok"] is True, f"apply failed: {res.get('error')}"
                assert "restored" in res["weather_note"], (
                    f"Expected stripped+restored note, got: {res.get('weather_note')}"
                )
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg["building"]["name"] == "Stripped Weather Building"
                # Original (unresolvable) weather reference must survive the round-trip
                weather = unwrap(await s.call_tool("get_weather_info", {}))
                assert weather["ok"] is True, f"weather lost: {weather.get('error')}"
                assert weather["weather_file"]["url"] == BOGUS_EPW_NAME
                assert weather["weather_file"]["city"] == "Baltimore Blt Washngtn IntL"
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_weather_setting_measure_not_clobbered():
    """Measure that sets weather (ChangeBuildingLocation) wins over restore."""
    # Validates: when weather was stripped (unresolvable url) and the measure itself
    # sets a new weather file, the measure's weather is kept — restore must not
    # overwrite ChangeBuildingLocation's result with the stale reference
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                load = unwrap(await s.call_tool("load_osm_model", {
                    "osm_path": _bogus_weather_fixture(),
                }))
                assert load["ok"] is True, f"load failed: {load.get('error')}"
                res = unwrap(await s.call_tool("change_building_location", {
                    "weather_file": "/opt/comstock-measures/ChangeBuildingLocation"
                                    "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw",
                }))
                assert res["ok"] is True, f"change_building_location failed: {res.get('error')}"
                weather = unwrap(await s.call_tool("get_weather_info", {}))
                assert weather["ok"] is True
                assert "Boston" in weather["weather_file"]["url"], (
                    f"Measure's weather clobbered by restore: {weather['weather_file']}"
                )
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_staged_url_portable_and_rerunnable():
    """After a weather-setting measure, url is portable and measures re-run."""
    # Regression: issue #97 investigation — the runner writes the staged
    # absolute EPW path into the output model; the next apply_measure passed
    # that other-run-dir path via OSW file_paths unstaged, and the confined
    # subprocess EACCESed (surfaced as a bogus "Windows path length" error
    # from the standards sizing-run rescue)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": "/opt/common-measures/ChangeBuildingLocation",
                    "arguments": {
                        "weather_file_name":
                            "/opt/comstock-measures/ChangeBuildingLocation"
                            "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw",
                    },
                }))
                assert res["ok"] is True, f"CBL failed: {res.get('error')}"
                weather = unwrap(await s.call_tool("get_weather_info", {}))
                assert weather["weather_file"]["url"] == \
                    "USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw", (
                    "known EPW should be relativized to the portable bare name, "
                    f"got {weather['weather_file']['url']}"
                )
                # Re-running any measure on this model must work
                res2 = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                    "arguments": {"building_name": "Rerun OK"},
                }))
                assert res2["ok"] is True, \
                    f"second measure failed after weather set: {res2.get('error')}"
    asyncio.run(_run())


@pytest.mark.integration
def test_apply_measure_custom_epw_stays_absolute_and_rerunnable():
    """Custom EPW (basename in no search dir) keeps absolute url; re-runs work."""
    # Regression: issue #97 investigation — resolve_osw_weather tier 1 passed
    # an absolute own-run url via file_paths without staging (sandbox denies
    # other run dirs); and relativizing an unfindable basename would strand
    # the model's weather reference entirely
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                import shutil
                custom = f"MyCustom_{uuid.uuid4().hex[:8]}"
                wdir = Path(f"/runs/{_unique('custom_epw')}")
                wdir.mkdir(parents=True)
                src = Path("/opt/comstock-measures/ChangeBuildingLocation"
                           "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3")
                for ext in (".epw", ".ddy", ".stat"):
                    shutil.copy2(f"{src}{ext}", str(wdir / f"{custom}{ext}"))

                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": "/opt/common-measures/ChangeBuildingLocation",
                    "arguments": {"weather_file_name": str(wdir / f"{custom}.epw")},
                }))
                assert res["ok"] is True, f"CBL failed: {res.get('error')}"
                weather = unwrap(await s.call_tool("get_weather_info", {}))
                url = weather["weather_file"]["url"]
                assert url.endswith(f"files/{custom}.epw") and url.startswith("/"), (
                    "unfindable custom EPW must keep a resolvable absolute url, "
                    f"got {url}"
                )
                res2 = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                    "arguments": {"building_name": "Custom EPW Rerun"},
                }))
                assert res2["ok"] is True, \
                    f"second measure failed with custom EPW url: {res2.get('error')}"
    asyncio.run(_run())


def test_portable_url_failure_never_fails_measure(monkeypatch):
    """A raise in the portable-url post-step must not flip ok to False."""
    # Regression: PR #108 review — apply_measure's outer except would catch a
    # RuntimeError from the portable-url cleanup and report the whole
    # (successful, reloaded) measure run as failed
    from mcp_server.skills.measures import operations as ops

    def _boom(model):
        raise RuntimeError("weatherFile exploded")

    monkeypatch.setattr(ops, "make_weather_url_portable", _boom)
    monkeypatch.setattr(ops, "get_model", object)
    result = {"ok": True}
    ops._attach_portable_weather_url(result)
    assert result["ok"] is True
    assert result["weather_url_error"] == "weatherFile exploded"
    assert "weather_url" not in result


@pytest.mark.integration
def test_apply_measure_verify_model_changed():
    """Verify model state changed after measure application."""
    # Validates: apply_measure mutates in-memory model (building name changes)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, _unique())
                # Get original building name
                bldg_before = unwrap(await s.call_tool("get_building_info", {}))
                original_name = bldg_before["building"]["name"]
                # Apply measure with different name
                new_name = f"Changed_{uuid.uuid4().hex[:6]}"
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                    "arguments": {"building_name": new_name},
                }))
                assert res["ok"] is True
                # Verify changed
                bldg_after = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg_after["building"]["name"] == new_name
                assert bldg_after["building"]["name"] != original_name
    asyncio.run(_run())
