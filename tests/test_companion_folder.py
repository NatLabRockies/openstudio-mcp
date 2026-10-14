"""A model's resources live in its companion folder <dir>/<model>/files/, the OpenStudio
Application layout (SDK getCompanionFolder). Covers: no sharing between models saved into
one directory, legacy sibling files/ read and migrated forward, the Application-layout
fixture driven through run_simulation, retention leaving companion folders alone, the
model's own weather winning over a same-named global EPW, and edge names.
"""
import asyncio
import shutil
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

pytestmark = pytest.mark.integration

GENERATED_MEASURE_DIR = "/repo/tests/assets/measures/write_generated_file"
NAME_MEASURE_DIR = "/repo/tests/assets/measures/set_building_name"
SEB4_OSM = "/repo/tests/assets/SEB_model/SEB4_baseboard.osm"
BALTIMORE_EPW_NAME = "USA_MD_Baltimore-Washington.Intl.AP.724060_TMY3.epw"


def _unique(prefix: str = "pytest_companion") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _companion_files(osm_path: str) -> Path:
    p = Path(osm_path)
    return p.parent / p.stem / "files"


def test_save_name_models_keep_separate_resources():
    # Regression: every save_name model lands in one models/ dir and shared a sibling
    # models/files/, so two models' same-named resources overwrote each other; each
    # model now owns <models>/<name>/files/ and consumes its own file in simulation
    if not integration_enabled():
        pytest.skip("integration disabled")
    name_a, name_b = _unique("colA"), _unique("colB")

    async def _one(s, name: str, csv_name: str, occupied: str) -> Path:
        await setup_example(s, name)
        rp = unwrap(await s.call_tool("set_run_period", {
            "begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 2,
        }))
        assert rp["ok"] is True, rp
        res = unwrap(await s.call_tool("apply_measure", {
            "measure_dir": GENERATED_MEASURE_DIR, "arguments": {"file_name": csv_name},
        }))
        assert res["ok"] is True, res
        saved = unwrap(await s.call_tool("save_osm_model", {"save_name": name}))
        assert saved["ok"] is True, saved
        csv = _companion_files(saved["osm_path"]) / csv_name
        assert csv.is_file(), saved
        # make the two models' files differ: stamp a marker into the first data row
        lines = csv.read_text(encoding="utf-8").splitlines()
        lines[0] = occupied
        csv.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return Path(saved["osm_path"])

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                csv_name = "schedule.csv"  # deliberately the same name for both models
                osm_a = await _one(s, name_a, csv_name, "0.25")
                osm_b = await _one(s, name_b, csv_name, "0.75")

                a_csv = _companion_files(str(osm_a)) / csv_name
                b_csv = _companion_files(str(osm_b)) / csv_name
                assert a_csv.parent != b_csv.parent
                assert a_csv.read_text(encoding="utf-8").splitlines()[0] == "0.25", (
                    "model B's save must not have touched model A's resource")
                assert b_csv.read_text(encoding="utf-8").splitlines()[0] == "0.75"
                assert not (osm_a.parent / "files").exists(), "no shared sibling files/ any more"

                # Each model simulates with its own CSV
                for osm in (osm_a, osm_b):
                    sim = unwrap(await s.call_tool("run_simulation", {
                        "osm_path": str(osm), "epw_path": EPW_PATH,
                    }))
                    assert sim["ok"] is True, sim
                    status = await poll_until_done(s, sim["run_id"])
                    assert status["run"]["status"].lower() == "success", status
                    staged = Path(status["run"]["run_dir"]) / "files" / csv_name
                    assert staged.read_text(encoding="utf-8").splitlines()[0] == (
                        "0.25" if osm == osm_a else "0.75"), f"wrong CSV staged for {osm}"
    asyncio.run(_run())


