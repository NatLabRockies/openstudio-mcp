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
