"""run_simulation weather fail-fast + extract_summary_metrics failed-run guard.

Found via the LLM benchmark rework: an annual sim launched without a weather
file died in EnergyPlus within ~1s, while extract_summary_metrics answered
ok:true with all-null metrics — agents reported success on failed runs.
"""
import asyncio
import uuid
from pathlib import Path

import pytest
from conftest import integration_enabled, poll_until_done, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

EPW = ("/opt/comstock-measures/ChangeBuildingLocation"
       "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")


def _unique(prefix: str = "pytest_wxguard") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.mark.integration
def test_run_simulation_fails_fast_without_weather():
    """Annual sim on a weatherless model must refuse to launch, with guidance."""
    # Regression: weatherless run_simulation launched, died in ~1s in
    # EnergyPlus, and callers had to poll get_run_status to notice at all
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                cr = unwrap(await s.call_tool("create_baseline_osm", {"name": _unique()}))
                assert cr["ok"] is True, f"create_baseline_osm failed: {cr.get('error')}"

                sim = unwrap(await s.call_tool("run_simulation", {"osm_path": cr["osm_path"]}))
                assert sim["ok"] is False, (
                    f"weatherless annual sim must not launch, got: {sim}"
                )
                assert "no weather file" in sim["error"].lower(), sim["error"]
                assert "change_building_location" in sim["error"], (
                    f"error must point at the fix: {sim['error']}"
                )

    asyncio.run(_run())


@pytest.mark.integration
def test_run_simulation_allows_design_day_only_without_weather():
    """DD-only models (weather-file run periods off) may launch without an EPW."""
    # Validates: the weather fail-fast only blocks annual sims — sizing-only
    # workflows legitimately run without a weather file
    if not integration_enabled():
        pytest.skip("integration disabled")

    # SimulationControl is a unique object without list/set tool support, so
    # the DD-only fixture model is built directly with the SDK (fixture
    # construction, not mocking — the behavior under test is run_simulation).
    import openstudio
    model = openstudio.model.exampleModel()
    wf = model.getOptionalWeatherFile()
    if wf.is_initialized():
        wf.get().remove()
    model.getSimulationControl().setRunSimulationforWeatherFileRunPeriods(False)
    osm_path = f"/runs/{_unique('ddonly')}.osm"
    assert model.save(osm_path, True), f"fixture save failed: {osm_path}"

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                sim = unwrap(await s.call_tool("run_simulation", {"osm_path": osm_path}))
                assert sim["ok"] is True, (
                    f"DD-only sim must be allowed to launch without EPW: {sim.get('error')}"
                )
                # Let it reach a terminal state so nothing lingers; outcome of
                # the DD-only run itself is not this test's contract.
                await poll_until_done(s, sim["run_id"])

    asyncio.run(_run())


@pytest.mark.integration
def test_extract_summary_metrics_failed_run_reports_failure():
    """Extraction on a failed run must be ok:false, not all-null 'success'."""
    # Regression: extract_summary_metrics on a failed run returned ok:true
    # with null metrics and an empty warnings list — agents reported success
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                # A corrupt seed passes launch validation (weather resolution
                # defers on unloadable OSMs) and fails at the CLI load step —
                # the cheapest deterministic way to mint a genuinely failed run.
                bad_osm = Path(f"/runs/{_unique('corrupt')}.osm")
                bad_osm.write_text("this is not an OpenStudio model\n", encoding="utf-8")

                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": str(bad_osm), "epw_path": EPW,
                }))
                assert sim["ok"] is True, f"corrupt-seed run failed to launch: {sim}"
                status = await poll_until_done(s, sim["run_id"])
                assert status["run"]["status"] == "failed", (
                    f"corrupt seed should produce a failed run, got: {status}"
                )

                metrics = unwrap(await s.call_tool("extract_summary_metrics", {
                    "run_id": sim["run_id"],
                }))
                assert metrics["ok"] is False, (
                    f"extraction on a failed run must not report success: {metrics}"
                )
                assert metrics["status"] == "failed"
                assert "failed" in metrics["error"].lower()
                assert "extract_simulation_errors" in metrics["error"], (
                    f"error must point at diagnosis tools: {metrics['error']}"
                )

    asyncio.run(_run())


@pytest.mark.integration
def test_gem_weather_epws_pass_the_epw_gate():
    """Every EPW list_weather_files advertises must be usable downstream."""
    # Regression: list_weather_files listed openstudio-standards gem EPWs
    # (/var/oscli/...) that _SHARED_READ_ROOTS did not cover, so
    # change_building_location rejected the server's own suggestions with
    # "EPW path not allowed" (#121, found live by the nodiscovery smoke)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                listing = unwrap(await s.call_tool("list_weather_files", {}))
                assert listing["ok"] is True
                gem_epws = [f for f in listing["weather_files"]
                            if "/openstudio-standards-" in f["path"]]
                assert len(gem_epws) >= 50, (
                    f"gem weather dir should list dozens of EPWs, got {len(gem_epws)}"
                )
                target = next(f for f in gem_epws if f["has_ddy"] and f["has_stat"])
                res = unwrap(await s.call_tool("create_new_building", {
                    "building_type": "SmallOffice",
                    "total_bldg_floor_area": 10000,
                    "num_stories_above_grade": 1,
                    "weather_file": target["path"],
                }))
                assert res["ok"] is True, (
                    f"advertised gem EPW {target['path']} must be accepted: "
                    f"{res.get('error')}"
                )

    asyncio.run(_run())


@pytest.mark.integration
def test_companion_epw_symlink_escaping_allowlist_is_rejected(tmp_path, monkeypatch):
    # Regression: the companion-dir weather lookup returned candidate.resolve()
    # without re-gating, so a symlink files/weather.epw -> /outside/secret.epw
    # would stage another tenant's / host file into the caller's run dir.
    if not integration_enabled():
        pytest.skip("integration disabled")
    from mcp_server.skills.weather.operations import _staged_epw_by_basename

    # osm_dir lives INSIDE the caller's allowed run root
    run_root = tmp_path / "runs" / "user"
    osm_dir = run_root / "model"
    (osm_dir / "files").mkdir(parents=True)
    monkeypatch.setattr("mcp_server.config.user_run_root", lambda: run_root)

    # target sits OUTSIDE every allowed root
    outside = tmp_path / "other_tenant"
    outside.mkdir()
    secret = outside / "secret.epw"
    secret.write_text("another tenant's weather data")

    link = osm_dir / "files" / "weather.epw"
    link.symlink_to(secret)
    assert link.is_file(), "symlink must resolve to the real target for the test"

    got = _staged_epw_by_basename(osm_dir, "weather.epw")
    assert got is None, f"escaping companion symlink must be rejected, got {got}"

    # Control: a REAL companion EPW under the allowed run root is accepted
    real = osm_dir / "files" / "local.epw"
    real.write_text("legitimate companion weather")
    got_real = _staged_epw_by_basename(osm_dir, "local.epw")
    assert got_real == real.resolve(), (
        f"real companion EPW under the run root must be staged, got {got_real}"
    )