def test_legacy_sibling_files_are_read_and_migrated_on_save():
    # Validates: a model saved before the companion folder (resources in a sibling files/)
    # still resolves its plugin, and its first save copies the resources into the companion
    # folder (reported as migrated_files) without touching the sibling dir
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("legacy")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, name)
                created = unwrap(await s.call_tool("create_python_plugin", {
                    "name": "Legacy Metric", "template": "zone_metric_aggregate",
                    "aggregation": "volume_weighted_average",
                }))
                assert created["ok"] is True, created
                saved = unwrap(await s.call_tool("save_osm_model", {"osm_path": f"/runs/{name}/model.osm"}))
                assert saved["ok"] is True, saved
                companion = _companion_files(saved["osm_path"])
                assert (companion / "legacy_metric.py").is_file()

                # Rebuild the pre-companion layout by hand: sibling files/, no companion folder
                legacy = Path(f"/runs/{name}/files")
                shutil.move(str(companion), str(legacy))
                companion.parent.rmdir()
                assert not companion.exists() and (legacy / "legacy_metric.py").is_file()

                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": saved["osm_path"]}))
                assert lr["ok"] is True, lr
                plugin = unwrap(await s.call_tool("get_python_plugin", {"name": "Legacy Metric"}))
                assert plugin["ok"] is True, plugin
                assert plugin["plugin"]["script_path"] == str(legacy / "legacy_metric.py"), (
                    "a legacy sibling files/ must still be read")
                assert "class ZoneMetricAggregate" in plugin["source"]

                # An edit goes to the companion folder; the legacy copy is left alone
                source = plugin["source"].replace("ZoneMetricAggregate(EnergyPlusPlugin):",
                                                  "ZoneMetricAggregate(EnergyPlusPlugin):  # edited")
                edited = unwrap(await s.call_tool("edit_python_plugin", {"name": "Legacy Metric", "code": source}))
                assert edited["ok"] is True, edited
                assert "# edited" in (companion / "legacy_metric.py").read_text(encoding="utf-8")
                assert "# edited" not in (legacy / "legacy_metric.py").read_text(encoding="utf-8")
                after = unwrap(await s.call_tool("get_python_plugin", {"name": "Legacy Metric"}))
                assert after["plugin"]["script_path"] == str(companion / "legacy_metric.py"), (
                    "the companion copy wins once it exists")

                # A bare save migrates the remaining legacy resources forward
                (legacy / "extra.csv").write_text("1\n", encoding="utf-8")
                bare = unwrap(await s.call_tool("save_osm_model", {}))
                assert bare["ok"] is True, bare
                assert bare["migrated_files"] == ["extra.csv"], bare
                assert bare["files_dir"] == str(companion)
                assert (companion / "extra.csv").is_file()
                assert (legacy / "extra.csv").is_file(), "the legacy dir is never modified"
                assert "# edited" in (companion / "legacy_metric.py").read_text(encoding="utf-8"), (
                    "migration must never overwrite a companion file with the legacy copy")
    asyncio.run(_run())


def test_application_layout_fixture_simulates_and_saves_from_read_only_root():
    # Validates: the SEB4 fixture already uses the Application layout (SEB4_baseboard.osm +
    # SEB4_baseboard/files/<epw>); run_simulation resolves the model's own EPW from its
    # companion folder, a read never creates dirs under /repo, and save_name carries the
    # resources into the caller's area
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("seb4")
    fixture_companion = Path("/repo/tests/assets/SEB_model/SEB4_baseboard")
    before = sorted(p.name for p in fixture_companion.iterdir())

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": SEB4_OSM}))
                assert lr["ok"] is True, lr
                rp = unwrap(await s.call_tool("set_run_period", {
                    "begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 2,
                }))
                assert rp["ok"] is True, rp
                saved = unwrap(await s.call_tool("save_osm_model", {"save_name": name}))
                assert saved["ok"] is True, saved
                companion = _companion_files(saved["osm_path"])
                assert saved["files_dir"] == str(companion), saved
                epws = sorted(p.name for p in companion.glob("*.epw"))
                assert "SRRL_2012AMY_60min.epw" in epws, f"the fixture's EPWs must travel: {epws}"

                sim = unwrap(await s.call_tool("run_simulation", {"osm_path": saved["osm_path"]}))
                assert sim["ok"] is True, sim
                status = await poll_until_done(s, sim["run_id"])
                assert status["run"]["status"].lower() == "success", status
                assert (Path(status["run"]["run_dir"]) / "files" / "SRRL_2012AMY_60min.epw").is_file(), (
                    "the model's own EPW must be staged from its companion folder")
    asyncio.run(_run())
    after = sorted(p.name for p in fixture_companion.iterdir())
    assert after == before, "reading a model must never write into its (read-only) companion folder"


