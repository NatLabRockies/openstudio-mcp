"""results.sql_open: eplusout.sql is read through a private copy made from the descriptor-walked
source, so SQLite never opens a path in the tenant's run dir and a run-dir component swapped for a
link at any moment cannot hand the extractors another tenant's database (issue #190, part 1)."""
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
from test_analysis_tools import _http_tenant

from mcp_server import confined_fs
from mcp_server.skills.results import operations as results
from mcp_server.skills.results import sql_open

pytestmark = pytest.mark.unit
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks and dir_fd")


def _result_db(path: Path, variable: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE ReportDataDictionary (Name, KeyValue, ReportingFrequency, Units, IsMeter)")
    conn.execute("INSERT INTO ReportDataDictionary VALUES (?, 'Env', 'Hourly', 'C', 0)", (variable,))
    conn.commit()
    conn.close()


def _names(conn: sqlite3.Connection) -> list[str]:
    try:
        return [r[0] for r in conn.execute("SELECT Name FROM ReportDataDictionary").fetchall()]
    finally:
        conn.close()


def _temp_copies() -> list[str]:
    return sorted(p.name for p in Path(tempfile.gettempdir()).iterdir() if p.name.startswith(sql_open._COPY_PREFIX))


@posix_only
def test_connects_to_a_private_copy_read_only_and_leaves_nothing_behind(tmp_path, monkeypatch):
    # Validates: rows come back, the connection refuses writes, the tenant's run dir gains no
    # sidecar files, and the private copy is unlinked as soon as SQLite holds it (no temp file
    # with the copy prefix remains while or after the connection is used)
    root = _http_tenant(monkeypatch, tmp_path)
    db = root / "run_a" / "run" / "eplusout.sql"
    _result_db(db, "Zone Air Temperature")
    before = _temp_copies()
    conn = sql_open.connect_sql_readonly(db)
    assert _temp_copies() == before, "the copy's name is gone once SQLite has it open"
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO ReportDataDictionary VALUES ('x', 'y', 'z', 'u', 0)")
    assert _names(conn) == ["Zone Air Temperature"]
    assert sorted(p.name for p in db.parent.iterdir()) == ["eplusout.sql"]
    assert _temp_copies() == before


@posix_only
def test_run_dir_swapped_right_after_the_descriptor_open_still_reads_the_tenants_own_rows(tmp_path, monkeypatch):
    # Validates: SQLite never opens the tenant's path. A pathname handed to SQLite (even
    # /proc/self/fd/<n>, which its VFS resolves back to a pathname before its own open) leaves
    # a window inside SQLite between that resolution and the open; the copy made from the
    # server's descriptor has no such window, so a swap after the server's open changes nothing
    root = _http_tenant(monkeypatch, tmp_path)
    run_dir = root / "run_c"
    _result_db(run_dir / "run" / "eplusout.sql", "Alice Var")
    bob_run = root.parent / "bob" / "run_c" / "run"
    _result_db(bob_run / "eplusout.sql", "Bob Var")
    real_open_file = confined_fs.DirHandle.open_file

    def open_then_swap(self, name, *args, **kwargs):
        fd = real_open_file(self, name, *args, **kwargs)
        if name == "eplusout.sql" and not (run_dir / "run").is_symlink():
            (run_dir / "run").rename(run_dir / "run_moved")
            (run_dir / "run").symlink_to(bob_run, target_is_directory=True)
        return fd

    monkeypatch.setattr(confined_fs.DirHandle, "open_file", open_then_swap)
    assert _names(sql_open.connect_sql_readonly(run_dir / "run" / "eplusout.sql")) == ["Alice Var"]


@posix_only
def test_run_dir_component_swapped_after_the_lookup_never_reaches_the_other_tenants_database(tmp_path, monkeypatch):
    # Regression: _find_first_existing checked run/eplusout.sql by pathname and the extractor
    # then called sqlite3.connect(str(path)), which reopened it by name; run/ swapped for a
    # link to bob's run dir in between returned bob's variables as alice's. The open is now
    # anchored to the tenant root and the swap is a tool error.
    root = _http_tenant(monkeypatch, tmp_path)
    run_dir = root / "run_sql_1"
    _result_db(run_dir / "run" / "eplusout.sql", "Alice Var")
    bob_run = root.parent / "bob" / "run_sql_1" / "run"
    _result_db(bob_run / "eplusout.sql", "Bob Var")
    real_find = results._find_first_existing

    def find_then_swap(rd, candidates):
        found = real_find(rd, candidates)
        if found is not None and not (run_dir / "run").is_symlink():
            (run_dir / "run").rename(run_dir / "run_moved")
            (run_dir / "run").symlink_to(bob_run, target_is_directory=True)
        return found

    monkeypatch.setattr(results, "_find_first_existing", find_then_swap)
    res = results.list_output_variables_op("run_sql_1")
    assert res["ok"] is False and res["error"] == "sql_unreadable", res
    assert "Bob Var" not in repr(res)


@posix_only
def test_a_link_at_an_ancestor_component_is_refused(tmp_path, monkeypatch):
    # Validates: the copy is made from the descriptor walk, so a linked directory on the way
    # fails instead of reaching the database behind it, and no temp copy is left
    root = _http_tenant(monkeypatch, tmp_path)
    other = root.parent / "bob" / "elsewhere"
    _result_db(other / "run" / "eplusout.sql", "Decoy")
    (root / "run_d").symlink_to(other, target_is_directory=True)
    before = _temp_copies()
    with pytest.raises(OSError, match=r"symbolic link|Not a directory"):
        sql_open.connect_sql_readonly(root / "run_d" / "run" / "eplusout.sql")
    assert _temp_copies() == before


def test_a_path_under_no_confinement_root_is_opened_by_pathname_read_only(tmp_path, monkeypatch):
    # Validates: shared read-only roots and test fixtures keep the direct read-only open
    _http_tenant(monkeypatch, tmp_path)
    monkeypatch.setattr(confined_fs, "confinement_root_for", lambda _path: None)
    db = tmp_path / "fixture" / "eplusout.sql"
    _result_db(db, "Fixture")
    before = _temp_copies()
    conn = sql_open.connect_sql_readonly(db)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM ReportDataDictionary")
    assert _names(conn) == ["Fixture"]
    assert _temp_copies() == before


def test_sqlite_errors_are_tool_errors(tmp_path, monkeypatch):
    # Regression: a result file without the expected tables raised sqlite3.OperationalError out
    # of the extraction tools; every public extraction path returns {"ok": False, ...} now
    root = _http_tenant(monkeypatch, tmp_path)
    db = root / "run_e" / "run" / "eplusout.sql"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE Unrelated (x)")
    conn.commit()
    conn.close()
    res = results.list_output_variables_op("run_e")
    assert res["ok"] is False and res["error"] == "sql_error", res
    assert "ReportDataDictionary" in res["message"]


def test_a_corrupt_result_file_fails_summary_and_comparison_instead_of_reporting_null_success(tmp_path, monkeypatch):
    # Regression: extract_summary_metrics returned ok=True with null metrics, and compare_runs
    # ok=True with zero totals, when eplusout.sql existed but could not be read
    root = _http_tenant(monkeypatch, tmp_path)
    for run_id in ("run_j", "run_k"):
        bad = root / run_id / "run" / "eplusout.sql"
        bad.parent.mkdir(parents=True)
        bad.write_bytes(b"this is not a database" * 100)
    summary = results.extract_summary_metrics("run_j")
    assert summary["ok"] is False and summary["error"] == "sql_error", summary
    assert "not a database" in summary["message"]
    compared = results.compare_runs_op("run_j", "run_k")
    assert compared["ok"] is False and compared["error"] == "sql_error", compared
    assert "baseline run run_j" in compared["message"] and "not a database" in compared["message"]


def test_summary_fails_when_a_later_read_of_the_result_file_fails(tmp_path, monkeypatch):
    # Regression: the unmet-hours and EUI reads sat under a blanket except, so a result file that
    # failed after the first read produced ok=True with null metrics and a misleading warning
    from mcp_server.skills.results import sql_extract

    root = _http_tenant(monkeypatch, tmp_path)
    db = root / "run_m" / "run" / "eplusout.sql"
    _result_db(db, "Zone Air Temperature")

    def broken(source):
        raise sqlite3.DatabaseError("file is not a database")

    monkeypatch.setattr(sql_extract, "connection_for", broken)  # the unmet-hours / EUI reads
    summary = results.extract_summary_metrics("run_m")
    assert summary["ok"] is False and summary["error"] == "sql_error", summary
    assert "not a database" in summary["message"]


@posix_only
def test_an_oversize_result_file_is_refused_before_copying(tmp_path, monkeypatch):
    # Validates: the budget is checked on the opened descriptor, so a file over it is a
    # tool error and no copy is started
    root = _http_tenant(monkeypatch, tmp_path)
    db = root / "run_n" / "run" / "eplusout.sql"
    _result_db(db, "Big")
    monkeypatch.setattr(sql_open, "MAX_RESULT_SQL_BYTES", 16)
    before = _temp_copies()
    res = results.list_output_variables_op("run_n")
    assert res["ok"] is False and res["error"] == "sql_unreadable", res
    assert "exceeds the 16-byte limit" in res["message"]
    assert _temp_copies() == before


@posix_only
def test_fallback_search_does_not_descend_a_linked_directory(tmp_path, monkeypatch):
    # Validates: the fallback search (now a walk by directory descriptor, before a resolve-based
    # filter over rglob) never returns a result file reached through a linked directory, and
    # still finds one nested in a real subdirectory
    root = _http_tenant(monkeypatch, tmp_path)
    run_dir = root / "run_sql_2"
    run_dir.mkdir()
    bob_run = root.parent / "bob" / "run_sql_2" / "run"
    _result_db(bob_run / "eplusout.sql", "Bob Var")
    (run_dir / "linked").symlink_to(bob_run.parent, target_is_directory=True)
    assert results._find_first_existing(run_dir, ["run/eplusout.sql", "eplusout.sql"]) is None
    _result_db(run_dir / "deeper" / "eplusout.sql", "Alice Var")
    assert results._find_first_existing(run_dir, ["run/eplusout.sql"]) == run_dir / "deeper" / "eplusout.sql"


@posix_only
def test_a_checkpointed_wal_source_reads_through_the_private_copy(tmp_path, monkeypatch):
    # Regression: the private copy was opened without immutable=1, so SQLite looked for the
    # copy's -wal/-shm files beside a name already unlinked and the first read of a WAL-mode
    # source (cleanly checkpointed) failed with an I/O error; EnergyPlus writes journal_mode=OFF,
    # so this covers result files produced or post-processed by other tools
    root = _http_tenant(monkeypatch, tmp_path)
    db = root / "run_w" / "run" / "eplusout.sql"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE ReportDataDictionary (Name, KeyValue, ReportingFrequency, Units, IsMeter)")
    conn.execute("INSERT INTO ReportDataDictionary VALUES ('Wal Var', 'Env', 'Hourly', 'C', 0)")
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    assert _names(sql_open.connect_sql_readonly(db)) == ["Wal Var"]


@posix_only
def test_summary_copies_the_result_file_once_for_its_three_reads(tmp_path, monkeypatch):
    # Validates: extract_summary_metrics opens one private copy and hands the connection to the
    # total-site, unmet-hours and EUI extractors instead of copying the file for each
    root = _http_tenant(monkeypatch, tmp_path)
    db = root / "run_s" / "run" / "eplusout.sql"
    db.parent.mkdir(parents=True)
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE TabularDataWithStrings "
        "(ReportName, ReportForString, TableName, RowName, ColumnName, Units, Value)",
    )
    conn.commit()
    conn.close()
    copies: list[int] = []
    real = sql_open.copy_fd_bounded

    def counted(*args, **kwargs):
        copies.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(sql_open, "copy_fd_bounded", counted)
    summary = results.extract_summary_metrics("run_s")
    assert summary["ok"] is True, summary
    assert len(copies) == 1, "one copy serves total site energy, unmet hours and EUI"


