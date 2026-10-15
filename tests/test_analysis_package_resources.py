"""Unit tier: OSAF packaging carries the seed and its companion resources into the package, and
the seed preflight cache (manifest and completed run) is keyed on the seed, weather and
resources identity rather than the OSM and EPW alone (#198, second half)."""
import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from test_analysis_tools import _http_tenant, _measure_xml, _package_layout, _write_foundational_measure_entries

import mcp_server.skills.simulation.operations as simulation
from mcp_server.skills.analysis import operations

SEED = b"OSM seed contents"
CSV = b"1,2,3\n"
PLUGIN = b"print('hi')\n"


def _common_measures(monkeypatch, tmp_path: Path) -> None:
    common = tmp_path / "common_measures"
    for name in ("view_model", "openstudio_results", "generic_qaqc"):
        (common / name).mkdir(parents=True)
        (common / name / "measure.rb").write_text(f"class {name}; end", encoding="utf-8")
        (common / name / "measure.xml").write_text(_measure_xml(name), encoding="utf-8")
    monkeypatch.setenv("COMMON_MEASURES_DIR", str(common))


def _model_with_resources(root: Path, name: str = "m") -> Path:
    """A saved model in the Application layout: <name>.osm beside <name>/files/<resources>."""
    models = root / "models"
    (models / name / "files" / "sub").mkdir(parents=True)
    osm = models / f"{name}.osm"
    osm.write_bytes(SEED)
    (models / name / "files" / "schedule.csv").write_bytes(CSV)
    (models / name / "files" / "sub" / "plugin.py").write_bytes(PLUGIN)
    return osm


def _empty_seed_package(root: Path) -> Path:
    pkg = root / "package"
    _package_layout(pkg)
    (pkg / "seeds" / "example.osm").unlink()
    return pkg


def _recording_preflight(monkeypatch) -> list[dict]:
    """A preflight stand-in that writes a passing manifest for the seed it was given."""
    calls: list[dict] = []

    def preflight(**kwargs):
        calls.append(kwargs)
        seed = Path(kwargs["seed_path"])
        digest = operations.resources_digest(seed)
        manifest = {
            "ok": True, "ready": True, "run_id": "run_seed_preflight_123",
            "seed_sha256": hashlib.sha256(seed.read_bytes()).hexdigest(),
            "weather_sha256": None,
            "resources_sha256": digest["sha256"],
            "resource_files": sorted(digest["files"]),
            "basic_qaqc": {"passed": True, "issues": []},
        }
        Path(kwargs["manifest_path"]).write_text(json.dumps(manifest), encoding="utf-8")
        return {"ok": True, "ready": True, "manifest": manifest}

    monkeypatch.setattr(operations, "preflight_seed_for_analysis_package", preflight)
    return calls


# Fixed vectors for the two-resource set above (CSV, PLUGIN): the per-file sha256 values and
# the combined resources_sha256 the manifest and run record carry. Computed once and pinned,
# so a change to the digest format (which would orphan every recorded identity) fails here.
CSV_SHA256 = "7a8988e95e356e2b5b8fecf5e31f7c2e7e8fb44a5cd9d89ebb0d1e60b1f5c689"
PLUGIN_SHA256 = "caf026f25d7140209f98072605307a438914b9ce6f3c14b23d15d9667241de52"
TWO_RESOURCES_DIGEST = "17f28dfebda5f63cf6e83ed3d80450ad7b539dc4992e927d2eccdd732fb85fbf"


