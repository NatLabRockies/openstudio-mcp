"""read_file, get_run_artifacts and the tree removals under tenant-writable trees open the path they
authorized by directory descriptor, so a component swapped for a link after the check is refused
instead of followed (issue #190, part 3)."""
import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

import pytest
from test_analysis_tools import _http_tenant

from mcp_server import config, confined_copy, confined_fs
from mcp_server.skills.results import operations as results
from mcp_server.skills.simulation import operations as sim_ops

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and dir_fd")

SECRET = b"bob's private bytes\n"


def _contains_bytes(tree: Path, needle: bytes) -> bool:
    return any(p.is_file() and not p.is_symlink() and p.read_bytes() == needle for p in tree.rglob("*"))


@posix_only
def test_read_file_source_dir_swapped_after_the_allow_check_does_not_read_the_other_tenant(tmp_path, monkeypatch):
    # Regression: read_file authorized the resolved path, then opened it by pathname; alice's run
    # dir replaced by a link to bob's run dir in between returned bob's file with ok: True
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "run_x").mkdir()
    (bob / "run_x" / "report.txt").write_bytes(SECRET)
    src = root / "run_x"
    src.mkdir()
    (src / "report.txt").write_bytes(b"mine\n")
    real_allowed = config.is_path_allowed

    def allow_then_swap(p, *, write=False):
        out = real_allowed(p, write=write)
        if Path(p) == src / "report.txt" and not src.is_symlink():
            src.rename(root / "run_x_moved")
            src.symlink_to(bob / "run_x", target_is_directory=True)
        return out

    monkeypatch.setattr(config, "is_path_allowed", allow_then_swap)
    res = results.read_file(str(src / "report.txt"))
    assert res["ok"] is False and res["error"] == "read_failed", res
    assert SECRET.decode() not in repr(res)


def test_read_file_reads_with_offset_and_reports_truncation(tmp_path, monkeypatch):
    # Validates: the descriptor-opened read keeps the chunked contract: offset applies, bytes_read
    # and truncated follow from the file size, text is decoded
    root = _http_tenant(monkeypatch, tmp_path)
    f = root / "run_y" / "log.txt"
    f.parent.mkdir()
    f.write_bytes(b"0123456789")
    res = results.read_file(str(f), max_bytes=4, offset=3)
    assert res["ok"] is True, res
    assert (res["text"], res["bytes_read"], res["file_size"], res["truncated"]) == ("3456", 4, 10, True)
    res = results.read_file(str(f), max_bytes=50, offset=8)
    assert (res["text"], res["truncated"]) == ("89", False)


@posix_only
def test_read_file_under_a_shared_read_root_still_follows_the_servers_own_links(tmp_path, monkeypatch):
    # Validates: the shared read-only roots (repo assets, bundled measures) are server-owned and
    # lie under no confinement root; a link the server itself placed there stays readable, so
    # agents reading repo assets through a link are not broken by the tenant-tree hardening.
    # The shared dir is made under the repo's runs/ (tmp_path lies under the temp confinement
    # root and would take the descriptor branch instead).
    _http_tenant(monkeypatch, tmp_path)
    shared = Path(tempfile.mkdtemp(prefix="shared_root_", dir=Path.cwd() / "runs"))
    try:
        assert confined_fs.confinement_root_for(shared) is None, "precondition: outside every confinement root"
        (shared / "real.txt").write_bytes(b"asset\n")
        (shared / "link.txt").symlink_to(shared / "real.txt")
        monkeypatch.setattr(config, "_SHARED_READ_ROOTS", [*config._SHARED_READ_ROOTS, shared.resolve()])
        res = results.read_file(str(shared / "link.txt"))
        assert res["ok"] is True and res["text"] == "asset\n", res
    finally:
        shutil.rmtree(shared, ignore_errors=True)


@posix_only
@pytest.mark.parametrize("target_exists", [True, False])
def test_read_file_swapped_dir_gives_the_same_refusal_whether_the_other_tenants_file_exists(
        tmp_path, monkeypatch, target_exists):
    # Regression: after authorization, read_file still ran exists()/is_file() by pathname before the
    # descriptor open; through a swapped directory those answered about bob's tree, so not_found
    # versus read_failed told alice whether a guessed file existed in bob's run. Both cases now
    # fail identically at the descriptor walk
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "output").mkdir()
    if target_exists:
        (bob / "output" / "guess.txt").write_bytes(SECRET)
    src = root / "run_x" / "output"
    src.mkdir(parents=True)
    (src / "guess.txt").write_bytes(b"mine\n")
    real_allowed = config.is_path_allowed

    def allow_then_swap(p, *, write=False):
        out = real_allowed(p, write=write)
        if Path(p) == src / "guess.txt" and not src.is_symlink():
            src.rename(root / "run_x" / "output_moved")
            src.symlink_to(bob / "output", target_is_directory=True)
        return out

    monkeypatch.setattr(config, "is_path_allowed", allow_then_swap)
    res = results.read_file(str(src / "guess.txt"))
    assert res["ok"] is False and res["error"] == "read_failed", res
    assert "guess.txt" not in res["message"].split(":")[-1] or SECRET.decode() not in repr(res)


