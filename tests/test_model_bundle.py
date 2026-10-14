"""A model's resources travel with it when it leaves its directory (issue #198).

The OpenStudio Application's unit of "a model" is the OSM plus its companion folder
(`<dir>/<stem>/files/`). Covers: `request_download(path=<osm>, bundle=True)` zipping
that unit, `copy_file` writing the companion beside the copy, `test_measure` and
actuator discovery seeing the model's resources, and the pure companion-folder rule
matching the SDK's.
"""
import asyncio
import io
import uuid
import zipfile
from pathlib import Path

import httpx
import pytest
from conftest import (
    EPW_PATH,
    http_server,
    http_session,
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
CSV = "schedule.csv"

RUBY_FIND = (
    '    found = runner.workflow.findFile("schedule.csv")\n'
    '    if found.empty?\n'
    '      runner.registerError("schedule.csv not found; searched #{runner.workflow.absoluteFilePaths.map(&:to_s)}")\n'
    '      return false\n'
    '    end\n'
    '    runner.registerInfo("found #{found.get}")'
)
PYTHON_FIND = (
    '        found = runner.workflow().findFile(openstudio.toPath("schedule.csv"))\n'
    '        if not found.is_initialized():\n'
    '            runner.registerError("schedule.csv not found")\n'
    '            return False\n'
    '        runner.registerInfo(f"found {found.get()}")'
)


def _unique(prefix: str = "pytest_bundle") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _companion_files(osm_path: str | Path) -> Path:
    p = Path(osm_path)
    return p.parent / p.stem / "files"


def _base(url: str) -> str:
    return url[: -len("/mcp")] if url.endswith("/mcp") else url


async def _model_with_resource(s, name: str) -> str:
    """Example model, a measure-generated schedule.csv, saved under models/<name>.osm."""
    await setup_example(s, name)
    rp = unwrap(await s.call_tool("set_run_period", {
        "begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 2,
    }))
    assert rp["ok"] is True, rp
    res = unwrap(await s.call_tool("apply_measure", {
        "measure_dir": GENERATED_MEASURE_DIR, "arguments": {"file_name": CSV},
    }))
    assert res["ok"] is True, res
    saved = unwrap(await s.call_tool("save_osm_model", {"save_name": name}))
    assert saved["ok"] is True, saved
    assert (_companion_files(saved["osm_path"]) / CSV).is_file(), saved
    return saved["osm_path"]


def test_companion_folder_rule_matches_the_sdk():
    # Validates: the pure last-dot rule in resources.companion_folder equals the SDK's
    # getCompanionFolder on every name shape, including the ones where pathlib's stem
    # differs (.osm, model.); the SDK is the Application's rule and stays the reference
    if not integration_enabled():
        pytest.skip("integration disabled")
    openstudio = pytest.importorskip("openstudio")
    from mcp_server.resources import companion_folder

    cases = {
        "/a/b/model.osm": "/a/b/model",
        "/a/b/model.v2.osm": "/a/b/model.v2",
        "/a/b/files.osm": "/a/b/files",
        "/a/b/noext": "/a/b/noext",
        "/a/b/.hidden.osm": "/a/b/.hidden",
        "/a/b/x.OSM": "/a/b/x",
        "/a/b/model..osm": "/a/b/model.",
        "/a/b/model.tar.osm": "/a/b/model.tar",
        "/a/b/.osm": "/a/b",
        "/a/b/model.": "/a/b/model",
    }
    for name, expected in cases.items():
        pure = companion_folder(name)
        sdk = Path(str(openstudio.getCompanionFolder(openstudio.path(name))))
        assert pure == Path(expected), name
        assert pure == sdk, f"{name}: pure {pure} != SDK {sdk}"


def test_download_bundle_zips_the_model_with_its_companion_resources():
    # Regression: request_download handed back one file for an OSM, so a downloaded model
    # that referenced a Schedule:File CSV in its companion folder could not simulate
    # anywhere else; bundle=True with an OSM path now zips OSM + <stem>/files/ + marker
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("dl")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                osm = await _model_with_resource(s, name)
                stem = Path(osm).stem
                csv_bytes = (_companion_files(osm) / CSV).read_bytes()

                dl = unwrap(await s.call_tool("request_download", {"path": osm, "bundle": True}))
                assert dl["ok"] is True, dl
                assert dl["bundle"] is True, dl
                assert sorted(dl["members"]) == sorted([
                    f"{stem}.osm", f"{stem}/files/{CSV}", f"{stem}/.resources-migrated",
                ]), dl
                assert "warnings" not in dl, dl
                r = httpx.get(_base(url) + dl["download_path"], timeout=120)
                assert r.status_code == 200, r.text
                zf = zipfile.ZipFile(io.BytesIO(r.content))
                assert sorted(zf.namelist()) == sorted(dl["members"]), zf.namelist()
                assert zf.read(f"{stem}.osm") == Path(osm).read_bytes()
                assert zf.read(f"{stem}/files/{CSV}") == csv_bytes
                assert zf.read(f"{stem}/.resources-migrated") != b""

                # An unsaved session edit is reported: the bundle is the saved model only
                rp = unwrap(await s.call_tool("set_run_period", {
                    "begin_month": 2, "begin_day": 1, "end_month": 2, "end_day": 2,
                }))
                assert rp["ok"] is True, rp
                again = unwrap(await s.call_tool("request_download", {"path": osm, "bundle": True}))
                assert again["ok"] is True, again
                assert any("not saved" in w for w in again["warnings"]), again

        asyncio.run(_run())


def test_download_bundle_never_follows_planted_links():
    # Validates: the companion folder and the OSM path are tenant-writable, so a link at
    # the OSM, at <stem> or at files/ (each pointing at the caller's own other files, which
    # the path policy alone would allow) is refused when the URL is minted, a link at a
    # resource is skipped, and the target's bytes never reach a zip
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("dllink")
    secret = b"OS:Version,3.11.0;\nsecret,%s\n" % name.encode()

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                osm = await _model_with_resource(s, name)
                models = Path(osm).parent
                victim_dir = models.parent / f"victim_{name}"
                (victim_dir / "files").mkdir(parents=True)
                (victim_dir / "files" / "secret.csv").write_bytes(secret)
                victim_osm = models.parent / f"victim_{name}.osm"
                victim_osm.write_bytes(secret)

                # 1. link at the OSM path: refused when the URL is minted
                link_osm = models / f"{name}_link.osm"
                link_osm.symlink_to(victim_osm)
                dl = unwrap(await s.call_tool("request_download", {"path": str(link_osm), "bundle": True}))
                assert dl["ok"] is False and "symlink" in dl["error"], dl

                async def refused_at_mint(path: Path) -> None:
                    # the mint runs the same link checks as the route, so the caller sees
                    # the refusal in the tool response rather than a 4xx on GET
                    res = unwrap(await s.call_tool("request_download", {"path": str(path), "bundle": True}))
                    assert res["ok"] is False, res
                    assert "symlink" in res["error"], res

                # 2. link at <stem>: the companion folder itself is a link
                stem_osm = models / f"{name}_stem.osm"
                stem_osm.write_bytes(Path(osm).read_bytes())
                stem_osm.with_suffix("").symlink_to(victim_dir, target_is_directory=True)
                await refused_at_mint(stem_osm)

                # 3. link at files/
                files_osm = models / f"{name}_files.osm"
                files_osm.write_bytes(Path(osm).read_bytes())
                files_osm.with_suffix("").mkdir()
                (files_osm.with_suffix("") / "files").symlink_to(victim_dir / "files", target_is_directory=True)
                await refused_at_mint(files_osm)

                async def bundle_of(path: Path) -> httpx.Response:
                    res = unwrap(await s.call_tool("request_download", {"path": str(path), "bundle": True}))
                    assert res["ok"] is True, res
                    return httpx.get(_base(url) + res["download_path"], timeout=120)

                # 4. link at a resource: skipped, the rest of the bundle is served
                leaf_osm = models / f"{name}_leaf.osm"
                leaf_osm.write_bytes(Path(osm).read_bytes())
                leaf_files = _companion_files(leaf_osm)
                leaf_files.mkdir(parents=True)
                (leaf_files / "ok.csv").write_bytes(b"1\n")
                (leaf_files / "leak.csv").symlink_to(victim_dir / "files" / "secret.csv")
                r = await bundle_of(leaf_osm)
                assert r.status_code == 200, r.text
                zf = zipfile.ZipFile(io.BytesIO(r.content))
                stem = leaf_osm.stem
                assert f"{stem}/files/ok.csv" in zf.namelist()
                assert f"{stem}/files/leak.csv" not in zf.namelist(), zf.namelist()
                assert secret not in r.content
                assert (victim_dir / "files" / "secret.csv").read_bytes() == secret

        asyncio.run(_run())


def test_copy_file_carries_the_companion_folder():
    # Regression: copy_file copied the OSM alone, so loading the copy and simulating it
    # lost its Schedule:File CSV; the copy now gets <stem>/files/ (saved resources only,
    # never the session's unsaved pending files), replaces a stale same-named file and
    # reports it, writes the migration marker, and a run from the copy stages the CSV
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("cp")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                osm = await _model_with_resource(s, name)
                csv_bytes = (_companion_files(osm) / CSV).read_bytes()
                root = Path(osm).parent.parent  # <user run root>/models/<name>.osm
                stale = root / "exports" / name / "files" / CSV
                stale.parent.mkdir(parents=True)
                stale.write_bytes(b"stale\n")
                # an unsaved, pending resource must not leak into the copy
                res = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": GENERATED_MEASURE_DIR, "arguments": {"file_name": "pending.csv"},
                }))
                assert res["ok"] is True, res

                copied = unwrap(await s.call_tool("copy_file", {"file_path": osm}))
                assert copied["ok"] is True, copied
                dest = Path(copied["destination"])
                assert dest == root / "exports" / f"{name}.osm", copied
                assert copied["size_bytes"] == Path(osm).stat().st_size
                assert copied["resource_count"] == 1, copied
                assert copied["replaced_resources"] == [CSV], copied
                assert stale.read_bytes() == csv_bytes
                assert (dest.parent / name / ".resources-migrated").is_file()
                assert not (dest.parent / name / "files" / "pending.csv").exists(), (
                    "pending workspace files are not part of the saved model")

                load = unwrap(await s.call_tool("load_osm_model", {"osm_path": str(dest)}))
                assert load["ok"] is True, load
                sim = unwrap(await s.call_tool("run_simulation", {"osm_path": str(dest), "epw_path": EPW_PATH}))
                assert sim["ok"] is True, sim
                status = unwrap(await s.call_tool("get_run_status", {"run_id": sim["run_id"]}))
                run_dir = Path(status["run"]["run_dir"])
                assert (run_dir / "files" / CSV).read_bytes() == csv_bytes, "the copy's resources are staged"
                unwrap(await s.call_tool("cancel_run", {"run_id": sim["run_id"]}))

    asyncio.run(_run())