def test_resources_digest_vectors(tmp_path):
    # Validates: the digest is a function of (relative POSIX path, bytes) only, independent of
    # enumeration order and of which dir a file came from, None for no resources
    from mcp_server.model_bundle import combine_resource_hashes, digest_resource_dirs

    assert hashlib.sha256(CSV).hexdigest() == CSV_SHA256
    assert combine_resource_hashes({"sub/plugin.py": PLUGIN_SHA256, "schedule.csv": CSV_SHA256}) == TWO_RESOURCES_DIGEST
    assert combine_resource_hashes({"schedule.csv": CSV_SHA256, "sub/plugin.py": PLUGIN_SHA256}) == TWO_RESOURCES_DIGEST
    assert combine_resource_hashes({}) is None
    first, second = tmp_path / "first", tmp_path / "second"
    (first / "sub").mkdir(parents=True)
    second.mkdir()
    (first / "sub" / "plugin.py").write_bytes(PLUGIN)
    (second / "schedule.csv").write_bytes(CSV)
    (second / "sub").mkdir()
    (second / "sub" / "plugin.py").write_bytes(b"shadowed: the first dir wins")
    digest = digest_resource_dirs([first, second])
    assert digest == {
        "files": {"schedule.csv": CSV_SHA256, "sub/plugin.py": PLUGIN_SHA256},
        "sha256": TWO_RESOURCES_DIGEST,
    }
    assert digest_resource_dirs([tmp_path / "absent"]) == {"files": {}, "sha256": None}


def test_prepare_package_copies_the_seed_and_its_resources_into_the_package(monkeypatch, tmp_path):
    # Regression: an external seed_path was never copied into seeds/ and its companion resources
    # never reached the package, so the zip failed validation (seed_sha256 matched no member) or a
    # datapoint ran without the model's Schedule:File CSV; resources now go flat into lib/, the
    # directory the analysis gem adds to every datapoint's search path
    root = _http_tenant(monkeypatch, tmp_path)
    _common_measures(monkeypatch, tmp_path)
    calls = _recording_preflight(monkeypatch)
    osm = _model_with_resources(root)
    pkg = _empty_seed_package(root)
    (pkg / "lib" / "sub").mkdir()
    (pkg / "lib" / "sub" / "plugin.py").write_bytes(PLUGIN)  # same bytes already there: fine
    out = root / "analysis.zip"

    res = operations.prepare_analysis_package(package_dir=str(pkg), output_zip_path=str(out), seed_path=str(osm))

    assert res["ok"] is True, res
    assert res["validation"]["issues"] == []
    assert res["seed_member"] == "seeds/m.osm"
    assert res["resource_files"] == ["schedule.csv", "sub/plugin.py"]
    assert res["lib_files_not_from_seed"] == []
    assert [c["seed_path"] for c in calls] == [str(osm)], "the preflight simulates the model with its companion folder"
    assert (pkg / "seeds" / "m.osm").read_bytes() == SEED
    with zipfile.ZipFile(out) as archive:
        names = sorted(archive.namelist())
        assert archive.read("seeds/m.osm") == SEED
        assert archive.read("lib/schedule.csv") == CSV
        assert archive.read("lib/sub/plugin.py") == PLUGIN
        manifest = json.loads(archive.read("lib/seed_simulation_qaqc.json"))
    assert [n for n in names if n.startswith("seeds/")] == ["seeds/m.osm"], "nothing but the seed under seeds/"
    assert manifest["seed_member"] == "seeds/m.osm"
    assert manifest["resource_files"] == ["schedule.csv", "sub/plugin.py"]
    assert manifest["resources_sha256"] == TWO_RESOURCES_DIGEST


def test_prepare_package_refuses_a_second_seed_before_copying(monkeypatch, tmp_path):
    # Regression: the manifest hash check accepted any member under seeds/ while submission took
    # the first, so a package validated for one seed could be submitted with another
    root = _http_tenant(monkeypatch, tmp_path)
    calls = _recording_preflight(monkeypatch)
    pkg = root / "package"
    _package_layout(pkg)  # seeds/example.osm
    other = root / "z.osm"
    other.write_bytes(b"another model")

    res = operations.prepare_analysis_package(
        package_dir=str(pkg), output_zip_path=str(root / "a.zip"), seed_path=str(other),
    )

    assert res["ok"] is False
    assert "seeds/example.osm" in res["error"] and "seeds/z.osm" in res["error"], res
    assert not (pkg / "seeds" / "z.osm").exists(), "refused before the copy"
    assert calls == []


