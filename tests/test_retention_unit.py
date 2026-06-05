"""Unit: the retention sweep deletes the right run dirs and spares the rest.

Pure filesystem logic — crafts run dirs under tmp_path and runs the sweep with a
fixed clock, so age/pin/active/run-dir predicates are all checked deterministically
without Docker, OpenStudio, or a real simulation.
"""
import json
import os
from pathlib import Path

import pytest

from mcp_server.skills.simulation.retention import _run_root_is_sane, _sweep_user_root

NOW = 2_000_000_000.0
OLD = NOW - 100 * 86400      # 100 days old
FRESH = NOW - 3600           # 1 hour old
WEEK = 7 * 86400


def _mk(root, name, record=None, *, out_osw=False, pinned=False, payload=2048):
    d = root / name
    d.mkdir()
    if record is not None:
        (d / "run_record.json").write_text(json.dumps(record))
    if out_osw:
        (d / "out.osw").write_text("{}")
    if pinned:
        (d / ".pinned").write_text("pinned\n")
    (d / "blob.bin").write_bytes(b"x" * payload)
    return d


@pytest.mark.unit
def test_sweep_deletes_old_terminal_runs_only(tmp_path):
    # Validates: GC removes terminal run dirs past the age cutoff, and spares
    # fresh / pinned / queued / running / non-run dirs — the core retention policy.
    _mk(tmp_path, "succ_old", {"status": "success", "ended_at": OLD})
    _mk(tmp_path, "cxl_old", {"status": "cancelled", "ended_at": OLD})
    _mk(tmp_path, "fail_old", {"status": "failed", "ended_at": OLD})
    _mk(tmp_path, "running_dead", {"status": "running", "pid": 999_999, "ended_at": OLD})
    _mk(tmp_path, "outosw_old", out_osw=True)  # no record -> mtime fallback (huge vs NOW)

    _mk(tmp_path, "succ_fresh", {"status": "success", "ended_at": FRESH})       # too young
    _mk(tmp_path, "queued_old", {"status": "queued", "created_at": OLD})        # active
    _mk(tmp_path, "running_alive", {"status": "running", "pid": os.getpid(), "created_at": OLD})
    _mk(tmp_path, "pinned_old", {"status": "success", "ended_at": OLD}, pinned=True)
    _mk(tmp_path, "examples", {"status": "success", "ended_at": OLD})           # excluded by name
    stray = tmp_path / "stray"
    stray.mkdir()
    (stray / "notes.txt").write_text("not a run")                              # not a run dir

    recs, freed = _sweep_user_root(
        tmp_path, "u", WEEK, NOW, dry_run=False, reason="gc")

    deleted = {r["run_id"] for r in recs}
    assert deleted == {"succ_old", "cxl_old", "fail_old", "running_dead", "outosw_old"}, deleted
    assert freed > 0, "deleting 5 run dirs must free bytes"

    for gone in ("succ_old", "cxl_old", "fail_old", "running_dead", "outosw_old"):
        assert not (tmp_path / gone).exists(), f"{gone} should be deleted"
    for kept in ("succ_fresh", "queued_old", "running_alive", "pinned_old", "examples", "stray"):
        assert (tmp_path / kept).exists(), f"{kept} must be spared"


@pytest.mark.unit
def test_sweep_dry_run_deletes_nothing(tmp_path):
    # Validates: dry_run previews candidates without touching the filesystem.
    _mk(tmp_path, "succ_old", {"status": "success", "ended_at": OLD})

    recs, freed = _sweep_user_root(
        tmp_path, "u", WEEK, NOW, dry_run=True, reason="cleanup")

    assert [r["run_id"] for r in recs] == ["succ_old"]
    assert freed > 0
    assert (tmp_path / "succ_old").exists(), "dry_run must not delete"


@pytest.mark.unit
def test_sweep_never_follows_symlink_out_of_tree(tmp_path):
    # Regression: GC must never delete (or follow) a symlink — a run-shaped link
    # pointing outside the swept tree, and its target, must be left untouched.
    user_root = tmp_path / "user"
    user_root.mkdir()
    real = _mk(user_root, "real_old", {"status": "success", "ended_at": OLD})

    outside = tmp_path / "outside_secret"   # stands in for "anything outside the MCP"
    outside.mkdir()
    (outside / "important.txt").write_text("do not delete")
    (outside / "out.osw").write_text("{}")  # makes the link *look* like a run dir
    link = user_root / "evil_link"
    link.symlink_to(outside, target_is_directory=True)

    recs, _freed = _sweep_user_root(user_root, "u", WEEK, NOW, dry_run=False, reason="gc")

    assert {r["run_id"] for r in recs} == {"real_old"}, "only the real run is reclaimed"
    assert not real.exists()
    assert link.is_symlink(), "the symlink itself must be left in place"
    assert outside.exists() and (outside / "important.txt").exists(), \
        "external target must survive — GC cannot escape via symlink"


@pytest.mark.unit
@pytest.mark.parametrize(("path", "sane"), [
    ("/runs", True), ("/runs/sub", True), ("/data/openstudio/runs", True),
    ("/", False), ("/home", False), ("/tmp", False), ("/etc", False), ("/var", False),  # noqa: S108
])
def test_run_root_sanity_guard(path, sane):
    # Validates: the daemon refuses to sweep a filesystem/system root, so a
    # misconfigured OSMCP_RUN_ROOT can never turn GC loose on real data.
    assert _run_root_is_sane(Path(path)) is sane
