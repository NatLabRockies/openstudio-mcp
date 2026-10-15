"""confined_copy.copy_tree_confined / remove_tree_confined and the tree-copy sites that used
shutil.copytree: measure staging, copy_file's directory copies, the OSAF package's foundational
measures and the OSW staging copy. Both trees are walked by directory descriptor, so a component
swapped for a link after the caller's check fails the copy instead of redirecting it into or out of
another tenant's tree (issue #190, part 2)."""
import os
import stat
import sys
from pathlib import Path

import pytest
from test_analysis_tools import _http_tenant

from mcp_server import confined_copy, confined_fs
from mcp_server.skills.analysis import operations as analysis
from mcp_server.skills.results import operations as results
from mcp_server.skills.simulation import operations as sim_ops

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks, FIFOs and dir_fd")

SECRET = b"bob's private bytes\n"


def _tree(root: Path) -> Path:
    """A small measure-like tree: measure.rb (0o755), measure.xml, resources/data.csv."""
    (root / "resources").mkdir(parents=True)
    (root / "measure.rb").write_bytes(b"class M; end\n")
    (root / "measure.rb").chmod(0o755)
    (root / "measure.xml").write_bytes(b"<measure/>\n")
    (root / "resources" / "data.csv").write_bytes(b"1,2,3\n")
    return root


def _snapshot(tree: Path) -> dict[str, bytes | str]:
    out: dict[str, bytes | str] = {}
    for p in sorted(tree.rglob("*")):
        rel = str(p.relative_to(tree))
        out[rel] = str(p.readlink()) if p.is_symlink() else (p.read_bytes() if p.is_file() else "<dir>")
    return out


def _contains_bytes(tree: Path, needle: bytes) -> bool:
    return any(p.is_file() and not p.is_symlink() and p.read_bytes() == needle for p in tree.rglob("*"))


# --- primitive -------------------------------------------------------------------------------

def test_copies_nested_tree_bytes_modes_and_counts(tmp_path, monkeypatch):
    # Validates: the replacement for shutil.copytree reproduces the tree (sub-directories, exact
    # bytes, the executable bit the CLI needs on measure scripts) and reports what it copied
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "m")
    dst = root / "run" / "measures" / "m"
    counts = confined_copy.copy_tree_confined(src, dst)
    assert counts == {"dirs": 1, "files": 3, "bytes": 13 + 11 + 6, "links": 0}
    assert _snapshot(dst) == _snapshot(src)
    if sys.platform != "win32":
        assert stat.S_IMODE((dst / "measure.rb").stat().st_mode) == 0o755


@posix_only
@pytest.mark.parametrize(("target", "outcome"), [
    ("resources/data.csv", "kept"),
    ("../m/measure.xml", "refused"),  # re-enters by the tree's own name: lexically it still leaves
    ("../../bob/secret.txt", "refused"),
    ("/etc/hostname", "refused"),
])
def test_links_are_recreated_only_when_they_stay_inside_the_tree(tmp_path, monkeypatch, target, outcome):
    # Validates: copytree(symlinks=True) recreated every link as written; the descriptor copy keeps a
    # relative link whose lexical target stays under the copied tree (a measure's own file) and
    # refuses an absolute or escaping one even though the pathname pre-check passed (a swap)
    root = _http_tenant(monkeypatch, tmp_path)
    (root.parent / "bob" / "secret.txt").write_bytes(SECRET)
    src = _tree(root / "m")
    (src / "link").symlink_to(target)
    dst = root / "run" / "m"
    if outcome == "kept":
        counts = confined_copy.copy_tree_confined(src, dst)
        assert counts["links"] == 1
        assert str((dst / "link").readlink()) == target
        assert not (dst / "link").is_file() or (dst / "link").read_bytes() in (b"1,2,3\n", b"<measure/>\n")
    else:
        with pytest.raises(ValueError, match="link"):
            confined_copy.copy_tree_confined(src, dst)
        assert not (dst / "link").exists() and not (dst / "link").is_symlink()
        assert not _contains_bytes(root / "run", SECRET)


@posix_only
def test_a_fifo_in_the_source_fails_the_copy_without_blocking(tmp_path, monkeypatch):
    # Validates: a named pipe planted in a tenant-written tree is a copy error, not a hang on open
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "m")
    os.mkfifo(src / "resources" / "pipe")
    with pytest.raises(ValueError, match="not a regular file"):
        confined_copy.copy_tree_confined(src, root / "run" / "m")