def test_prepare_package_refuses_a_same_named_seed_with_different_bytes(monkeypatch, tmp_path):
    # Validates: a copy already in seeds/ is reused only when it holds the seed's bytes; otherwise
    # the manifest would vouch for a model the package does not carry
    root = _http_tenant(monkeypatch, tmp_path)
    calls = _recording_preflight(monkeypatch)
    osm = _model_with_resources(root)
    pkg = _empty_seed_package(root)
    (pkg / "seeds" / "m.osm").write_bytes(b"stale copy")

    res = operations.prepare_analysis_package(
        package_dir=str(pkg), output_zip_path=str(root / "a.zip"), seed_path=str(osm),
    )

    assert res["ok"] is False
    assert "seeds/m.osm" in res["error"] and "different content" in res["error"], res
    assert (pkg / "seeds" / "m.osm").read_bytes() == b"stale copy", "never overwritten"
    assert calls == []


def test_prepare_package_refuses_a_lib_resource_with_different_bytes(monkeypatch, tmp_path):
    # Validates: lib/ is shared by every packaging of a package_dir; a same-named file with other
    # bytes is an error, never silently kept (the datapoint would read the wrong CSV)
    root = _http_tenant(monkeypatch, tmp_path)
    calls = _recording_preflight(monkeypatch)
    osm = _model_with_resources(root)
    pkg = _empty_seed_package(root)
    (pkg / "lib" / "schedule.csv").write_bytes(b"9,9,9\n")

    res = operations.prepare_analysis_package(
        package_dir=str(pkg), output_zip_path=str(root / "a.zip"), seed_path=str(osm),
    )

    assert res["ok"] is False
    assert "lib/schedule.csv" in res["error"] and "different content" in res["error"], res
    assert (pkg / "lib" / "schedule.csv").read_bytes() == b"9,9,9\n", "the caller's file is kept"
    assert calls == []


def test_prepare_package_reports_lib_files_that_are_not_the_seeds(monkeypatch, tmp_path):
    # Validates: an earlier packaging's resource left in lib/ is reported, not deleted (it is the
    # caller's package_dir content) and does not fail the package
    root = _http_tenant(monkeypatch, tmp_path)
    _common_measures(monkeypatch, tmp_path)
    _recording_preflight(monkeypatch)
    osm = _model_with_resources(root)
    pkg = _empty_seed_package(root)
    (pkg / "lib" / "old_seed.csv").write_bytes(b"old\n")

    res = operations.prepare_analysis_package(
        package_dir=str(pkg), output_zip_path=str(root / "a.zip"), seed_path=str(osm),
    )

    assert res["ok"] is True, res
    assert res["lib_files_not_from_seed"] == ["old_seed.csv"]
    assert (pkg / "lib" / "old_seed.csv").read_bytes() == b"old\n"


def test_prepare_package_refuses_non_seed_files_under_seeds(monkeypatch, tmp_path):
    # Validates: a companion folder under seeds/ is invisible to datapoints (the search is not
    # recursive) and its files would be taken for seed candidates; the package refuses it
    root = _http_tenant(monkeypatch, tmp_path)
    calls = _recording_preflight(monkeypatch)
    pkg = root / "package"
    _package_layout(pkg)
    (pkg / "seeds" / "example" / "files").mkdir(parents=True)
    (pkg / "seeds" / "example" / "files" / "schedule.csv").write_bytes(CSV)

    res = operations.prepare_analysis_package(package_dir=str(pkg), output_zip_path=str(root / "a.zip"))

    assert res["ok"] is False
    assert "seeds/example/files/schedule.csv" in res["error"] and "lib/" in res["error"], res
    assert calls == []


@pytest.mark.parametrize("planted", ["seeds", "lib", "lib/schedule.csv"])
def test_prepare_package_refuses_planted_links_before_writing(monkeypatch, tmp_path, planted):
    # Validates: a link at seeds/, lib/ or a lib/ resource name is refused before the seed or a
    # resource is written, so nothing lands outside the package (both roots are tenant-writable)
    root = _http_tenant(monkeypatch, tmp_path)
    calls = _recording_preflight(monkeypatch)
    osm = _model_with_resources(root)
    pkg = _empty_seed_package(root)
    elsewhere = root.parent / "bob" / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "keep.txt").write_bytes(b"keep")
    target = pkg / planted
    if planted == "lib/schedule.csv":
        target.symlink_to(elsewhere / "keep.txt")
    else:
        shutil.rmtree(target)
        target.symlink_to(elsewhere, target_is_directory=True)

    res = operations.prepare_analysis_package(
        package_dir=str(pkg), output_zip_path=str(root / "a.zip"), seed_path=str(osm),
    )

    assert res["ok"] is False
    assert "link" in res["error"], res
    assert sorted(p.name for p in elsewhere.iterdir()) == ["keep.txt"], "nothing written through the link"
    assert (elsewhere / "keep.txt").read_bytes() == b"keep"
    assert calls == []


