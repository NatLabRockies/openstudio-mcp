"""read_file, get_run_artifacts and the tree removals under tenant-writable trees open the path they
authorized by directory descriptor, so a component swapped for a link after the check is refused
instead of followed (issue #190, part 3)."""
import sys
from pathlib import Path

import pytest
from test_analysis_tools import _http_tenant

from mcp_server import config, confined_copy
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
    # agents reading repo assets through a link are not broken by the tenant-tree hardening
    _http_tenant(monkeypatch, tmp_path)
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "real.txt").write_bytes(b"asset\n")
    (shared / "link.txt").symlink_to(shared / "real.txt")
    monkeypatch.setattr(config, "_SHARED_READ_ROOTS", [*config._SHARED_READ_ROOTS, shared.resolve()])
    res = results.read_file(str(shared / "link.txt"))
    assert res["ok"] is True and res["text"] == "asset\n", res


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