def test_budgets_stop_the_copy(tmp_path, monkeypatch):
    # Validates: a tree over the file-count or per-file byte budget is refused (a tenant cannot
    # make the server copy an unbounded tree into its own run dir)
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "m")
    with pytest.raises(ValueError, match="files"):
        confined_copy.copy_tree_confined(src, root / "run" / "a", max_files=2)
    with pytest.raises(ValueError, match="exceeds"):
        confined_copy.copy_tree_confined(src, root / "run" / "b", max_file_bytes=10)
    with pytest.raises(ValueError, match="total"):
        confined_copy.copy_tree_confined(src, root / "run" / "c", max_total_bytes=20)


def test_a_destination_inside_the_source_is_refused(tmp_path, monkeypatch):
    # Validates: copying a directory into itself (copy_file of a run dir to that run dir) is a
    # ValueError before anything is written, not an unbounded recursion
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "m")
    before = _snapshot(src)
    with pytest.raises(ValueError, match="nest"):
        confined_copy.copy_tree_confined(src, src / "resources" / "m")
    with pytest.raises(ValueError, match=r"nest|same"):
        confined_copy.copy_tree_confined(src, src)
    assert _snapshot(src) == before


@posix_only
def test_replace_removes_the_existing_destination_through_its_parent_descriptor(tmp_path, monkeypatch):
    # Validates: replace=True clears a stale directory, file or link at the destination name; a
    # link there is unlinked, never followed, so the tree it points at keeps every byte
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "stale").mkdir()
    (bob / "stale" / "keep.txt").write_bytes(SECRET)
    src = _tree(root / "m")
    stale_dir = root / "out" / "d"
    stale_dir.mkdir(parents=True)
    (stale_dir / "old.txt").write_bytes(b"old\n")
    confined_copy.copy_tree_confined(src, stale_dir, replace=True)
    assert not (stale_dir / "old.txt").exists() and _snapshot(stale_dir) == _snapshot(src)
    stale_file = root / "out" / "f"
    stale_file.write_bytes(b"file\n")
    confined_copy.copy_tree_confined(src, stale_file, replace=True)
    assert _snapshot(stale_file) == _snapshot(src)
    stale_link = root / "out" / "l"
    stale_link.symlink_to(bob / "stale", target_is_directory=True)
    confined_copy.copy_tree_confined(src, stale_link, replace=True)
    assert not stale_link.is_symlink() and _snapshot(stale_link) == _snapshot(src)
    assert (bob / "stale" / "keep.txt").read_bytes() == SECRET


def test_merge_into_an_existing_destination_overwrites_files_and_keeps_others(tmp_path, monkeypatch):
    # Validates: the dirs_exist_ok=True sites (measure staging into a run dir that already holds
    # files) still merge: a same-named regular file is replaced, unrelated files survive
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "m")
    dst = root / "run" / "m"
    dst.mkdir(parents=True)
    (dst / "measure.xml").write_bytes(b"stale\n")
    (dst / "unrelated.txt").write_bytes(b"keep\n")
    confined_copy.copy_tree_confined(src, dst)
    assert (dst / "measure.xml").read_bytes() == b"<measure/>\n"
    assert (dst / "unrelated.txt").read_bytes() == b"keep\n"


@posix_only
def test_merge_never_writes_through_a_link_or_directory_at_a_file_name(tmp_path, monkeypatch):
    # Validates: with dirs_exist_ok=True, copytree followed a link planted at a destination file
    # name and wrote the source bytes into its target; the descriptor copy fails instead
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "target.xml").write_bytes(SECRET)
    src = _tree(root / "m")
    dst = root / "run" / "m"
    dst.mkdir(parents=True)
    (dst / "measure.xml").symlink_to(bob / "target.xml")
    with pytest.raises((OSError, ValueError)):
        confined_copy.copy_tree_confined(src, dst)
    assert (bob / "target.xml").read_bytes() == SECRET


def test_excluded_and_ignored_names_are_not_copied(tmp_path, monkeypatch):
    # Validates: the OSW staging copy skips run/ and generated_files/, the package copy skips
    # .git, __pycache__ and *.pyc; neither appears in the destination
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "m")
    (src / "run").mkdir()
    (src / "run" / "eplusout.err").write_bytes(b"x")
    (src / "__pycache__").mkdir()
    (src / "__pycache__" / "m.pyc").write_bytes(b"x")
    (src / "m.pyc").write_bytes(b"x")
    dst = root / "run" / "m"
    counts = confined_copy.copy_tree_confined(
        src, dst, exclude_names={"run", "__pycache__"}, ignore=lambda name: name.endswith(".pyc"))
    assert counts["files"] == 3
    assert sorted(p.name for p in dst.iterdir()) == ["measure.rb", "measure.xml", "resources"]