def test_prepare_package_never_writes_the_manifest_through_a_swapped_lib_dir(monkeypatch, tmp_path):
    # Regression: the manifest rewrite opened pkg/lib/seed_simulation_qaqc.json no-follow at the
    # last component only, so lib/ swapped for a link while the preflight ran redirected the
    # write into the link's target; the write now goes through a descriptor of lib/ itself
    root = _http_tenant(monkeypatch, tmp_path)
    _common_measures(monkeypatch, tmp_path)
    osm = _model_with_resources(root)
    pkg = _empty_seed_package(root)
    elsewhere = root.parent / "bob" / "elsewhere"
    elsewhere.mkdir()

    def preflight(**kwargs):
        manifest = _manifest(SEED, ready=True)
        Path(kwargs["manifest_path"]).write_text(json.dumps(manifest), encoding="utf-8")
        shutil.move(pkg / "lib", pkg / "lib_moved")
        (pkg / "lib").symlink_to(elsewhere, target_is_directory=True)
        return {"ok": True, "ready": True, "manifest": manifest}

    monkeypatch.setattr(operations, "preflight_seed_for_analysis_package", preflight)

    res = operations.prepare_analysis_package(
        package_dir=str(pkg), output_zip_path=str(root / "a.zip"), seed_path=str(osm),
    )

    assert res["ok"] is False, res
    assert list(elsewhere.iterdir()) == [], "nothing written through the swapped lib/"
    assert not (root / "a.zip").exists()


@pytest.mark.skipif(not hasattr(__import__("os"), "mkfifo"), reason="POSIX FIFO")
@pytest.mark.timeout(30)
def test_prepare_package_rejects_a_fifo_at_a_resource_name_without_blocking(monkeypatch, tmp_path):
    # Regression: the verification hash opened lib/<rel> O_RDONLY, which blocks on a FIFO
    # before fstat can reject it; a FIFO planted at a resource name hung packaging
    import os

    root = _http_tenant(monkeypatch, tmp_path)
    calls = _recording_preflight(monkeypatch)
    osm = _model_with_resources(root)
    pkg = _empty_seed_package(root)
    os.mkfifo(pkg / "lib" / "schedule.csv")

    res = operations.prepare_analysis_package(
        package_dir=str(pkg), output_zip_path=str(root / "a.zip"), seed_path=str(osm),
    )

    assert res["ok"] is False
    assert "lib/schedule.csv" in res["error"] and "not a regular file" in res["error"], res
    assert calls == []


# ---- preflight identity -----------------------------------------------------------------


def _seed_and_weather(root: Path) -> tuple[Path, Path]:
    osm = _model_with_resources(root)
    epw = root / "w.epw"
    epw.write_bytes(b"weather bytes")
    return osm, epw


def _identity_of(osm: Path, epw: Path | None) -> dict:
    return {
        "seed_sha256": hashlib.sha256(osm.read_bytes()).hexdigest(),
        "weather_sha256": hashlib.sha256(epw.read_bytes()).hexdigest() if epw else None,
        "resources_sha256": operations.resources_digest(osm)["sha256"],
    }


def _write_run(root: Path, run_id: str, *, ended_at: float, sql: bool = True, **record) -> Path:
    """A run_record.json as run_simulation writes it, plus the artefact the cache looks for."""
    run_dir = root / run_id
    (run_dir / "run").mkdir(parents=True)
    data = {
        "run_id": run_id, "user_key": "alice", "name": run_id, "status": "success",
        "created_at": ended_at - 10, "started_at": ended_at - 9, "ended_at": ended_at, "pid": None,
        "run_dir": str(run_dir), "osw_path": str(run_dir / "workflow.osw"), "epw_path": None,
        "exit_code": 0, "error": None,
    }
    data.update(record)
    (run_dir / "run_record.json").write_text(json.dumps(data), encoding="utf-8")
    if sql:
        (run_dir / "run" / "eplusout.sql").write_bytes(b"sqlite")
    return run_dir