def test_copy_file_oversize_resource_fails_without_a_marker():
    # Validates: a regular resource that cannot be copied (over the per-file budget) fails
    # the copy loudly and leaves no migration marker, so the destination is never declared
    # a complete model with a resource silently missing
    if not integration_enabled():
        pytest.skip("integration disabled")
    from mcp_server.resources import MAX_RESOURCE_FILE_BYTES
    name = _unique("cpbig")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                osm = await _model_with_resource(s, name)
                with (_companion_files(osm) / "big.csv").open("wb") as fh:
                    fh.truncate(MAX_RESOURCE_FILE_BYTES + 1)  # sparse: refused on size, never read
                copied = unwrap(await s.call_tool("copy_file", {"file_path": osm}))
                assert copied["ok"] is False, copied
                assert "big.csv" in copied["message"], copied
                root = Path(osm).parent.parent
                assert not (root / "exports" / name / ".resources-migrated").exists()

    asyncio.run(_run())


@pytest.mark.parametrize(("language", "run_body"), [("Ruby", RUBY_FIND), ("Python", PYTHON_FIND)])
def test_test_measure_sees_the_models_resources(language, run_body):
    # Regression: test_measure copied only tests/test_model.osm, so a measure that reads
    # a model resource through runner.workflow.findFile failed its own test; the
    # resources are now staged where the pathless test workflow searches (<measure>/files),
    # on a private copy, and only measure.xml + tests/test_model.osm come back
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique(f"tm_{language.lower()}")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _model_with_resource(s, name)
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name, "description": "reads schedule.csv",
                    "run_body": run_body, "language": language,
                }))
                assert create["ok"] is True, create
                mdir = Path(create["measure_dir"])

                test = unwrap(await s.call_tool("test_measure", {"measure_dir": str(mdir)}))
                assert test["ok"] is True, test.get("test_output", test)
                assert test["failed"] == 0 and test["errors"] == 0, test
                assert test["passed"] >= 1, test
                assert (mdir / "tests" / "test_model.osm").is_file(), "the test model still comes back"
                assert not (mdir / "files").exists(), "staged resources never land in the measure dir"
                if language == "Ruby":
                    assert "test_model.osm" in (mdir / "measure.xml").read_text(encoding="utf-8")

    asyncio.run(_run())


