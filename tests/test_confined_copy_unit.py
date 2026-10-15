"""confined_copy.copy_tree_confined / remove_tree_confined and the tree-copy sites that used
shutil.copytree: measure staging, copy_file's directory copies, the OSAF package's foundational
measures and the OSW staging copy. Both trees are walked by directory descriptor, so a component
swapped for a link after the caller's check fails the copy instead of redirecting it into or out of
another tenant's tree (issue #190, part 2)."""
import json
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
    ("resources/../measure.xml", "refused"),  # stays inside lexically, but ".." is never kept
    ("../m/measure.xml", "refused"),  # re-enters by the tree's own name: still leaves
    ("../../bob/secret.txt", "refused"),
    ("/etc/hostname", "refused"),
])
def test_links_are_recreated_only_when_relative_and_descending(tmp_path, monkeypatch, target, outcome):
    # Validates: copytree(symlinks=True) recreated every link as written; the descriptor copy keeps a
    # link only when it is relative and has no ".." component (such links can only resolve to a
    # descendant of their own directory, however they chain) and refuses every other one even
    # though the pathname pre-check passed (a swap)
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
def test_chained_links_cannot_compose_an_escape(tmp_path, monkeypatch):
    # Regression: a tree with a/up -> .. and link -> a/up/../x passed a per-link lexical check
    # (each target stays inside on paper) while the chain resolved outside the tree; the copy
    # now refuses the ".." link itself, so no kept link can resolve above the copied tree
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "m")
    (src / "a").mkdir()
    (src / "a" / "up").symlink_to("..")
    (src / "link").symlink_to("a/up/../measure.xml")
    dst = root / "run" / "m"
    with pytest.raises(ValueError, match="link"):
        confined_copy.copy_tree_confined(src, dst)
    for p in dst.rglob("*") if dst.exists() else []:
        if p.is_symlink():
            assert ".." not in str(p.readlink()), f"kept link {p} could climb out of the copied tree"


@posix_only
def test_directory_permission_bits_are_preserved(tmp_path, monkeypatch):
    # Regression: only regular files kept their mode; a private 0o700 export dir and a 0o750
    # sub-directory came out 0o755 (wider than the source), where copytree preserved them
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "m")
    (src / "resources").chmod(0o750)
    src.chmod(0o700)
    dst = root / "run" / "m"
    confined_copy.copy_tree_confined(src, dst)
    assert stat.S_IMODE(dst.stat().st_mode) == 0o700
    assert stat.S_IMODE((dst / "resources").stat().st_mode) == 0o750


def test_replace_with_a_missing_parent_creates_the_destination(tmp_path, monkeypatch):
    # Regression: replace=True raised FileNotFoundError while looking for a stale destination
    # under a parent that did not exist yet, although the API promises to create missing parents
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "m")
    dst = root / "new" / "deeper" / "m"
    counts = confined_copy.copy_tree_confined(src, dst, replace=True)
    assert counts["files"] == 3 and _snapshot(dst) == _snapshot(src)


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
    (dst / "measure.xml").unlink()
    (dst / "measure.xml").mkdir()
    (dst / "measure.xml" / "inner").write_bytes(b"inner\n")
    with pytest.raises((OSError, ValueError)):
        confined_copy.copy_tree_confined(src, dst)
    assert (dst / "measure.xml" / "inner").read_bytes() == b"inner\n"


def test_excluded_names_apply_at_the_top_only_and_ignored_names_everywhere(tmp_path, monkeypatch):
    # Regression: exclude_names was applied at every depth, so an OSW dir's resources/run/needed
    # vanished from the staged run; the OSW copy skips run/ and generated_files/ at the top level
    # only (as the iterdir loop it replaced did), while ignore() still prunes caches everywhere
    root = _http_tenant(monkeypatch, tmp_path)
    src = _tree(root / "m")
    (src / "run").mkdir()
    (src / "run" / "eplusout.err").write_bytes(b"x")
    (src / "resources" / "run").mkdir()
    (src / "resources" / "run" / "needed.csv").write_bytes(b"needed\n")
    (src / "resources" / "__pycache__").mkdir()
    (src / "resources" / "__pycache__" / "m.pyc").write_bytes(b"x")
    (src / "m.pyc").write_bytes(b"x")
    dst = root / "run" / "m"
    counts = confined_copy.copy_tree_confined(
        src, dst, exclude_names={"run"}, ignore=lambda name: name == "__pycache__" or name.endswith(".pyc"))
    assert counts["files"] == 4
    assert sorted(p.name for p in dst.iterdir()) == ["measure.rb", "measure.xml", "resources"]
    assert (dst / "resources" / "run" / "needed.csv").read_bytes() == b"needed\n"
    assert not (dst / "resources" / "__pycache__").exists()


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
    (source / ".git").mkdir()
    (source / ".git" / "HEAD").write_bytes(b"ref\n")
    (source / "__pycache__").mkdir()
    (source / "__pycache__" / "x.pyc").write_bytes(b"x")
    (source / "resources" / "__pycache__").mkdir()
    (source / "resources" / "__pycache__" / "y.pyc").write_bytes(b"x")
    (source / "measure.pyc").write_bytes(b"x")
    monkeypatch.setattr(analysis, "_foundational_measure_path", lambda n: tmp_path / "common" / n)
    others = [str(s["measure_name"]) for s in analysis.FOUNDATIONAL_ANALYSIS_MEASURES[1:]]
    pkg = root / "pkg"
    pkg.mkdir()
    res = analysis._ensure_foundational_measures_in_package(pkg)
    assert res["copied"] == [name] and res["missing"] == others
    assert sorted(p.name for p in (pkg / "measures" / name).iterdir()) == ["measure.rb", "measure.xml", "resources"]
    assert sorted(p.name for p in (pkg / "measures" / name / "resources").iterdir()) == ["data.csv"]


