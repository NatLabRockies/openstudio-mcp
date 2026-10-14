"""Integration tests for measures tools (Phase 6D).

Tests list_measure_arguments, apply_measure.
Uses a minimal test measure at tests/assets/measures/set_building_name/.
"""
import asyncio
import uuid
from pathlib import Path

import pytest
from conftest import (
    EPW_PATH,
    integration_enabled,
    poll_until_done,
    server_params,
    setup_example,
    unwrap,
)
from mcp import ClientSession
from mcp.client.stdio import stdio_client


def _unique(prefix: str = "pytest_measures") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# Measure path inside container (repo mounted at /repo)
MEASURE_DIR = "/repo/tests/assets/measures/set_building_name"
RESOURCE_MEASURE_DIR = "/repo/tests/assets/measures/read_resource_file"
GENERATED_MEASURE_DIR = "/repo/tests/assets/measures/write_generated_file"

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


@pytest.mark.integration
def test_bare_save_after_measure_writes_users_file():
    # Regression: apply_measure reloaded the session model from <run_dir>/run/in.osm and a
    # no-arg save_osm_model wrote there, leaving the user's file untouched (issue #195)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                cr = unwrap(await s.call_tool("create_example_osm", {"name": _unique()}))
                assert cr["ok"] is True, cr
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
                assert lr["ok"] is True, lr
                user_osm = lr["osm_path"]

                new_name = f"Saved_{uuid.uuid4().hex[:6]}"
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": MEASURE_DIR,
                    "arguments": {"building_name": new_name},
                }))
                assert res["ok"] is True, res

                saved = unwrap(await s.call_tool("save_osm_model", {}))
                assert saved["ok"] is True, saved
                assert saved["osm_path"] == user_osm, (
                    f"bare save must target the file the user loaded, not the measure run dir: {saved}")

                reloaded = unwrap(await s.call_tool("load_osm_model", {"osm_path": user_osm}))
                assert reloaded["ok"] is True, reloaded
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg["building"]["name"] == new_name, (
                    "the user's file on disk must hold the measure result after a bare save")
    asyncio.run(_run())


@pytest.mark.integration
def test_measure_can_read_model_resource_file():
    # Regression: apply_measure never put the model's companion files/ on the measure
    # workflow's file search paths, so a measure calling workflow.findFile on a model
    # resource (EMS plugin script, Schedule:File CSV) could not find it (#195 follow-up)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                cr = unwrap(await s.call_tool("create_example_osm", {"name": _unique()}))
                assert cr["ok"] is True, cr
                osm = Path(cr["osm_path"])
                files_dir = osm.parent / osm.stem / "files"  # the model's companion folder
                files_dir.mkdir(parents=True, exist_ok=True)
                (files_dir / "note.txt").write_text("hello from files\n", encoding="utf-8")
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
                assert lr["ok"] is True, lr

                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": RESOURCE_MEASURE_DIR,
                    "arguments": {"file_name": "note.txt"},
                }))
                assert res["ok"] is True, f"measure must find the model's files/ resource: {res}"
                bldg = unwrap(await s.call_tool("get_building_info", {}))
                assert bldg["building"]["name"] == "resource:hello from files", bldg
    asyncio.run(_run())


@pytest.mark.integration
def test_generated_file_persists_on_save_and_simulates():
    # Validates: a file a measure generates (the CLI's generated_files/) is kept in the
    # session workspace, written next to the model on save, and resolved from there by
    # run_simulation: the Application's Apply-Measure-Now copy-back, persisted on Save
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("pytest_generated")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, name)
                rp = unwrap(await s.call_tool("set_run_period", {
                    "begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 2,
                }))
                assert rp["ok"] is True, rp

                # Unique name: save_name models share one models/files/ dir, so a copy
                # left by an earlier run must not be able to satisfy the checks below
                csv_name = f"{name}.csv"
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": GENERATED_MEASURE_DIR,
                    "arguments": {"file_name": csv_name},
                }))
                assert res["ok"] is True, res
                assert res["generated_files"] == [csv_name], (
                    f"apply_measure must report the file the measure generated: {res}")

                saved = unwrap(await s.call_tool("save_osm_model", {"save_name": name}))
                assert saved["ok"] is True, saved
                saved_osm = Path(saved["osm_path"])
                csv = saved_osm.parent / saved_osm.stem / "files" / csv_name
                assert saved["persisted_files"] == [csv_name], saved
                assert csv.is_file(), f"generated file must be persisted next to the saved model: {saved}"
                assert saved["files_dir"] == str(csv.parent), saved
                assert csv.read_text(encoding="utf-8").splitlines()[8] == "1", (
                    "persisted CSV must be the measure's content (hour 8 is occupied)")

                sim = unwrap(await s.call_tool("run_simulation", {
                    "osm_path": saved["osm_path"], "epw_path": EPW_PATH,
                }))
                assert sim["ok"] is True, sim
                status = await poll_until_done(s, sim["run_id"])
                assert status["run"]["status"].lower() == "success", (
                    f"simulation must resolve the Schedule:File CSV from files/: {status}")
    asyncio.run(_run())