def test_retention_never_deletes_a_companion_folder():
    # Regression: retention treated any top-level dir holding run/ as an old run; a model
    # saved as save_name="run" with a resource creates models/run/files/, which made the
    # whole models/ dir look like a run and deletable
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("ret")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, name)
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": GENERATED_MEASURE_DIR, "arguments": {"file_name": f"{name}.csv"},
                }))
                assert res["ok"] is True, res
                run_dir = Path(res["run_dir"])
                saved = unwrap(await s.call_tool("save_osm_model", {"save_name": "run"}))
                assert saved["ok"] is True, saved
                csv = _companion_files(saved["osm_path"]) / f"{name}.csv"
                assert csv.is_file() and csv.parent.parent.name == "run", csv

                # Sweeps every eligible run in this container's /runs (other tests'
                # finished runs included); only the saved model must survive
                swept = unwrap(await s.call_tool("cleanup_runs", {"older_than_days": 0, "dry_run": False}))
                assert swept["ok"] is True, swept
                assert not run_dir.exists(), f"the sweep must have run (measure run dir still there): {swept}"
                assert Path(saved["osm_path"]).is_file() and csv.is_file(), (
                    "models/ and the companion folder models/run/ must survive retention")
    asyncio.run(_run())


def test_model_own_epw_wins_over_same_named_global_epw():
    # Validates: a bare weather-file name in the model resolves to the EPW in the model's
    # companion folder before a same-named EPW in the known weather dirs, both for a
    # measure run (OSW weather staging) and for run_simulation
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("ownepw")
    model_dir = Path(f"/runs/{name}")
    model_dir.mkdir(parents=True, exist_ok=True)
    osm = model_dir / "m.osm"
    # SystemD_baseline references the Baltimore EPW by bare name; stamp a marker into the
    # companion copy so the staged bytes identify which file was used
    shutil.copy2("/repo/tests/assets/SystemD_baseline.osm", osm)
    from mcp_server.skills.weather.operations import find_epw_by_name
    source_epw = find_epw_by_name(BALTIMORE_EPW_NAME)
    assert source_epw is not None, "the Baltimore EPW must exist in a known weather dir"
    companion = _companion_files(str(osm))
    companion.mkdir(parents=True)
    marker = f"COMMENTS 2,companion-copy-{name}\n"
    lines = source_epw.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    (companion / BALTIMORE_EPW_NAME).write_text("".join(lines[:6]) + marker + "".join(lines[7:]), encoding="utf-8")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                lr = unwrap(await s.call_tool("load_osm_model", {"osm_path": str(osm)}))
                assert lr["ok"] is True, lr
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": NAME_MEASURE_DIR, "arguments": {"building_name": "own epw"},
                }))
                assert res["ok"] is True, res
                staged = Path(res["run_dir"]) / "files" / BALTIMORE_EPW_NAME
                assert marker.strip() in staged.read_text(encoding="utf-8", errors="replace"), (
                    "the measure run must use the model's own EPW, not the global one")

                rp = unwrap(await s.call_tool("set_run_period", {
                    "begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 2,
                }))
                assert rp["ok"] is True, rp
                saved = unwrap(await s.call_tool("save_osm_model", {}))
                assert saved["ok"] is True, saved
                sim = unwrap(await s.call_tool("run_simulation", {"osm_path": str(osm)}))
                assert sim["ok"] is True, sim
                status = await poll_until_done(s, sim["run_id"])
                assert status["run"]["status"].lower() == "success", status
                run_epw = Path(status["run"]["run_dir"]) / "files" / BALTIMORE_EPW_NAME
                assert marker.strip() in run_epw.read_text(encoding="utf-8", errors="replace"), (
                    "run_simulation must stage the model's own EPW")
    asyncio.run(_run())