def _fake_simulation(monkeypatch, root: Path, *, complete: bool, record_override: dict | None = None):
    """run_simulation / get_run_status / QA/QC stand-ins; the run records the identity as the real one does."""
    calls: list[dict] = []

    def run_simulation(osm_path, epw_path=None, name=None):
        calls.append({"osm_path": osm_path, "epw_path": epw_path})
        run_id = f"run_new_{len(calls)}"
        identity = _identity_of(Path(osm_path), Path(epw_path) if epw_path else None)
        identity.update(record_override or {})
        _write_run(root, run_id, ended_at=1000.0 + len(calls), status="success" if complete else "queued", **identity)
        return {"ok": True, "run_id": run_id, "status": "queued"}

    def get_run_status(run_id):
        return {"ok": True, "run": {"status": "success" if complete else "queued", "run_id": run_id}}

    # the preflight imports both from the simulation module at call time
    monkeypatch.setattr(simulation, "run_simulation", run_simulation)
    monkeypatch.setattr(simulation, "get_run_status", get_run_status)
    monkeypatch.setattr(operations, "_basic_seed_qaqc", lambda _run_id: {"ok": True, "passed": True, "issues": []})
    monkeypatch.setattr(operations, "_effective_weather", lambda _seed: None)
    return calls


def test_preflight_manifest_is_reused_only_on_the_full_identity(monkeypatch, tmp_path):
    # Regression: the manifest matched on the OSM and EPW hashes alone, so editing a resource
    # (a Schedule:File CSV) and repackaging reused the stale QA/QC evidence; a manifest without
    # the resource digest (written before this change) is rerun once
    root = _http_tenant(monkeypatch, tmp_path)
    osm, epw = _seed_and_weather(root)
    calls = _fake_simulation(monkeypatch, root, complete=True)
    manifest = root / "package" / "lib" / "seed_simulation_qaqc.json"

    first = operations.preflight_seed_for_analysis_package(
        str(osm), weather_file=str(epw), manifest_path=str(manifest),
    )
    assert first["ok"] is True and first["ready"] is True and first["reused"] is False, first
    assert len(calls) == 1
    written = json.loads(manifest.read_text(encoding="utf-8"))
    assert written["seed_sha256"] == hashlib.sha256(SEED).hexdigest()
    assert written["weather_sha256"] == hashlib.sha256(b"weather bytes").hexdigest()
    assert written["resource_files"] == ["schedule.csv", "sub/plugin.py"]
    assert written["resources_sha256"] == TWO_RESOURCES_DIGEST

    second = operations.preflight_seed_for_analysis_package(
        str(osm), weather_file=str(epw), manifest_path=str(manifest),
    )
    assert second["reused"] is True and second["source"] == "manifest", second
    assert len(calls) == 1

    # an older manifest (no resource identity) with matching seed and weather is not reused
    old = {k: v for k, v in written.items() if k != "resources_sha256"}
    manifest.write_text(json.dumps(old), encoding="utf-8")
    for run_dir in root.glob("run_*"):
        shutil.rmtree(run_dir)  # so the cached-run lookup cannot answer instead
    third = operations.preflight_seed_for_analysis_package(
        str(osm), weather_file=str(epw), manifest_path=str(manifest),
    )
    assert third["reused"] is False, third
    assert len(calls) == 2

    # one changed resource byte: neither the manifest nor the run just made match
    (osm.parent / "m" / "files" / "schedule.csv").write_bytes(b"1,2,4\n")
    fourth = operations.preflight_seed_for_analysis_package(
        str(osm), weather_file=str(epw), manifest_path=str(manifest),
    )
    assert fourth["reused"] is False, fourth
    assert len(calls) == 3
    rewritten = json.loads(manifest.read_text(encoding="utf-8"))
    assert rewritten["resources_sha256"] != written["resources_sha256"]