def test_read_file_missing_file_and_directory_are_not_found(tmp_path, monkeypatch):
    # Validates: within the caller's own tree the pre-#190 answers hold: a missing file and a
    # directory are not_found, not read_failed
    root = _http_tenant(monkeypatch, tmp_path)
    (root / "run_y").mkdir()
    assert results.read_file(str(root / "run_y" / "absent.txt"))["error"] == "not_found"
    assert results.read_file(str(root / "run_y"))["error"] == "not_found"


def test_read_file_maps_read_errors_and_absurd_offsets_to_a_tool_error(tmp_path, monkeypatch):
    # Regression: a failure after the open (a seek past what the platform accepts, an I/O error)
    # raised through the tool; every failure is now read_failed
    root = _http_tenant(monkeypatch, tmp_path)
    f = root / "run_y" / "log.txt"
    f.parent.mkdir()
    f.write_bytes(b"0123456789")
    res = results.read_file(str(f), offset=2**63)
    assert res["ok"] is False and res["error"] == "read_failed", res


@posix_only
def test_get_run_artifacts_run_dir_swapped_after_lookup_does_not_list_the_other_tenant(tmp_path, monkeypatch):
    # Regression: get_run_artifacts resolved the run dir, then listed <run>/run by pathname; the
    # run dir replaced by a link to bob's run in between listed bob's artifact names and sizes
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "run_x" / "run").mkdir(parents=True)
    (bob / "run_x" / "run" / "bobs_secret_report.html").write_bytes(SECRET)
    run_dir = root / "run_x"
    (run_dir / "run").mkdir(parents=True)
    (run_dir / "run" / "eplusout.err").write_bytes(b"ok\n")
    monkeypatch.setattr(sim_ops, "_get_run_record", lambda _run_id: None)
    real_resolve = sim_ops.resolve_run_dir

    def resolve_then_swap(run_root, run_id):
        out = real_resolve(run_root, run_id)
        if not run_dir.is_symlink():
            run_dir.rename(root / "run_x_moved")
            run_dir.symlink_to(bob / "run_x", target_is_directory=True)
        return out

    monkeypatch.setattr(sim_ops, "resolve_run_dir", resolve_then_swap)
    res = sim_ops.get_run_artifacts("run_x")
    assert "bobs_secret_report" not in repr(res), res
    assert res["ok"] is False or res["artifacts"] == [], res


def test_get_run_artifacts_lists_files_and_shallow_children(tmp_path, monkeypatch):
    # Validates: the descriptor-walked listing keeps the contract agents rely on: out.osw with
    # its size, run/ with its children (name, is_dir, size for files), links skipped
    root = _http_tenant(monkeypatch, tmp_path)
    run_dir = root / "run_z"
    (run_dir / "run" / "sub").mkdir(parents=True)
    (run_dir / "out.osw").write_bytes(b"{}")
    (run_dir / "run" / "eplusout.sql").write_bytes(b"sqlite")
    if sys.platform != "win32":
        (run_dir / "run" / "link").symlink_to(run_dir / "out.osw")
    monkeypatch.setattr(sim_ops, "_get_run_record", lambda _run_id: None)
    res = sim_ops.get_run_artifacts("run_z")
    assert res["ok"] is True, res
    by_name = {a["name"]: a for a in res["artifacts"]}
    assert by_name["out.osw"] == {"path": str(run_dir / "out.osw"), "name": "out.osw", "is_dir": False, "size": 2}
    children = by_name["run"]["children"]
    assert [c["name"] for c in children] == ["eplusout.sql", "sub"]
    assert children[0]["size"] == 6 and children[0]["is_dir"] is False
    assert children[1]["size"] is None and children[1]["is_dir"] is True