@posix_only
def test_an_uncheckpointed_wal_source_is_refused_instead_of_read_stale(tmp_path, monkeypatch):
    # Regression: copying the main file of a WAL-mode database whose -wal still held committed
    # pages read the pre-commit rows as if current; a source with a non-empty -wal is a tool
    # error until its writer closes or checkpoints
    root = _http_tenant(monkeypatch, tmp_path)
    db = root / "run_u" / "run" / "eplusout.sql"
    db.parent.mkdir(parents=True)
    writer = sqlite3.connect(db)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE ReportDataDictionary (Name, KeyValue, ReportingFrequency, Units, IsMeter)")
    writer.execute("INSERT INTO ReportDataDictionary VALUES ('Old', 'Env', 'Hourly', 'C', 0)")
    writer.commit()
    writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    writer.execute("UPDATE ReportDataDictionary SET Name = 'Committed update'")
    writer.commit()  # lands in eplusout.sql-wal, not in the main file
    try:
        assert (db.parent / "eplusout.sql-wal").stat().st_size > 0
        res = results.list_output_variables_op("run_u")
        assert res["ok"] is False and res["error"] == "sql_unreadable", res
        assert "uncheckpointed WAL" in res["message"]
        assert "Old" not in repr(res)
    finally:
        writer.close()