@posix_only
def test_package_dir_swapped_before_measures_is_created_makes_nothing_in_the_other_tenant(tmp_path, monkeypatch):
    # Regression: after checking that <package>/measures was not a link, the package copy created
    # it with mkdir(parents=True) by pathname; the package dir replaced by a link to bob's package
    # in between created bob/pkg/measures before the containment check refused the copy
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "pkg").mkdir()
    pkg = root / "pkg"
    pkg.mkdir()
    monkeypatch.setattr(analysis, "_foundational_measure_path", lambda n: tmp_path / "common" / n)
    real_is_symlink = Path.is_symlink

    def is_symlink_then_swap(self):
        out = real_is_symlink(self)
        if self == pkg / "measures" and not real_is_symlink(pkg):
            pkg.rename(root / "pkg_moved")
            pkg.symlink_to(bob / "pkg", target_is_directory=True)
        return out

    monkeypatch.setattr(Path, "is_symlink", is_symlink_then_swap)
    before = _snapshot(bob)
    res = analysis._ensure_foundational_measures_in_package(pkg)
    assert res["ok"] is False and res["copied"] == [], res
    assert _snapshot(bob) == before, "no directory may be created in bob's package"


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


def _osw_run_setup(monkeypatch):
    """run_osw up to staging: validation stubbed, nothing enqueued, so staging decides the outcome."""
    monkeypatch.setattr(sim_ops, "validate_osw", lambda *_a, **_k: {"ok": True, "osw": {}})
    monkeypatch.setattr(sim_ops, "_enqueue", lambda *_a: None)


@posix_only
def test_run_osw_does_not_resolve_the_osw_dir_again_after_the_check(tmp_path, monkeypatch):
    # Regression: run_osw authorized the resolved OSW path, then resolved its parent a second time
    # before staging; alice's OSW dir replaced by a link to bob's dir in between resolved to bob's
    # real path, which the descriptor walk then copied without seeing a link
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "osw_dir").mkdir()
    (bob / "osw_dir" / "workflow.osw").write_text("{}", encoding="utf-8")
    (bob / "osw_dir" / "secret.txt").write_bytes(SECRET)
    src = root / "osw_dir"
    src.mkdir()
    (src / "workflow.osw").write_text("{}", encoding="utf-8")
    _osw_run_setup(monkeypatch)
    real_check = sim_ops.reject_escaping_symlinks

    def check_then_swap(path):
        out = real_check(path)
        if Path(path) == src and not src.is_symlink():
            src.rename(root / "osw_dir_moved")
            src.symlink_to(bob / "osw_dir", target_is_directory=True)
        return out

    monkeypatch.setattr(sim_ops, "reject_escaping_symlinks", check_then_swap)
    res = sim_ops.run_osw(str(src / "workflow.osw"), _internal=True)
    assert res["ok"] is False and "stage" in res["error"], res
    assert not _contains_bytes(root, SECRET), "bob's file must not be staged into alice's run dir"


def test_run_osw_seed_outside_the_osw_dir_over_budget_is_a_tool_error(tmp_path, monkeypatch):
    # Regression: the seed and OSW fallback copies sat outside run_osw's staging error handling, so
    # an over-budget (or swapped) seed raised through the tool; a ../ seed reference is staged
    # lexically (no resolve after the check) and a failure is {"ok": False}
    root = _http_tenant(monkeypatch, tmp_path)
    src = root / "osw_dir"
    src.mkdir()
    (root / "seed.osm").write_bytes(b"OS:Version,\n" * 4)
    (src / "workflow.osw").write_text(json.dumps({"seed_file": "../seed.osm"}), encoding="utf-8")
    _osw_run_setup(monkeypatch)
    monkeypatch.setattr(sim_ops, "MAX_STAGED_FILE_BYTES", 8)
    res = sim_ops.run_osw(str(src / "workflow.osw"), _internal=True)
    assert res["ok"] is False and "seed.osm" in res["error"] and "exceeds" in res["error"], res
    monkeypatch.setattr(sim_ops, "MAX_STAGED_FILE_BYTES", 1 << 20)
    res = sim_ops.run_osw(str(src / "workflow.osw"), _internal=True)
    assert res["ok"] is True, res
    staged = Path(res["run_dir"])
    assert (staged / "seed.osm").read_bytes() == b"OS:Version,\n" * 4
    assert json.loads((staged / "workflow.osw").read_text(encoding="utf-8"))["seed_file"] == "seed.osm"