def test_test_measure_reporting_measure_gets_the_runs_resources():
    # Regression: the ReportingMeasure test copied run/in.osm from the completed run but
    # not the run's files/, so a reporting measure that reads a resource the simulation
    # used could not find it
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("tmrep")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                osm = await _model_with_resource(s, name)
                sim = unwrap(await s.call_tool("run_simulation", {"osm_path": osm, "epw_path": EPW_PATH}))
                assert sim["ok"] is True, sim
                status = await poll_until_done(s, sim["run_id"])
                assert status["run"]["status"] == "success", status

                create = unwrap(await s.call_tool("create_measure", {
                    "name": name, "description": "reporting measure reads schedule.csv",
                    "run_body": RUBY_FIND, "language": "Ruby",
                    "measure_type": "ReportingMeasure",
                }))
                assert create["ok"] is True, create
                test = unwrap(await s.call_tool("test_measure", {
                    "measure_dir": create["measure_dir"], "run_id": sim["run_id"],
                }))
                assert test["ok"] is True, test
                assert test["failed"] == 0, test

    asyncio.run(_run())


def test_list_ems_actuators_sees_the_models_resources():
    # Regression: actuator discovery snapshotted the model into a scratch dir without its
    # resources, so a model with a Schedule:File CSV in its companion folder produced no
    # usable .edd; the discovery run now stages the resources like run_simulation does
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("act")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _model_with_resource(s, name)
                res = unwrap(await s.call_tool("list_ems_actuators", {
                    "component_type": "Schedule", "max_results": 0,
                }))
                assert res["ok"] is True, res
                keys = {a["actuator_key"].upper() for a in res["actuators"]}
                assert "GENERATED LIGHTING SCHEDULE" in keys, (
                    f"the Schedule:File fed by the companion CSV must be actuatable; got {sorted(keys)[:10]}")

    asyncio.run(_run())