def test_edge_names_resolve_through_the_sdk_and_refuse_nesting():
    # Validates: the companion folder comes from the SDK (model.v2.osm -> model.v2/files),
    # a regular file at <stem> is refused, and files.osm (companion inside a legacy
    # files/) is refused rather than copied into itself
    if not integration_enabled():
        pytest.skip("integration disabled")
    pytest.importorskip("openstudio")
    from mcp_server.resources import companion_files_dir, copy_resources, resource_dir_issue

    assert companion_files_dir("/x/y/model.v2.osm") == Path("/x/y/model.v2/files")
    assert companion_files_dir("/x/y/plain.osm") == Path("/x/y/plain/files")

    import tempfile
    with tempfile.TemporaryDirectory(dir="/runs") as tmp:
        d = Path(tmp)
        (d / "taken").write_text("not a dir\n", encoding="utf-8")
        issue = resource_dir_issue(companion_files_dir(d / "taken.osm"), write=True)
        assert issue is not None and "not a directory" in issue

        legacy = d / "files"
        legacy.mkdir()
        (legacy / "a.csv").write_text("1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="nest"):
            copy_resources([legacy], companion_files_dir(d / "files.osm"))
        assert not (legacy / "files").exists(), "nothing may be copied into the nested companion"


def test_save_as_over_an_existing_model_replaces_its_stale_resources():
    # Regression: a save-as onto a path whose previous model kept a same-named resource
    # left that stale file in place (copy never overwrote), so the OSM was model A but
    # the resource was still model B's; the source model's resources now replace them
    # and the replacement is reported
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("saveas_stale")
    target_osm = f"/runs/{name}/target.osm"

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # Model B: saved at the target with its own schedule.csv
                await setup_example(s, f"{name}_b")
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": GENERATED_MEASURE_DIR, "arguments": {"file_name": "schedule.csv"},
                }))
                assert res["ok"] is True, res
                saved_b = unwrap(await s.call_tool("save_osm_model", {"osm_path": target_osm}))
                assert saved_b["ok"] is True, saved_b
                stale = _companion_files(target_osm) / "schedule.csv"
                stale.write_text("B\n", encoding="utf-8")

                # Model A with a different schedule.csv, saved as the same target
                await setup_example(s, f"{name}_a")
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": GENERATED_MEASURE_DIR, "arguments": {"file_name": "schedule.csv"},
                }))
                assert res["ok"] is True, res
                saved_a = unwrap(await s.call_tool("save_osm_model", {"save_name": f"{name}_a"}))
                assert saved_a["ok"] is True, saved_a
                a_csv = _companion_files(saved_a["osm_path"]) / "schedule.csv"
                a_csv.write_text("A\n", encoding="utf-8")
                over = unwrap(await s.call_tool("save_osm_model", {"osm_path": target_osm}))
                assert over["ok"] is True, over
                assert over["replaced_files"] == ["schedule.csv"], over
                assert stale.read_text(encoding="utf-8") == "A\n", (
                    "the target's resource must be the source model's, not the previous model's")
    asyncio.run(_run())


def test_legacy_migration_completes_once():
    # Validates: after the first save migrated a legacy sibling files/, the sibling dir is
    # no longer consulted: a file added there later does not creep into the model, and a
    # resource deleted from the companion folder does not come back
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("migrate_once")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, name)
                saved = unwrap(await s.call_tool("save_osm_model", {"osm_path": f"/runs/{name}/model.osm"}))
                assert saved["ok"] is True, saved
                legacy = Path(f"/runs/{name}/files")
                legacy.mkdir()
                (legacy / "old.csv").write_text("old\n", encoding="utf-8")
                companion = _companion_files(saved["osm_path"])

                first = unwrap(await s.call_tool("save_osm_model", {}))
                assert first["ok"] is True, first
                assert first["migrated_files"] == ["old.csv"], first
                assert (companion / "old.csv").is_file()

                (legacy / "later.csv").write_text("later\n", encoding="utf-8")
                (companion / "old.csv").unlink()
                second = unwrap(await s.call_tool("save_osm_model", {}))
                assert second["ok"] is True, second
                assert "migrated_files" not in second, second
                assert not (companion / "later.csv").exists(), "a migrated model no longer reads the legacy dir"
                assert not (companion / "old.csv").exists(), "a deleted companion resource must not come back"
    asyncio.run(_run())


def test_oversize_resource_fails_staging_loudly():
    # Validates: a regular resource that cannot be copied (over the per-file budget) makes
    # the run refuse to stage instead of silently simulating without that resource
    if not integration_enabled():
        pytest.skip("integration disabled")
    from mcp_server.resources import MAX_RESOURCE_FILE_BYTES, stage_model_resources
    name = _unique("oversize")
    model_dir = Path(f"/runs/{name}")
    files = model_dir / "m" / "files"
    files.mkdir(parents=True)
    (model_dir / "m.osm").write_text("", encoding="utf-8")
    # A sparse file just over the real per-file budget: refused on its size, never read
    with (files / "big.csv").open("wb") as fh:
        fh.truncate(MAX_RESOURCE_FILE_BYTES + 1)
    (files / "small.csv").write_bytes(b"0,1\n" * 8)
    (files / "link.csv").symlink_to(files / "small.csv")
    err = stage_model_resources(model_dir / "m.osm", model_dir / "stage" / "files")
    assert err is not None and "big.csv" in err and "exceeds" in err, err
    assert "link.csv" not in err, "a skipped link is not an error, only a regular file that failed"
    (files / "big.csv").unlink()
    err_ok = stage_model_resources(model_dir / "m.osm", model_dir / "stage2" / "files")
    assert err_ok is None
    assert (model_dir / "stage2" / "files" / "small.csv").read_bytes() == b"0,1\n" * 8
    assert not (model_dir / "stage2" / "files" / "link.csv").exists()


