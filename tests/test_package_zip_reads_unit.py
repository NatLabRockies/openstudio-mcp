"""The OSAF package zip writer and the analysis skill's JSON read, write and hash helpers open the
path they authorized by directory descriptor, so a component swapped for a link after the check is
refused instead of followed (issue #190, part 4)."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

import pytest
from test_analysis_tools import _http_tenant

from mcp_server import confined_fs
from mcp_server.skills.analysis import operations as analysis

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and dir_fd")

SECRET = b"bob's private bytes\n"


def _package(root: Path) -> Path:
    pkg = root / "pkg"
    (pkg / "measures" / "m" / "resources").mkdir(parents=True)
    (pkg / "measures" / "m" / "measure.rb").write_bytes(b"class M; end\n")
    (pkg / "measures" / "m" / "resources" / "data.csv").write_bytes(b"1,2\n")
    (pkg / "seeds").mkdir()
    (pkg / "seeds" / "seed.osm").write_bytes(b"OS:Version,\n")
    (pkg / "notes.txt").write_bytes(b"not a package root\n")  # outside the required roots: not zipped
    return pkg


def _members(zip_path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(zip_path) as zf:
        return {i.filename: zf.read(i) for i in zf.infolist()}


def test_zip_holds_every_regular_file_under_the_package_roots_with_exact_bytes(tmp_path, monkeypatch):
    # Validates: the descriptor-walked writer archives the same members archive.write did: every
    # regular file under measures/, seeds/, weather/, scripts/, lib/ with its bytes and relative
    # arcname, directories implied, files outside those roots left out
    root = _http_tenant(monkeypatch, tmp_path)
    pkg = _package(root)
    out = root / "out" / "analysis.zip"
    assert analysis._write_support_zip(pkg, out) is None
    assert _members(out) == {
        "measures/m/measure.rb": b"class M; end\n",
        "measures/m/resources/data.csv": b"1,2\n",
        "seeds/seed.osm": b"OS:Version,\n",
    }


@posix_only
def test_zip_member_dir_swapped_after_the_containment_check_is_not_archived(tmp_path, monkeypatch):
    # Regression: the writer checked each member resolved inside the package and then called
    # archive.write(path), which opens by pathname and follows links; measures/ replaced by a
    # link to bob's package between the two archived bob's measure.rb under alice's arcname
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "pkg" / "measures" / "m" / "resources").mkdir(parents=True)
    (bob / "pkg" / "measures" / "m" / "measure.rb").write_bytes(SECRET)
    (bob / "pkg" / "measures" / "m" / "resources" / "data.csv").write_bytes(SECRET)
    pkg = _package(root)
    real_inside = analysis._inside

    def inside_then_swap(path, package_root):
        out = real_inside(path, package_root)
        measures = pkg / "measures"
        if out and Path(path).is_file() and not measures.is_symlink():
            measures.rename(pkg / "measures_moved")
            measures.symlink_to(bob / "pkg" / "measures", target_is_directory=True)
        return out

    monkeypatch.setattr(analysis, "_inside", inside_then_swap)
    out = root / "out" / "analysis.zip"
    err = analysis._write_support_zip(pkg, out)
    # develop: the first file was archived through the link before the next member's check
    # failed, so the zip left behind held bob's measure.rb under alice's arcname
    if out.exists():
        assert SECRET not in _members(out).values(), "bob's bytes were archived under alice's arcname"
    if err is None:
        assert _members(out)["measures/m/measure.rb"] == b"class M; end\n"
    else:
        assert "link" in err, err


@posix_only
def test_zip_output_dir_that_is_a_link_is_not_written_through(tmp_path, monkeypatch):
    # Regression: the output zip's parent was created with mkdir(parents=True) and the zip opened
    # by pathname; alice/out as a link to bob's directory wrote the archive into bob's tree
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "out").mkdir()
    pkg = _package(root)
    (root / "out").symlink_to(bob / "out", target_is_directory=True)
    err = analysis._write_support_zip(pkg, root / "out" / "analysis.zip")
    assert err is not None and "analysis.zip" in err, err
    assert sorted(p.name for p in (bob / "out").iterdir()) == [], "nothing may be written into bob's dir"


@posix_only
def test_zip_refuses_a_link_member_and_reports_its_arcname(tmp_path, monkeypatch):
    # Validates: a link anywhere under a package root is still an error naming the member (the
    # pre-#190 contract), never archived as a regular file
    root = _http_tenant(monkeypatch, tmp_path)
    pkg = _package(root)
    (pkg / "measures" / "m" / "secret").symlink_to(root.parent / "bob")
    err = analysis._write_support_zip(pkg, root / "out" / "analysis.zip")
    assert err == "package member is a symlink (not allowed): measures/m/secret"


def test_zip_refuses_a_member_over_the_file_budget(tmp_path, monkeypatch):
    # Validates: a package file over the per-file budget is an error naming it, so a tenant
    # cannot make the server zip an unbounded file
    root = _http_tenant(monkeypatch, tmp_path)
    pkg = _package(root)
    monkeypatch.setattr(analysis, "MAX_PACKAGE_FILE_BYTES", 8)
    err = analysis._write_support_zip(pkg, root / "out" / "analysis.zip")
    assert err is not None and "measures/m/measure.rb" in err and "exceeds" in err, err


@posix_only
def test_read_json_source_dir_swapped_after_the_allow_check_is_refused(tmp_path, monkeypatch):
    # Regression: _read_json authorized the resolved path and then read it by pathname; alice's
    # dir replaced by a link to bob's in between returned bob's JSON
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "osa").mkdir()
    (bob / "osa" / "a.json").write_text(json.dumps({"owner": "bob"}), encoding="utf-8")
    d = root / "osa"
    d.mkdir()
    (d / "a.json").write_text(json.dumps({"owner": "alice"}), encoding="utf-8")
    real_allowed = analysis._is_analysis_path_allowed

    def allow_then_swap(p, *args, **kwargs):
        out = real_allowed(p, *args, **kwargs)
        if Path(p) == d / "a.json" and not d.is_symlink():
            d.rename(root / "osa_moved")
            d.symlink_to(bob / "osa", target_is_directory=True)
        return out

    monkeypatch.setattr(analysis, "_is_analysis_path_allowed", allow_then_swap)
    with pytest.raises(ValueError, match=r"a.json"):
        analysis._read_json(d / "a.json")


@posix_only
def test_write_json_parent_swapped_after_the_allow_check_is_not_written_through(tmp_path, monkeypatch):
    # Regression: _write_json authorized the resolved path and then wrote it by pathname; alice's
    # dir replaced by a link to bob's in between created the file in bob's tree
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "osa").mkdir()
    d = root / "osa"
    d.mkdir()
    real_allowed = analysis._is_analysis_path_allowed

    def allow_then_swap(p, *args, **kwargs):
        out = real_allowed(p, *args, **kwargs)
        if Path(p) == d / "new.json" and not d.is_symlink():
            d.rename(root / "osa_moved")
            d.symlink_to(bob / "osa", target_is_directory=True)
        return out

    monkeypatch.setattr(analysis, "_is_analysis_path_allowed", allow_then_swap)
    with pytest.raises(ValueError, match=r"new.json"):
        analysis._write_json(d / "new.json", {"x": 1})
    assert sorted(p.name for p in (bob / "osa").iterdir()) == [], "nothing may be written into bob's dir"


def test_write_json_creates_parents_and_read_json_round_trips(tmp_path, monkeypatch):
    # Validates: the descriptor-anchored helpers keep their contract: missing parents created,
    # pretty JSON written, read back as the same object, non-object JSON refused
    root = _http_tenant(monkeypatch, tmp_path)
    p = root / "deep" / "er" / "osa.json"
    assert analysis._write_json(p, {"analysis": {"name": "x"}}) == str(p)
    assert p.read_text(encoding="utf-8") == json.dumps({"analysis": {"name": "x"}}, indent=2) + "\n"
    assert analysis._read_json(p) == {"analysis": {"name": "x"}}
    p.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected JSON object"):
        analysis._read_json(p)
    with pytest.raises(ValueError, match=r"absent.json"):
        analysis._read_json(root / "absent.json")


@posix_only
def test_sha256_file_does_not_follow_a_link(tmp_path, monkeypatch):
    # Regression: the seed and weather hashes written into the preflight manifest were taken by
    # opening the path, which followed a link; a seeds/ member linked to another file hashed that
    # file. The hash now refuses a link and matches the regular-file hash otherwise
    root = _http_tenant(monkeypatch, tmp_path)
    real = root / "seed.osm"
    real.write_bytes(b"OS:Version,\n")
    link = root / "link.osm"
    link.symlink_to(real)
    assert analysis._sha256_file(real) == hashlib.sha256(b"OS:Version,\n").hexdigest()
    with pytest.raises((OSError, ValueError)):
        analysis._sha256_file(link)


@posix_only
def test_zip_member_dir_swapped_right_after_the_walker_descends_still_archives_alices_bytes(tmp_path, monkeypatch):
    # Validates: members are opened relative to the directory descriptor the walker holds. The
    # package's measures/ is replaced by a link to bob's package the moment the walker has
    # opened it; a pathname open of <pkg>/measures/m/measure.rb would now read bob's file, the
    # descriptor-relative open still reads alice's, so the archive holds her bytes and the swap
    # is proven to have happened
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "pkg" / "measures" / "m" / "resources").mkdir(parents=True)
    (bob / "pkg" / "measures" / "m" / "measure.rb").write_bytes(SECRET)
    (bob / "pkg" / "measures" / "m" / "resources" / "data.csv").write_bytes(SECRET)
    pkg = _package(root)
    real_subdir = confined_fs.DirHandle.subdir
    swapped: list[str] = []

    def subdir_then_swap(self, name, *, create=False):
        handle = real_subdir(self, name, create=create)
        if name == "measures" and self.path == pkg and not swapped:
            swapped.append(name)
            (pkg / "measures").rename(pkg / "measures_moved")
            (pkg / "measures").symlink_to(bob / "pkg" / "measures", target_is_directory=True)
        return handle

    monkeypatch.setattr(confined_fs.DirHandle, "subdir", subdir_then_swap)
    out = root / "out" / "analysis.zip"
    err = analysis._write_support_zip(pkg, out)
    assert swapped, "the swap must have happened right after the walker opened measures/"
    assert err is None, err
    members = _members(out)
    assert SECRET not in members.values(), "bob's bytes were archived under alice's arcname"
    assert members["measures/m/measure.rb"] == b"class M; end\n"


def test_zip_output_path_that_is_a_directory_is_an_error_and_the_directory_survives(tmp_path, monkeypatch):
    # Regression: every zip error removed the output path with a recursive tree removal, so an
    # output path naming an existing directory (the open fails) deleted that directory and
    # everything under it; only an archive this call opened is discarded, and as a file
    root = _http_tenant(monkeypatch, tmp_path)
    pkg = _package(root)
    out = root / "out" / "existing_dir"
    (out / "keep").mkdir(parents=True)
    (out / "keep" / "important.txt").write_bytes(b"keep me\n")
    err = analysis._write_support_zip(pkg, out)
    assert err is not None and "existing_dir" in err, err
    assert (out / "keep" / "important.txt").read_bytes() == b"keep me\n"


def test_zip_partial_output_is_discarded_on_a_member_error(tmp_path, monkeypatch):
    # Validates: when a member fails after the archive was opened, the half-written zip this call
    # created is removed (through the parent's descriptor), so no truncated package is left
    root = _http_tenant(monkeypatch, tmp_path)
    pkg = _package(root)
    monkeypatch.setattr(analysis, "MAX_PACKAGE_FILE_BYTES", 8)
    out = root / "out" / "analysis.zip"
    err = analysis._write_support_zip(pkg, out)
    assert err is not None and "exceeds" in err, err
    assert not out.exists()


def test_preflight_reports_a_seed_that_cannot_be_hashed_instead_of_raising(tmp_path, monkeypatch):
    # Regression: the seed and weather hashes raised for an oversize file or a swapped directory
    # and the exception escaped the preflight tool; both are a tool error now
    root = _http_tenant(monkeypatch, tmp_path)
    seed = root / "seed.osm"
    seed.write_bytes(b"OS:Version,\n  {00000000-0000-0000-0000-000000000000},\n  3.11.0;\n")
    monkeypatch.setattr(analysis, "MAX_PACKAGE_FILE_BYTES", 8)
    res = analysis.preflight_seed_for_analysis_package(seed_path=str(seed))
    assert res["ok"] is False and res["ready"] is False, res
    assert "hashed" in res["error"] and "seed.osm" in res["error"], res


def test_malformed_caller_schema_keeps_its_diagnostic(tmp_path, monkeypatch):
    # Regression: a caller-supplied schema with invalid JSON lost the "Invalid OSA JSON schema in
    # <path>" message (the JSONDecodeError was caught by its ValueError superclass first)
    root = _http_tenant(monkeypatch, tmp_path)
    schema = root / "schema.json"
    schema.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid OSA JSON schema in"):
        analysis._read_osa_schema(str(schema))


def _manifest_zip(path: Path, owner: str, *, resources: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"owner": owner}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("measures/m/measure.rb", "class M; end\n")
        zf.writestr("seeds/seed.osm", "OS:Version,\n")
        if resources:
            zf.writestr("lib/r.csv", "1,2\n")
            manifest.update({"resources_sha256": "0" * 64, "resource_files": ["r.csv"]})
        zf.writestr(analysis.SEED_QAQC_MANIFEST, json.dumps(manifest))


@posix_only
def test_validate_package_zip_dir_swapped_after_the_allow_check_does_not_read_the_other_tenant(tmp_path, monkeypatch):
    # Regression: validate_analysis_package authorized the zip path and then opened it by pathname;
    # alice's output dir replaced by a link to bob's in between returned bob's manifest as
    # seed_qaqc_manifest
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    _manifest_zip(bob / "out" / "analysis.zip", "bob")
    out = root / "out"
    _manifest_zip(out / "analysis.zip", "alice")
    real_allowed = analysis._is_analysis_path_allowed

    def allow_then_swap(p, *args, **kwargs):
        res = real_allowed(p, *args, **kwargs)
        if Path(p) == out / "analysis.zip" and not out.is_symlink():
            out.rename(root / "out_moved")
            out.symlink_to(bob / "out", target_is_directory=True)
        return res

    monkeypatch.setattr(analysis, "_is_analysis_path_allowed", allow_then_swap)
    res = analysis.validate_analysis_package(str(out / "analysis.zip"))
    assert res["ok"] is False, res
    assert "bob" not in repr(res), res


def test_validate_package_reads_its_own_manifest(tmp_path, monkeypatch):
    # Validates: the descriptor-opened archive still yields the package's own manifest and
    # layout findings for an ordinary package
    root = _http_tenant(monkeypatch, tmp_path)
    _manifest_zip(root / "out" / "analysis.zip", "alice")
    res = analysis.validate_analysis_package(str(root / "out" / "analysis.zip"))
    assert res["seed_qaqc_manifest"] == {"owner": "alice"}


def _measure_zip(path: Path, measure_name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"measures/{measure_name}/measure.rb", "class M; end\n")
        zf.writestr(f"measures/{measure_name}/measure.xml", "<measure/>\n")
        zf.writestr("seeds/seed.osm", "OS:Version,\n")


@posix_only
def test_smoke_workflow_opens_the_package_path_validation_authorized_not_a_re_resolved_one(tmp_path, monkeypatch):
    # Regression: the smoke-test extractor resolved the package path again after validation had
    # authorized it; alice's output dir replaced by a link to bob's in between resolved to bob's
    # real zip, which the descriptor walk then opened (no link left on that path) and extracted
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    _measure_zip(bob / "out" / "analysis.zip", "BOBS_PRIVATE_MEASURE")
    out = root / "out"
    _measure_zip(out / "analysis.zip", "alices_measure")
    validation = analysis.validate_analysis_package(str(out / "analysis.zip"))
    assert validation["zip_path"] == str(out / "analysis.zip")
    out.rename(root / "out_moved")
    out.symlink_to(bob / "out", target_is_directory=True)
    opened: list[Path] = []
    real_open = analysis._zip_for_read

    def recording_open(path):
        opened.append(Path(path))
        return real_open(path)

    monkeypatch.setattr(analysis, "_zip_for_read", recording_open)
    with pytest.raises((OSError, ValueError)):
        analysis._build_static_workflow_from_package(str(out / "analysis.zip"), validation)
    assert opened == [out / "analysis.zip"], "the open must be on the authorized path, not bob's resolved one"


def test_smoke_test_reports_an_extractor_failure_instead_of_raising(tmp_path, monkeypatch):
    # Regression: the smoke test's caller caught ValueError only, so a package whose directory
    # was swapped (NotADirectoryError), vanished (FileNotFoundError) or was truncated
    # (BadZipFile) between validation and extraction raised through the tool
    root = _http_tenant(monkeypatch, tmp_path)
    _measure_zip(root / "out" / "analysis.zip", "m")
    monkeypatch.setattr(analysis, "_server_url", lambda *_a: "http://server.invalid")
    monkeypatch.setattr(analysis, "check_server_health", lambda *_a: {"ok": True})
    monkeypatch.setattr(analysis, "_package_seed_weather_refs", lambda *_a: ("seeds/seed.osm", None))
    monkeypatch.setattr(analysis, "validate_analysis_package", lambda path, **_k: {
        "ok": True, "zip_path": path, "measure_files": ["measures/m/measure.rb"], "issues": []})

    def swapped_away(zip_path, validation):
        raise NotADirectoryError(20, "Not a directory", "out")

    monkeypatch.setattr(analysis, "_build_static_workflow_from_package", swapped_away)
    res = analysis.test_server_config_single_run(upload_zip_path=str(root / "out" / "analysis.zip"))
    assert res["ok"] is False and res["stage"] == "build_static_workflow", res
    assert "Not a directory" in res["error"]


def test_writer_keeps_the_previous_archive_and_leaves_no_temp_file_when_a_member_fails(tmp_path, monkeypatch):
    # Regression: the writer truncated the output path first and, on error, unlinked whatever
    # regular file sat at that name afterwards (a replacement written meanwhile included); it
    # now writes a private temp file beside the output, publishes it by rename on success, and
    # on failure removes only that temp file, so the previous archive survives
    root = _http_tenant(monkeypatch, tmp_path)
    pkg = _package(root)
    out = root / "out" / "analysis.zip"
    out.parent.mkdir()
    out.write_bytes(b"previous archive")
    monkeypatch.setattr(analysis, "MAX_PACKAGE_FILE_BYTES", 8)
    err = analysis._write_support_zip(pkg, out)
    assert err is not None and "exceeds" in err, err
    assert out.read_bytes() == b"previous archive"
    assert sorted(p.name for p in out.parent.iterdir()) == ["analysis.zip"], "no temp file left beside the output"


@posix_only
def test_writer_replaces_a_link_at_the_output_name_without_writing_through_it(tmp_path, monkeypatch):
    # Validates: publishing by rename replaces a link planted at the output name with the new
    # archive instead of writing through it; the link's target keeps every byte
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "target.zip").write_bytes(SECRET)
    pkg = _package(root)
    out = root / "out" / "analysis.zip"
    out.parent.mkdir()
    out.symlink_to(bob / "target.zip")
    assert analysis._write_support_zip(pkg, out) is None
    assert not out.is_symlink() and "seeds/seed.osm" in _members(out)
    assert (bob / "target.zip").read_bytes() == SECRET


def test_validation_reports_a_package_that_breaks_between_its_opens(tmp_path, monkeypatch):
    # Regression: the lib/ resource check re-opened the package after the main open; a package
    # truncated in between raised zipfile.BadZipFile through validate_analysis_package
    root = _http_tenant(monkeypatch, tmp_path)
    zip_path = root / "out" / "analysis.zip"
    _manifest_zip(zip_path, "alice", resources=True)
    real_open = analysis._zip_for_read
    calls: list[int] = []

    def truncate_before_second_open(path):
        calls.append(1)
        if len(calls) == 2:
            Path(path).write_bytes(b"PK\x03\x04 truncated")
        return real_open(path)

    monkeypatch.setattr(analysis, "_zip_for_read", truncate_before_second_open)
    res = analysis.validate_analysis_package(str(zip_path))
    assert len(calls) >= 2, "the lib/ resource check must have re-opened the package"
    assert res["ok"] is False
    assert any("could not be read" in issue or "could not be hashed" in issue for issue in res["issues"]), res["issues"]