@posix_only
def test_a_link_at_a_source_ancestor_fails_before_anything_is_written(tmp_path, monkeypatch):
    # Validates: the source is walked from the tenant root; a directory component that is a link
    # (planted after whatever the caller checked) fails the open and no destination is created
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    _tree(bob / "m")
    (root / "shared").symlink_to(bob, target_is_directory=True)
    dst = root / "run" / "m"
    with pytest.raises(OSError, match=r"symbolic link|Too many levels|Not a directory"):
        confined_copy.copy_tree_confined(root / "shared" / "m", dst)
    assert not dst.exists() and not (root / "run").exists()


def test_a_tree_under_no_confinement_root_is_copied_by_pathname(tmp_path, monkeypatch):
    # Validates: a server-owned source (bundled measures, the repo's assets) lies under no
    # confinement root and copies through the same API in path mode
    monkeypatch.setattr(confined_fs, "confinement_root_for", lambda _path: None)
    src = _tree(tmp_path / "bundled" / "m")
    dst = tmp_path / "out" / "m"
    counts = confined_copy.copy_tree_confined(src, dst)
    assert counts["files"] == 3 and _snapshot(dst) == _snapshot(src)


def test_remove_tree_confined_reports_whether_anything_was_there(tmp_path, monkeypatch):
    # Validates: the replacement for the rmtree-before-copytree pattern removes a directory, a
    # file or nothing, and says which, so callers need no pathname exists() check first
    root = _http_tenant(monkeypatch, tmp_path)
    d = _tree(root / "d")
    assert confined_copy.remove_tree_confined(d) is True and not d.exists()
    f = root / "f"
    f.write_bytes(b"x")
    assert confined_copy.remove_tree_confined(f) is True and not f.exists()
    assert confined_copy.remove_tree_confined(root / "absent") is False


# --- sites -------------------------------------------------------------------------------------

@posix_only
def test_copy_file_source_dir_swapped_after_the_link_check_does_not_copy_the_other_tenant(tmp_path, monkeypatch):
    # Regression: copy_file checked the source tree for escaping links, then ran shutil.copytree by
    # pathname; alice's run dir replaced by a link to bob's run dir in between copied bob's files
    # into alice's exports
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "run_x").mkdir()
    (bob / "run_x" / "secret.txt").write_bytes(SECRET)
    src = root / "run_x"
    src.mkdir()
    (src / "mine.txt").write_bytes(b"mine\n")
    real_check = results.reject_escaping_symlinks

    def check_then_swap(path):
        out = real_check(path)
        if Path(path) == src and not src.is_symlink():
            src.rename(root / "run_x_moved")
            src.symlink_to(bob / "run_x", target_is_directory=True)
        return out

    monkeypatch.setattr(results, "reject_escaping_symlinks", check_then_swap)
    res = results.copy_file(str(src))
    assert res["ok"] is False and res["error"] == "copy_failed", res
    assert not _contains_bytes(root / "exports", SECRET) if (root / "exports").exists() else True


@posix_only
def test_copy_file_destination_dir_swapped_after_creation_touches_nothing_in_the_other_tenant(tmp_path, monkeypatch):
    # Regression: copy_file created the destination dir by descriptor, then removed and re-created
    # <dest>/<name> by pathname; alice/exports replaced by a link to bob/exports in between deleted
    # bob's directory of that name and wrote alice's files into bob's tree
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "exports" / "run_x").mkdir(parents=True)
    (bob / "exports" / "run_x" / "stale.txt").write_bytes(SECRET)
    src = root / "run_x"
    src.mkdir()
    (src / "mine.txt").write_bytes(b"mine\n")
    exports = root / "exports"
    real_open = confined_fs.DirHandle.open
    swapped = []

    def open_then_swap(directory, **kw):
        handle = real_open(directory, **kw)
        if not swapped and confined_fs.lexical_abspath(directory) == exports:
            swapped.append(True)
            exports.rename(root / "exports_moved")
            exports.symlink_to(bob / "exports", target_is_directory=True)
        return handle

    monkeypatch.setattr(confined_fs.DirHandle, "open", staticmethod(open_then_swap))
    before = _snapshot(bob)
    res = results.copy_file(str(src), str(exports))
    assert res["ok"] is False, res
    assert _snapshot(bob) == before, "bob's export dir must be neither deleted nor written"