def test_explicit_osw_weather_beats_the_seed_companion_epw():
    # Validates: run_osw stages the seed's companion resources behind the OSW's own
    # weather staging, so an explicit weather_file with the same basename as an EPW in
    # the seed's companion folder keeps its own bytes
    if not integration_enabled():
        pytest.skip("integration disabled")
    from mcp_server.skills.weather.operations import find_epw_by_name
    name = _unique("oswepw")
    base = Path(f"/runs/{name}")
    base.mkdir(parents=True)
    shutil.copy2("/repo/tests/assets/SystemD_baseline.osm", base / "seed.osm")
    source_epw = find_epw_by_name(BALTIMORE_EPW_NAME)
    assert source_epw is not None
    lines = source_epw.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

    def variant(tag: str) -> str:
        return "".join(lines[:6]) + f"COMMENTS 2,{tag}-{name}\n" + "".join(lines[7:])

    companion = base / "seed" / "files"
    companion.mkdir(parents=True)
    (companion / BALTIMORE_EPW_NAME).write_text(variant("companion"), encoding="utf-8")
    # Outside the OSW dir: an in-dir file is mirrored as is, an external one is
    # staged into the run's files/, which is where a companion copy could clash
    explicit_dir = Path(f"/runs/{name}_explicit")
    explicit_dir.mkdir()
    (explicit_dir / BALTIMORE_EPW_NAME).write_text(variant("explicit"), encoding="utf-8")
    import json
    osw = base / "workflow.osw"
    osw.write_text(json.dumps({
        "seed_file": "seed.osm",
        "weather_file": str(explicit_dir / BALTIMORE_EPW_NAME),
        "steps": [],
    }), encoding="utf-8")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                run = unwrap(await s.call_tool("run_osw", {"osw_path": str(osw)}))
                assert run["ok"] is True, run
                status = unwrap(await s.call_tool("get_run_status", {"run_id": run["run_id"]}))
                run_dir = Path(status["run"]["run_dir"])
                staged = run_dir / "files" / BALTIMORE_EPW_NAME
                assert f"explicit-{name}" in staged.read_text(encoding="utf-8", errors="replace"), (
                    "the OSW's explicit weather file must not be replaced by the seed companion's copy")
                unwrap(await s.call_tool("cancel_run", {"run_id": run["run_id"]}))
    asyncio.run(_run())


def test_explicit_osw_weather_beats_a_mirrored_companion_epw():
    # Regression: an OSW that lives inside the seed's companion folder (the Application
    # writes workflow.osw there) mirrors that folder's files/X.epw into the run before the
    # OSW's explicit external X.epw was staged, and the staging refused to replace it, so
    # the run used the stale companion EPW
    if not integration_enabled():
        pytest.skip("integration disabled")
    from mcp_server.skills.weather.operations import find_epw_by_name
    name = _unique("mirrorepw")
    base = Path(f"/runs/{name}")
    companion = base / "seed"
    (companion / "files").mkdir(parents=True)
    shutil.copy2("/repo/tests/assets/SystemD_baseline.osm", base / "seed.osm")
    source_epw = find_epw_by_name(BALTIMORE_EPW_NAME)
    assert source_epw is not None
    lines = source_epw.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)

    def variant(tag: str) -> str:
        return "".join(lines[:6]) + f"COMMENTS 2,{tag}-{name}\n" + "".join(lines[7:])

    (companion / "files" / BALTIMORE_EPW_NAME).write_text(variant("companion"), encoding="utf-8")
    explicit_dir = Path(f"/runs/{name}_explicit")
    explicit_dir.mkdir()
    (explicit_dir / BALTIMORE_EPW_NAME).write_text(variant("explicit"), encoding="utf-8")
    import json
    osw = companion / "workflow.osw"  # inside the companion folder, like the Application
    osw.write_text(json.dumps({
        "seed_file": "../seed.osm",
        "weather_file": str(explicit_dir / BALTIMORE_EPW_NAME),
        "steps": [],
    }), encoding="utf-8")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                run = unwrap(await s.call_tool("run_osw", {"osw_path": str(osw)}))
                assert run["ok"] is True, run
                status = unwrap(await s.call_tool("get_run_status", {"run_id": run["run_id"]}))
                run_dir = Path(status["run"]["run_dir"])
                staged = run_dir / "files" / BALTIMORE_EPW_NAME
                assert f"explicit-{name}" in staged.read_text(encoding="utf-8", errors="replace"), (
                    "the OSW's explicit weather must replace the mirrored companion copy")
                staged_osw = json.loads((run_dir / "workflow.osw").read_text(encoding="utf-8"))
                assert staged_osw["weather_file"] == str(staged), staged_osw
                unwrap(await s.call_tool("cancel_run", {"run_id": run["run_id"]}))
    asyncio.run(_run())