def test_preflight_matches_a_completed_run_on_its_recorded_identity_only(monkeypatch, tmp_path):
    # Regression: the cached-run match rehashed the run dir's seed and EPW (tenant-written files)
    # and ignored resources; now only the triple run_simulation recorded at launch counts, the run
    # is the directory the record sits in, and eplusout.sql must be a regular file inside it
    root = _http_tenant(monkeypatch, tmp_path)
    osm, epw = _seed_and_weather(root)
    calls = _fake_simulation(monkeypatch, root, complete=False)
    identity = _identity_of(osm, epw)

    def preflight():
        return operations.preflight_seed_for_analysis_package(str(osm), weather_file=str(epw))

    # (i) a run in the old layout: seed and EPW staged and hashable, no recorded identity
    old = _write_run(root, "run_old", ended_at=100.0)
    (old / "m.osm").write_bytes(SEED)
    (old / "files").mkdir()
    (old / "files" / "w.epw").write_bytes(b"weather bytes")
    (old / "workflow.osw").write_text(json.dumps({"seed_file": "m.osm", "weather_file": "files/w.epw"}))
    res = preflight()
    assert res["reused"] is False and res["run_id"] == "run_new_1", res
    assert len(calls) == 1
    shutil.rmtree(root / "run_new_1")

    # (ii) a recorded identity equal to the seed's: reused
    _write_run(root, "run_match", ended_at=200.0, **identity)
    res = preflight()
    assert res["reused"] is True and res["run_id"] == "run_match", res
    assert len(calls) == 1

    # (iii) newer, but a different resource digest: still run_match
    _write_run(root, "run_other_resources", ended_at=300.0, **{**identity, "resources_sha256": "0" * 64})
    assert preflight()["run_id"] == "run_match"

    # (iv) newer, matching triple, but its run_dir field points at a directory holding the
    #      artefact while its own directory has none: the field is not trusted
    other = root.parent / "bob" / "run_elsewhere"
    (other / "run").mkdir(parents=True)
    (other / "run" / "eplusout.sql").write_bytes(b"sqlite")
    _write_run(root, "run_forged_dir", ended_at=400.0, sql=False, run_dir=str(other), **identity)
    assert preflight()["run_id"] == "run_match"

    # (v) newer, matching, with its artefact: wins
    _write_run(root, "run_newest", ended_at=500.0, **identity)
    assert preflight()["run_id"] == "run_newest"
    assert len(calls) == 1


def test_preflight_resolves_the_models_own_weather_when_none_is_passed(monkeypatch, tmp_path):
    # Regression: with no weather_file the preflight hashed no weather, so its identity never
    # matched a run that staged the model's own EPW (what run_simulation does without an
    # override); the effective EPW is now resolved the same way and recorded
    root = _http_tenant(monkeypatch, tmp_path)
    osm, epw = _seed_and_weather(root)
    calls = _fake_simulation(monkeypatch, root, complete=True)
    monkeypatch.setattr(operations, "_effective_weather", lambda _seed: epw)
    manifest = root / "m.json"

    res = operations.preflight_seed_for_analysis_package(str(osm), manifest_path=str(manifest))

    assert res["ok"] is True and res["reused"] is False, res
    assert calls == [{"osm_path": str(osm), "epw_path": str(epw)}]
    written = json.loads(manifest.read_text(encoding="utf-8"))
    assert written["weather_file"] == str(epw)
    assert written["weather_sha256"] == hashlib.sha256(b"weather bytes").hexdigest()
    again = operations.preflight_seed_for_analysis_package(str(osm))
    assert again["reused"] is True and again["run_id"] == "run_new_1", "the run that staged that EPW matches"


def test_preflight_refuses_a_run_whose_recorded_identity_differs(monkeypatch, tmp_path):
    # Validates: the run hashes what it staged; if that differs from what the preflight hashed
    # (a file changed in between), the run is no evidence for the seed as it is now
    root = _http_tenant(monkeypatch, tmp_path)
    osm, epw = _seed_and_weather(root)
    calls = _fake_simulation(monkeypatch, root, complete=True, record_override={"seed_sha256": "f" * 64})
    manifest = root / "m.json"

    res = operations.preflight_seed_for_analysis_package(
        str(osm), weather_file=str(epw), manifest_path=str(manifest), wait_timeout_seconds=1,
    )

    assert res["ok"] is False and res["ready"] is False, res
    assert "changed while the preflight simulation ran" in res["error"]
    assert res["run_id"] == "run_new_1" and len(calls) == 1
    assert not manifest.exists()