async def _target_dir(name: str) -> Path:
    """A dir the test owns, holding a file a planted link could point at."""
    d = Path(f"/runs/{name}_target")
    d.mkdir(parents=True, exist_ok=True)
    (d / "private.txt").write_text("not for the model\n", encoding="utf-8")
    return d


@pytest.mark.integration
def test_link_left_in_generated_files_is_not_adopted():
    # Validates: a link a measure leaves in generated_files/ is neither adopted nor
    # persisted; the real generated file still is (end to end through the CLI run)
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("pytest_genlink")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, name)
                target = await _target_dir(name)
                csv_name = f"{name}.csv"
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": GENERATED_MEASURE_DIR,
                    "arguments": {"file_name": csv_name,
                                  "link_file_to": str(target / "private.txt")},
                }))
                assert res["ok"] is True, res
                assert res["generated_files"] == [csv_name], (
                    f"the planted link must not be adopted: {res}")
                saved = unwrap(await s.call_tool("save_osm_model", {"save_name": name}))
                assert saved["ok"] is True, saved
                assert saved["persisted_files"] == [csv_name], saved
                saved_osm = Path(saved["osm_path"])
                files_dir = saved_osm.parent / saved_osm.stem / "files"
                assert not (files_dir / "linked.txt").exists(), "the link must not reach files/"
    asyncio.run(_run())


@pytest.mark.integration
def test_generated_files_replaced_by_a_link_refuses_the_result():
    # Validates: when the measure leaves generated_files/ as a link to another directory,
    # apply_measure refuses the result (model not adopted, output path reported) and
    # nothing from the link's target reaches the session or a later save
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("pytest_gendirlink")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, name)
                before = unwrap(await s.call_tool("get_building_info", {}))["building"]["name"]
                target = await _target_dir(name)
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": GENERATED_MEASURE_DIR,
                    "arguments": {"file_name": f"{name}.csv", "link_dir_to": str(target)},
                }))
                assert res["ok"] is False, res
                assert "generated_files" in res["error"] and "not adopted" in res["error"], res
                assert res["output_osm"].endswith("/run/in.osm"), res

                # The session model was not replaced and holds nothing from the target
                after = unwrap(await s.call_tool("get_building_info", {}))["building"]["name"]
                assert after == before
                saved = unwrap(await s.call_tool("save_osm_model", {"save_name": name}))
                assert saved["ok"] is True, saved
                assert "persisted_files" not in saved, saved
                saved_osm = Path(saved["osm_path"])
                assert not (saved_osm.parent / saved_osm.stem / "files" / "private.txt").exists()
    asyncio.run(_run())


@pytest.mark.integration
def test_save_never_persists_through_a_link_at_the_destination():
    # Validates: a link planted at files/<generated name> before the save is skipped and
    # reported, its target is untouched, and a link planted at files/ itself makes the
    # save refuse to persist (model written, resources not)
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("pytest_dstlink")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                cr = unwrap(await s.call_tool("create_example_osm", {"name": name}))
                assert cr["ok"] is True, cr
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": cr["osm_path"]}))
                assert lr["ok"] is True, lr
                model_dir = Path(lr["osm_path"]).parent
                target = await _target_dir(name)
                csv_name = f"{name}.csv"

                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": GENERATED_MEASURE_DIR,
                    "arguments": {"file_name": csv_name},
                }))
                assert res["ok"] is True, res

                # Link at the destination file name, inside the model's companion folder
                files_dir = model_dir / Path(lr["osm_path"]).stem / "files"
                files_dir.mkdir(parents=True, exist_ok=True)
                (files_dir / csv_name).symlink_to(target / "private.txt")
                saved = unwrap(await s.call_tool("save_osm_model", {}))
                assert saved["ok"] is True, saved
                assert saved.get("skipped_files") == [csv_name], saved
                assert "persisted_files" not in saved, saved
                assert (target / "private.txt").read_text(encoding="utf-8") == "not for the model\n"

                # Link at files/ itself: the pending file is still waiting, the save refuses
                (files_dir / csv_name).unlink()
                files_dir.rmdir()
                files_dir.symlink_to(target, target_is_directory=True)
                saved2 = unwrap(await s.call_tool("save_osm_model", {}))
                assert saved2["ok"] is False, saved2
                assert "is a symlink" in saved2["error"], saved2
                assert not (target / csv_name).exists(), "nothing may be written through files/"

                # Link at the companion folder itself: same refusal, nothing written through
                files_dir.unlink()
                companion = files_dir.parent
                companion.rmdir()
                companion.symlink_to(target, target_is_directory=True)
                saved3 = unwrap(await s.call_tool("save_osm_model", {}))
                assert saved3["ok"] is False, saved3
                assert "is a symlink" in saved3["error"], saved3
                assert not (target / "files").exists(), "nothing may be created through the companion link"
    asyncio.run(_run())