def test_save_as_carries_migration_state_and_nested_resources():
    # Validates: a save-as of a migrated model marks the copy migrated too (its legacy dir
    # is not consulted, so a resource deleted from the companion folder stays deleted),
    # and a nested resource (a plugin's helper package) travels with the model
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("saveas_state")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, name)
                original = f"/runs/{name}/model.osm"
                saved = unwrap(await s.call_tool("save_osm_model", {"osm_path": original}))
                assert saved["ok"] is True, saved
                legacy = Path(f"/runs/{name}/files")
                legacy.mkdir()
                (legacy / "old.csv").write_text("old\n", encoding="utf-8")
                (legacy / "helpers").mkdir()
                (legacy / "helpers" / "util.py").write_text("X = 1\n", encoding="utf-8")
                companion = _companion_files(original)

                migrated = unwrap(await s.call_tool("save_osm_model", {}))
                assert migrated["ok"] is True, migrated
                assert sorted(migrated["migrated_files"]) == ["helpers/util.py", "old.csv"], migrated
                assert (companion / "helpers" / "util.py").read_text(encoding="utf-8") == "X = 1\n"
                assert (companion.parent / ".resources-migrated").is_file()

                (companion / "old.csv").unlink()
                copy_path = f"/runs/{name}_copy/model.osm"
                copied = unwrap(await s.call_tool("save_osm_model", {"osm_path": copy_path}))
                assert copied["ok"] is True, copied
                copy_files = _companion_files(copy_path)
                assert (copy_files.parent / ".resources-migrated").is_file(), (
                    "a save-as must carry the completed-migration state")
                assert not (copy_files / "old.csv").exists(), (
                    "the copy must not resurrect a resource deleted from the source's companion folder")
                assert (copy_files / "helpers" / "util.py").is_file(), "nested resources travel"
                assert not (copy_files / ".resources-migrated").exists(), "the marker never enters files/"

                # And the nested resource is staged for a run too
                sim = unwrap(await s.call_tool("run_simulation", {"osm_path": copy_path, "epw_path": EPW_PATH}))
                assert sim["ok"] is True, sim
                status = unwrap(await s.call_tool("get_run_status", {"run_id": sim["run_id"]}))
                run_dir = Path(status["run"]["run_dir"])
                assert (run_dir / "files" / "helpers" / "util.py").is_file(), "nested resources are staged"
                unwrap(await s.call_tool("cancel_run", {"run_id": sim["run_id"]}))
    asyncio.run(_run())


def test_migration_marker_is_never_written_through_a_link():
    # Validates: a link planted at the marker's name in the companion folder is neither
    # honoured as "migrated" nor written through; the save reports the refusal and the
    # link's target keeps its content
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("marker_link")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, name)
                original = f"/runs/{name}/model.osm"
                saved = unwrap(await s.call_tool("save_osm_model", {"osm_path": original}))
                assert saved["ok"] is True, saved
                legacy = Path(f"/runs/{name}/files")
                legacy.mkdir()
                (legacy / "old.csv").write_text("old\n", encoding="utf-8")
                victim = Path(f"/runs/{name}_victim.txt")
                victim.write_text("untouched\n", encoding="utf-8")
                companion = _companion_files(original)
                companion.parent.mkdir(parents=True, exist_ok=True)
                (companion.parent / ".resources-migrated").symlink_to(victim)

                res = unwrap(await s.call_tool("save_osm_model", {}))
                assert res["ok"] is False, res
                assert "migration marker" in res["error"], res
                assert victim.read_text(encoding="utf-8") == "untouched\n"
                assert (companion / "old.csv").is_file(), "the resources themselves were still carried"
                # a link at the marker never counts as migrated: the legacy dir is still read
                plugin_free = unwrap(await s.call_tool("get_python_plugin", {}))
                assert plugin_free["ok"] is True, plugin_free
    asyncio.run(_run())