def test_preflight_refuses_a_linked_seed_or_manifest_path(monkeypatch, tmp_path):
    # Validates: the seed is hashed and its companion folder read from the lexical path, and the
    # manifest is written where named; a link at either is refused rather than followed
    root = _http_tenant(monkeypatch, tmp_path)
    osm, epw = _seed_and_weather(root)
    calls = _fake_simulation(monkeypatch, root, complete=True)
    link = root / "link.osm"
    link.symlink_to(osm)
    res = operations.preflight_seed_for_analysis_package(str(link), weather_file=str(epw))
    assert res["ok"] is False and "symlink" in res["error"], res
    manifest_link = root / "manifest_link.json"
    manifest_link.symlink_to(root / "elsewhere.json")
    res = operations.preflight_seed_for_analysis_package(
        str(osm), weather_file=str(epw), manifest_path=str(manifest_link),
    )
    assert res["ok"] is False and "symlink" in res["error"], res
    assert not (root / "elsewhere.json").exists()
    assert calls == []


# ---- validate_analysis_package -----------------------------------------------------------


def _manifest(seed: bytes, **extra) -> dict:
    data = {
        "ok": True, "run_id": "run_seed_preflight_123",
        "seed_sha256": hashlib.sha256(seed).hexdigest(),
        "weather_sha256": None, "resources_sha256": None,
        "basic_qaqc": {"passed": True, "issues": []},
    }
    data.update(extra)
    return data