@posix_only
def test_remove_tree_confined_refuses_a_link_at_the_parent_and_keeps_the_target(tmp_path, monkeypatch):
    # Validates: the replacement for shutil.rmtree(path) opens the parent by descriptor; a parent
    # component that is a link fails (raised, or swallowed with ignore_errors) and the tree the
    # link points at keeps every byte
    root = _http_tenant(monkeypatch, tmp_path)
    bob = root.parent / "bob"
    (bob / "work" / "d").mkdir(parents=True)
    (bob / "work" / "d" / "keep.txt").write_bytes(SECRET)
    (root / "work").symlink_to(bob / "work", target_is_directory=True)
    with pytest.raises(OSError, match=r"symbolic link|Too many levels|Not a directory"):
        confined_copy.remove_tree_confined(root / "work" / "d")
    assert confined_copy.remove_tree_confined(root / "work" / "d", ignore_errors=True) is False
    assert (bob / "work" / "d" / "keep.txt").read_bytes() == SECRET
    assert str((root / "work").readlink()) == str(bob / "work")


def test_remove_tree_confined_with_ignore_errors_keeps_removing_after_a_failed_entry(tmp_path, monkeypatch):
    # Regression: ignore_errors swallowed the first error around the whole removal, so one entry
    # that could not be unlinked left every sibling behind (shutil.rmtree(ignore_errors=True) kept
    # going); the removal now continues past the failure and reports the tree as not fully removed
    root = _http_tenant(monkeypatch, tmp_path)
    d = root / "stale"
    (d / "sub").mkdir(parents=True)
    (d / "sub" / "b.txt").write_bytes(b"b")
    (d / "a.txt").write_bytes(b"a")
    (d / "c.txt").write_bytes(b"c")
    real_unlink = os.unlink

    def unlink_refusing_a(name, *args, **kwargs):
        if Path(name).name == "a.txt":
            raise PermissionError(1, "Operation not permitted", str(name))
        return real_unlink(name, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", unlink_refusing_a)
    assert confined_copy.remove_tree_confined(d, ignore_errors=True) is False
    assert sorted(str(p.relative_to(d)) for p in d.rglob("*")) == ["a.txt"], "every removable entry is gone"
    monkeypatch.undo()
    assert confined_copy.remove_tree_confined(d) is True and not d.exists()


@posix_only
def test_read_file_fifo_under_a_shared_read_root_is_not_found_without_blocking(tmp_path, monkeypatch):
    # Regression: the plain open used for shared read roots blocked on a FIFO with no writer
    # before fstat could reject it (the removed is_file() check used to answer not_found); the
    # open is non-blocking and the FIFO is not_found at once
    _http_tenant(monkeypatch, tmp_path)
    shared = Path(tempfile.mkdtemp(prefix="shared_root_", dir=Path.cwd() / "runs"))
    try:
        assert confined_fs.confinement_root_for(shared) is None
        os.mkfifo(shared / "pipe")
        monkeypatch.setattr(config, "_SHARED_READ_ROOTS", [*config._SHARED_READ_ROOTS, shared.resolve()])
        box: dict[str, object] = {}
        worker = threading.Thread(target=lambda: box.update(res=results.read_file(str(shared / "pipe"))), daemon=True)
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive(), "read_file blocked on the FIFO"
        assert box["res"]["ok"] is False and box["res"]["error"] == "not_found", box["res"]
    finally:
        shutil.rmtree(shared, ignore_errors=True)


def test_read_file_closes_the_descriptor_when_the_type_check_fails(tmp_path, monkeypatch):
    # Regression: on the shared-root branch an fstat failure after the open returned read_failed
    # with the descriptor still open; repeated failures would exhaust descriptors
    _http_tenant(monkeypatch, tmp_path)
    shared = Path(tempfile.mkdtemp(prefix="shared_root_", dir=Path.cwd() / "runs"))
    try:
        assert confined_fs.confinement_root_for(shared) is None
        (shared / "a.txt").write_bytes(b"a")
        monkeypatch.setattr(config, "_SHARED_READ_ROOTS", [*config._SHARED_READ_ROOTS, shared.resolve()])
        opened: list[int] = []
        closed: list[int] = []
        real_open, real_close, real_fstat = os.open, os.close, os.fstat

        def tracking_open(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            opened.append(fd)
            return fd

        def tracking_close(fd):
            closed.append(fd)
            return real_close(fd)

        def failing_fstat(fd):
            if fd in opened:
                raise OSError(5, "Input/output error")
            return real_fstat(fd)

        monkeypatch.setattr(os, "open", tracking_open)
        monkeypatch.setattr(os, "close", tracking_close)
        monkeypatch.setattr(os, "fstat", failing_fstat)
        res = results.read_file(str(shared / "a.txt"))
        assert res["ok"] is False and res["error"] == "read_failed", res
        assert opened and sorted(closed) == sorted(opened), "every descriptor opened by read_file is closed"
    finally:
        shutil.rmtree(shared, ignore_errors=True)
