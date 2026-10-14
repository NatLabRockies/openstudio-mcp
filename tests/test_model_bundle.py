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
    '    first = File.open(found.get.to_s, &:readline).strip\n'
    '    if first == "fixture"\n'
    '      runner.registerError("the measure fixture shadowed the model resource")\n'
    '      return false\n'
    '    end\n'
    '    runner.registerInfo("found #{found.get}")'
)
PYTHON_FIND = (
    '        found = runner.workflow().findFile(openstudio.toPath("schedule.csv"))\n'
    '        if not found.is_initialized():\n'
    '            runner.registerError("schedule.csv not found")\n'
    '            return False\n'
    '        with open(str(found.get())) as fh:\n'
    '            first = fh.readline().strip()\n'
    '        if first == "fixture":\n'
    '            runner.registerError("the measure fixture shadowed the model resource")\n'
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


def _zip_contains(content: bytes, needle: bytes) -> bool:
    """True when any member of the zip in `content` holds `needle` (decompressed)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return needle in content
    return any(needle in zf.read(n) for n in zf.namelist())


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
                # a relative path cannot be checked component by component: refused
                rel = unwrap(await s.call_tool("request_download", {
                    "path": str(Path(osm).relative_to("/")), "bundle": True}))
                assert rel["ok"] is False and "absolute" in rel["error"], rel
                # an absolute path spelled through '..' or through a linked directory
                # above the OSM is refused, even though both resolve inside the root
                alias = models.parent / f"alias_{name}"
                alias.symlink_to(models, target_is_directory=True)
                via_alias = unwrap(await s.call_tool("request_download", {
                    "path": str(alias / Path(osm).name), "bundle": True}))
                assert via_alias["ok"] is False and "symlink" in via_alias["error"], via_alias
                dotted_path = str(models.parent / "x" / ".." / Path(osm).relative_to(models.parent))
                dotted = unwrap(await s.call_tool("request_download", {"path": dotted_path, "bundle": True}))
                assert dotted["ok"] is False and "'..'" in dotted["error"], dotted

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
                assert not _zip_contains(r.content, secret)
                assert (victim_dir / "files" / "secret.csv").read_bytes() == secret

                # 5. a directory on the path swapped for a link after the URL was minted:
                # the route repeats the component check and refuses
                swap_dir = models.parent / f"swap_{name}"
                swap_dir.mkdir()
                swap_osm = swap_dir / f"{name}.osm"
                swap_osm.write_bytes(Path(osm).read_bytes())
                minted = unwrap(await s.call_tool("request_download", {"path": str(swap_osm), "bundle": True}))
                assert minted["ok"] is True, minted
                moved = models.parent / f"moved_{name}"
                swap_dir.rename(moved)
                swap_dir.symlink_to(moved, target_is_directory=True)
                r = httpx.get(_base(url) + minted["download_path"], timeout=120)
                assert r.status_code == 409, r.text
                assert "symlink" in r.json()["error"], r.text

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
                # A fixture the measure ships under the same name: in the private test
                # copy the model's resource replaces it; the measure dir keeps it
                (mdir / "files").mkdir()
                (mdir / "files" / CSV).write_text("fixture\n", encoding="utf-8")

                test = unwrap(await s.call_tool("test_measure", {"measure_dir": str(mdir)}))
                assert test["ok"] is True, test.get("test_output", test)
                assert test["failed"] == 0 and test["errors"] == 0, test
                assert test["passed"] >= 1, test
                assert (mdir / "tests" / "test_model.osm").is_file(), "the test model still comes back"
                assert sorted(p.name for p in (mdir / "files").iterdir()) == [CSV], (
                    "staged resources never land in the measure dir")
                assert (mdir / "files" / CSV).read_text(encoding="utf-8") == "fixture\n"
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


def test_copy_back_only_returns_regular_files_inside_the_test_copy():
    # Validates: the copy-back from a private test copy into the caller's measure dir
    # copies measure.xml and tests/test_model.osm only when each is a regular file
    # resolving inside the copy and no destination component is a link; the first
    # refusal ends the copy-back and is reported
    if not integration_enabled():
        pytest.skip("integration disabled")
    pytest.importorskip("openstudio")
    from mcp_server.skills.measure_authoring.operations import _copy_back_test_outputs

    base = Path(f"/runs/{_unique('copyback')}")
    elsewhere = base / "elsewhere" / "tests"
    elsewhere.mkdir(parents=True)
    (elsewhere / "test_model.osm").write_text("elsewhere\n", encoding="utf-8")

    # source side: tests/ is a link to a dir outside the private copy
    private = base / "private"
    private.mkdir()
    (private / "measure.xml").write_text("<measure/>\n", encoding="utf-8")
    (private / "tests").symlink_to(elsewhere, target_is_directory=True)
    own = base / "own"
    own.mkdir()
    err = _copy_back_test_outputs(private, own)
    assert err is not None and "link" in err, err
    assert (own / "measure.xml").read_text(encoding="utf-8") == "<measure/>\n", "the regular file before it came back"
    assert not (own / "tests").exists(), "nothing was written for the linked entry"

    # destination side: tests/ in the own dir is a regular file: refused, no exception
    own_file = base / "own_file"
    own_file.mkdir()
    (own_file / "tests").write_text("not a dir\n", encoding="utf-8")
    err_file = _copy_back_test_outputs(private, own_file)
    assert err_file is not None and "link" in err_file, err_file  # source link refused first
    private_ok = base / "private_ok"
    (private_ok / "tests").mkdir(parents=True)
    (private_ok / "measure.xml").write_text("<measure/>\n", encoding="utf-8")
    (private_ok / "tests" / "test_model.osm").write_text("model\n", encoding="utf-8")
    err_file = _copy_back_test_outputs(private_ok, own_file)
    assert err_file is not None and "not a directory" in err_file, err_file
    assert (own_file / "tests").read_text(encoding="utf-8") == "not a dir\n"

    # destination side: tests/ in the own dir is a link
    private2 = base / "private2"
    (private2 / "tests").mkdir(parents=True)
    (private2 / "measure.xml").write_text("<measure/>\n", encoding="utf-8")
    (private2 / "tests" / "test_model.osm").write_text("model\n", encoding="utf-8")
    own2 = base / "own2"
    own2.mkdir()
    target_dir = base / "own2_target"
    target_dir.mkdir()
    (own2 / "tests").symlink_to(target_dir, target_is_directory=True)
    err2 = _copy_back_test_outputs(private2, own2)
    assert err2 is not None and "symlink" in err2, err2
    assert not (target_dir / "test_model.osm").exists(), "no write through the linked destination"

    # the normal case: both come back
    own3 = base / "own3"
    own3.mkdir()
    assert _copy_back_test_outputs(private2, own3) is None
    assert (own3 / "tests" / "test_model.osm").read_text(encoding="utf-8") == "model\n"
    assert (own3 / "measure.xml").read_text(encoding="utf-8") == "<measure/>\n"


def test_test_measure_keeps_an_explicit_model_path_named_like_a_snapshot():
    # Regression: the per-call session snapshot was recognised by its file name prefix and
    # unlinked after the copy, so a caller's own model_path with that name disappeared;
    # only the snapshot this call created is removed
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("keep")
    keep = Path(f"/runs/{name}")
    keep.mkdir()
    own_model = keep / "_test_model_mine.osm"
    own_model.write_bytes(Path("/repo/tests/assets/SystemD_baseline.osm").read_bytes())

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                create = unwrap(await s.call_tool("create_measure", {
                    "name": name, "description": "noop",
                    "run_body": '    runner.registerInfo("ok")', "language": "Ruby",
                }))
                assert create["ok"] is True, create
                test = unwrap(await s.call_tool("test_measure", {
                    "measure_dir": create["measure_dir"], "model_path": str(own_model),
                }))
                assert test["ok"] is True, test
                assert own_model.is_file(), "an explicit model_path is the caller's file; never removed"
    asyncio.run(_run())