def _package_zip(path: Path, manifest: dict, *, seeds: dict[str, bytes], lib: dict[str, bytes] | None = None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("weather/example.epw", "weather")
        for name, content in seeds.items():
            archive.writestr(f"seeds/{name}", content)
        for name, content in (lib or {}).items():
            archive.writestr(f"lib/{name}", content)
        archive.writestr("measures/SetWWR/measure.rb", "class SetWWR; end")
        archive.writestr("measures/SetWWR/measure.xml", _measure_xml("set_wwr", class_name="SetWWR"))
        _write_foundational_measure_entries(archive)
        archive.writestr("scripts/data_point/initialization.sh", "exit 0\n")
        archive.writestr("lib/seed_simulation_qaqc.json", json.dumps(manifest))


def test_validate_package_rejects_a_manifest_without_the_resource_identity(tmp_path):
    # Validates: a manifest from before resources were part of the identity cannot vouch for the
    # package's lib/ contents; the issue names the tool that rewrites it
    manifest = _manifest(SEED)
    del manifest["resources_sha256"]
    _package_zip(tmp_path / "a.zip", manifest, seeds={"example.osm": SEED})

    validation = operations.validate_analysis_package(str(tmp_path / "a.zip"))

    assert validation["ok"] is False
    assert validation["issues"] == [
        "lib/seed_simulation_qaqc.json predates the resource identity (no resources_sha256). "
        "Run openstudio_analysis_prepare_package again.",
    ]


def test_validate_package_checks_lib_resources_against_the_manifest(tmp_path):
    # Validates: the zip's lib/ members listed in the manifest must hash to resources_sha256,
    # so a package whose resource was edited after packaging, or lost a member, is rejected
    manifest = _manifest(SEED, resources_sha256=TWO_RESOURCES_DIGEST, resource_files=["schedule.csv", "sub/plugin.py"])

    _package_zip(tmp_path / "ok.zip", manifest, seeds={"m.osm": SEED},
                 lib={"schedule.csv": CSV, "sub/plugin.py": PLUGIN})
    good = operations.validate_analysis_package(str(tmp_path / "ok.zip"))
    assert good["ok"] is True, good["issues"]

    _package_zip(tmp_path / "edited.zip", manifest, seeds={"m.osm": SEED},
                 lib={"schedule.csv": b"1,2,4\n", "sub/plugin.py": PLUGIN})
    edited = operations.validate_analysis_package(str(tmp_path / "edited.zip"))
    assert edited["ok"] is False
    assert edited["issues"] == [
        "lib/ resources do not match lib/seed_simulation_qaqc.json resources_sha256. "
        "Run openstudio_analysis_prepare_package again.",
    ]

    _package_zip(tmp_path / "missing.zip", manifest, seeds={"m.osm": SEED}, lib={"schedule.csv": CSV})
    missing = operations.validate_analysis_package(str(tmp_path / "missing.zip"))
    assert missing["ok"] is False
    assert missing["issues"] == [
        "lib/ is missing seed resources listed in lib/seed_simulation_qaqc.json: lib/sub/plugin.py",
    ]


def test_validate_package_bounds_the_resources_it_decompresses(monkeypatch, tmp_path):
    # Validates: the zip is tenant-built, so a listed resource declaring more than the per-file
    # budget, or listed twice, is refused before anything is decompressed and hashed
    manifest = _manifest(SEED, resources_sha256=TWO_RESOURCES_DIGEST, resource_files=["schedule.csv", "sub/plugin.py"])
    _package_zip(tmp_path / "a.zip", manifest, seeds={"m.osm": SEED},
                 lib={"schedule.csv": CSV, "sub/plugin.py": PLUGIN})
    monkeypatch.setattr(operations, "MAX_RESOURCE_FILE_BYTES", len(CSV))
    validation = operations.validate_analysis_package(str(tmp_path / "a.zip"))
    assert validation["issues"] == [
        "lib/ resource could not be verified: lib/sub/plugin.py: "
        f"{len(PLUGIN)} bytes exceeds the {len(CSV)}-byte limit",
    ]

    twice = _manifest(SEED, resources_sha256=TWO_RESOURCES_DIGEST, resource_files=["schedule.csv", "schedule.csv"])
    _package_zip(tmp_path / "twice.zip", twice, seeds={"m.osm": SEED}, lib={"schedule.csv": CSV})
    validation = operations.validate_analysis_package(str(tmp_path / "twice.zip"))
    assert validation["issues"] == ["lib/seed_simulation_qaqc.json resource_files lists a resource more than once."]


def test_validate_package_requires_one_seed_that_hashes_to_the_manifest(tmp_path):
    # Regression: seed_sha256 was accepted when it matched ANY member under seeds/ while
    # submission used the first; the manifest now names its member and the archive holds one seed
    _package_zip(tmp_path / "two.zip", _manifest(SEED), seeds={"a.osm": b"other", "b.osm": SEED})
    validation = operations.validate_analysis_package(str(tmp_path / "two.zip"))
    assert validation["ok"] is False
    assert validation["issues"] == [
        "seeds/ must contain exactly one seed model when the QA/QC manifest is required; "
        "found: seeds/a.osm, seeds/b.osm",
    ]

    _package_zip(tmp_path / "wrong.zip", _manifest(SEED, seed_member="seeds/b.osm"), seeds={"a.osm": b"other"})
    validation = operations.validate_analysis_package(str(tmp_path / "wrong.zip"))
    assert validation["issues"] == [
        "lib/seed_simulation_qaqc.json seed_member seeds/b.osm is not a seed in seeds/.",
        "lib/seed_simulation_qaqc.json seed_sha256 does not match seeds/a.osm.",
    ]

    _package_zip(tmp_path / "files.zip", _manifest(SEED), seeds={"a.osm": SEED, "a/files/schedule.csv": CSV})
    validation = operations.validate_analysis_package(str(tmp_path / "files.zip"))
    assert validation["issues"] == [
        "seeds/ must contain only .osm or .osw seed files (resources go to lib/): seeds/a/files/schedule.csv",
    ]


def test_submission_uses_the_manifests_seed_member():
    # Validates: the datapoint seed reference follows the manifest, not whichever member sorts
    # first under seeds/
    seed, weather = operations._package_seed_weather_refs({
        "seed_files": ["seeds/a.osm", "seeds/b.osm"],
        "weather_files": ["weather/x.epw"],
        "seed_qaqc_manifest": {"seed_member": "seeds/b.osm"},
    })
    assert seed == {"file_type": "OSM", "path": "./seeds/b.osm"}
    assert weather == {"file_type": "EPW", "path": "./weather/x.epw"}
    seed, _ = operations._package_seed_weather_refs({"seed_files": ["seeds/a.osm"], "weather_files": []})
    assert seed == {"file_type": "OSM", "path": "./seeds/a.osm"}