def test_copy_file_directory_copy_reports_the_file_count(tmp_path, monkeypatch):
    # Validates: the directory branch of copy_file still copies a run dir and counts its files
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "run_y")
    res = results.copy_file(str(src))
    assert res["ok"] is True, res
    assert res["type"] == "directory" and res["file_count"] == 3
    assert _snapshot(Path(res["destination"])) == _snapshot(src)


@posix_only
def test_package_measures_dir_swapped_after_the_check_is_not_cleared_or_written(tmp_path, monkeypatch):
    # Regression: the OSAF package copy checked <package>/measures/<name> resolved inside the package,
    # then removed it and copied the foundational measure in by pathname; the measures dir replaced
    # by a link to bob's package in between deleted bob's measure dir and wrote the copy there
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    name = str(analysis.FOUNDATIONAL_ANALYSIS_MEASURES[0]["measure_name"])
    (bob / "pkg" / "measures" / name).mkdir(parents=True)
    (bob / "pkg" / "measures" / name / "note.txt").write_bytes(SECRET)
    source = _tree(tmp_path / "common" / name)
    monkeypatch.setattr(analysis, "_foundational_measure_path", lambda n: tmp_path / "common" / n)
    pkg = root / "pkg"
    (pkg / "measures").mkdir(parents=True)
    real_inside = analysis._inside

    def inside_then_swap(path, package_root):
        out = real_inside(path, package_root)
        if not (pkg / "measures").is_symlink():
            (pkg / "measures").rename(pkg / "measures_moved")
            (pkg / "measures").symlink_to(bob / "pkg" / "measures", target_is_directory=True)
        return out

    monkeypatch.setattr(analysis, "_inside", inside_then_swap)
    before = _snapshot(bob)
    res = analysis._ensure_foundational_measures_in_package(pkg)
    assert res["ok"] is False and name not in res["copied"], res
    assert _snapshot(bob) == before, "bob's package must be neither cleared nor written"
    assert source.is_dir()


def test_package_foundational_measure_is_copied_without_caches(tmp_path, monkeypatch):
    # Validates: the package copy still stages the foundational measure and leaves .git,
    # __pycache__ and *.pyc behind
    root = _http_tenant(monkeypatch, tmp_path)
    name = str(analysis.FOUNDATIONAL_ANALYSIS_MEASURES[0]["measure_name"])
    source = _tree(tmp_path / "common" / name)
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "x.pyc").write_bytes(b"x")
    (source / "measure.pyc").write_bytes(b"x")
    monkeypatch.setattr(analysis, "_foundational_measure_path", lambda n: tmp_path / "common" / n)
    others = [str(s["measure_name"]) for s in analysis.FOUNDATIONAL_ANALYSIS_MEASURES[1:]]
    pkg = root / "pkg"
    pkg.mkdir()
    res = analysis._ensure_foundational_measures_in_package(pkg)
    assert res["copied"] == [name] and res["missing"] == others
    assert sorted(p.name for p in (pkg / "measures" / name).iterdir()) == ["measure.rb", "measure.xml", "resources"]


@posix_only
def test_osw_staging_copy_does_not_follow_a_link_to_another_tenant(tmp_path, monkeypatch):
    # Regression: run_osw staged the OSW's directory with shutil.copytree / copy2, which follow
    # links; a link planted in the directory after the escaping-link check copied the target's
    # bytes into the run dir. The copy now fails on the link
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "secret.txt").write_bytes(SECRET)
    src = root / "osw_dir"
    src.mkdir()
    (src / "workflow.osw").write_bytes(b"{}")
    (src / "files").mkdir()
    (src / "files" / "weather.epw").symlink_to(bob / "secret.txt")
    run_dir = root / "run_osw"
    run_dir.mkdir()
    with pytest.raises((OSError, ValueError)):
        sim_ops._copy_tree(src, run_dir)
    assert not _contains_bytes(run_dir, SECRET)


def test_osw_staging_copy_skips_generated_dirs(tmp_path, monkeypatch):
    # Validates: run_osw's staging copy still skips run/ and generated_files/ from a repo asset dir
    root = _http_tenant(monkeypatch, tmp_path)
    src = root / "osw_dir"
    (src / "run").mkdir(parents=True)
    (src / "run" / "eplusout.sql").write_bytes(b"x")
    (src / "generated_files").mkdir()
    (src / "files").mkdir()
    (src / "files" / "w.epw").write_bytes(b"epw\n")
    (src / "workflow.osw").write_bytes(b"{}")
    run_dir = root / "run_osw"
    sim_ops._copy_tree(src, run_dir)
    assert sorted(str(p.relative_to(run_dir)) for p in run_dir.rglob("*")) == ["files", "files/w.epw", "workflow.osw"]
