"""Unit tests for run_idf (issue #246): IDF text edits, Schedule:File companions, the
EnergyPlus command, status from eplusout.end, and the launch-time grant re-check.
No Docker/OpenStudio: the subprocess launch is replaced, everything else is real."""
import sys
from pathlib import Path

import pytest
from test_analysis_tools import _http_tenant

import mcp_server.skills.simulation.operations as ops
from mcp_server.skills.simulation import idf_run

pytestmark = pytest.mark.unit

IDF = """\
Version,25.2;

Building,
  Bldg,                                   !- Name
  0,                                      !- North Axis {deg}
  ,                                       !- Terrain
  ,                                       !- Loads Convergence Tolerance Value {W}
  ,                                       !- Temperature Convergence Tolerance Value {deltaC}
  ,                                       !- Solar Distribution
  ,                                       !- Maximum Number of Warmup Days
  ;                                       !- Minimum Number of Warmup Days

RunPeriod,
  Run Period 1,                           !- Name
  1,                                      !- Begin Month
  1,                                      !- Begin Day of Month
  2012,                                   !- Begin Year
  12,                                     !- End Month
  31,                                     !- End Day of Month
  2012,                                   !- End Year
  Sunday,                                 !- Day of Week for Start Day
  No;                                     !- Use Weather File Holidays and Special Days

Schedule:File,
  csv a,                                  !- Name
  Fractional,                             !- Schedule Type Limits Name
  {a},                                    !- File Name
  1,                                      !- Column Number
  1;                                      !- Rows to Skip at Top

Schedule:File,
  csv b,                                  !- Name
  ,                                       !- Schedule Type Limits Name
  {b},                                    !- File Name
  1,                                      !- Column Number
  1;                                      !- Rows to Skip at Top
"""


def test_overrides_set_run_period_and_blank_the_stale_weekday():
    # Validates: segment dates land in RunPeriod fields 2/3/5/6 and the translator's
    # weekday of the ORIGINAL start (Sunday) is blanked so EnergyPlus derives it from
    # Begin Year; every other byte, comments included, is unchanged
    text, err = idf_run.apply_overrides(IDF, begin_month=3, begin_day=10, end_month=3, end_day=21)
    assert err is None
    assert idf_run.get_fields(text, "runperiod", 2) == ["3"]
    assert idf_run.get_fields(text, "runperiod", 3) == ["10"]
    assert idf_run.get_fields(text, "runperiod", 4) == ["2012"]
    assert idf_run.get_fields(text, "runperiod", 5) == ["3"]
    assert idf_run.get_fields(text, "runperiod", 6) == ["21"]
    assert idf_run.get_fields(text, "runperiod", 8) == [""]
    # only the value changed: the comment after it keeps its own bytes
    assert "\n  10," + " " * 38 + "!- Begin Day of Month\n" in text
    assert text.count("!-") == IDF.count("!-")
    assert text.splitlines()[:12] == IDF.splitlines()[:12]  # Building untouched


def test_end_date_only_keeps_the_start_weekday():
    # Validates: the weekday is only blanked when the start date moves
    text, err = idf_run.apply_overrides(IDF, end_month=1, end_day=14)
    assert err is None
    assert idf_run.get_fields(text, "runperiod", 8) == ["Sunday"]
    assert idf_run.get_fields(text, "runperiod", 6) == ["14"]


def test_warmup_overrides_fill_blank_building_fields():
    # Validates: max/min warmup days go into Building fields 7/8, including a blank last field
    text, err = idf_run.apply_overrides(IDF, max_warmup_days=7, min_warmup_days=2)
    assert err is None
    assert idf_run.get_fields(text, "building", 7) == ["7"]
    assert idf_run.get_fields(text, "building", 8) == ["2"]


def test_set_fields_appends_missing_trailing_fields():
    # Validates: a short object (Building with only a name) gains the trailing fields
    text, n = idf_run.set_fields("Building,B;\n", "building", {8: "3"})
    assert n == 1
    assert text == "Building,B,,,,,,,3;\n"


@pytest.mark.parametrize(("kwargs", "msg"), [
    ({"begin_month": 13}, "begin_month must be an integer from 1 to 12, got 13"),
    ({"end_day": 0}, "end_day must be an integer from 1 to 31, got 0"),
    ({"min_warmup_days": True}, "min_warmup_days must be an integer from 1 to 10000, got True"),
])
def test_override_values_are_range_checked(kwargs, msg):
    # Validates: out-of-range or non-integer overrides are refused before any staging
    _text, err = idf_run.apply_overrides(IDF, **kwargs)
    assert err == msg


def test_run_period_override_needs_exactly_one_run_period():
    # Validates: with two RunPeriods it is ambiguous which one a segment means
    two = IDF + "\nRunPeriod,RP2,1,1,,1,2,;\n"
    _text, err = idf_run.apply_overrides(two, begin_month=2)
    assert err == "run period overrides need exactly one RunPeriod in the IDF, found 2"


def test_schedule_files_resolve_to_absolute_paths_and_dedupe_dirs(tmp_path, monkeypatch):
    # Validates: a relative name resolves against the source IDF's dir (the staged copy
    # lives elsewhere), an absolute one is kept, and each companion dir is granted once
    root = _http_tenant(monkeypatch, tmp_path)
    src = root / "run_src" / "files"
    src.mkdir(parents=True)
    (src / "a.csv").write_text("v\n1\n")
    (src / "b.csv").write_text("v\n1\n")
    text = IDF.replace("{a}", "files/a.csv").replace("{b}", str(src / "b.csv"))
    out, dirs, err = idf_run.resolve_schedule_files(text, root / "run_src", root)
    assert err is None
    assert idf_run.get_fields(out, "schedule:file", 3) == [str(src / "a.csv"), str(src / "b.csv")]
    assert dirs == [str(src)]


def test_schedule_file_outside_own_run_area_is_refused(tmp_path, monkeypatch):
    # Validates: another tenant's CSV is never granted to this tenant's EnergyPlus child
    root = _http_tenant(monkeypatch, tmp_path)
    other = root.parent / "bob" / "x.csv"
    other.write_text("v\n1\n")
    text = IDF.replace("{a}", str(other)).replace("{b}", str(other))
    _out, dirs, err = idf_run.resolve_schedule_files(text, root, root)
    assert dirs == []
    assert err.startswith(f"Schedule:File '{other}' resolves to {other}, outside your run area")


def test_missing_schedule_file_is_reported_up_front(tmp_path, monkeypatch):
    # Validates: a missing companion fails at submit, not as a fatal EnergyPlus run later
    root = _http_tenant(monkeypatch, tmp_path)
    _out, _dirs, err = idf_run.resolve_schedule_files(IDF.replace("{a}", "nope.csv"), root, root)
    assert err == f"Schedule:File 'nope.csv' not found (looked for {root / 'nope.csv'})"


def test_idf_run_command_is_energyplus_into_run_dir(monkeypatch):
    # Validates: an IDF run launches EnergyPlus with the staged EPW and -d run/, so the
    # outputs land where get_run_logs, extract_* and apply_measure(run_id) read them
    monkeypatch.setenv("ENERGYPLUS_EXE_PATH", sys.executable)  # any existing file
    cmd = ops._build_run_cmd(Path("/r/run_x/run/in.idf"), Path("/r/run_x/files/w.epw"))
    assert cmd == [sys.executable, "-w", "/r/run_x/files/w.epw", "-d", "/r/run_x/run", "/r/run_x/run/in.idf"]
    assert ops._build_run_cmd(Path("/r/run_x/workflow.osw"))[-3:] == ["run", "-w", "/r/run_x/workflow.osw"]


@pytest.mark.parametrize(("end", "status", "error"), [
    ("EnergyPlus Completed Successfully-- 3 Warning; 0 Severe Errors;", "success", None),
    ("EnergyPlus Terminated--Fatal Error Detected. 0 Warning; 1 Severe Errors;", "failed", None),
    (None, "failed", "EnergyPlus left no eplusout.end (see get_run_logs)"),
])
def test_idf_run_status_comes_from_eplusout_end(tmp_path, end, status, error):
    # Validates: an IDF run has no out.osw; its terminal status is EnergyPlus's own verdict
    run_dir = tmp_path / "run_x"
    (run_dir / "run").mkdir(parents=True)
    if end is not None:
        (run_dir / "run" / "eplusout.end").write_text(end)
    rec = ops.RunRecord(run_id="run_x", user_key="local", name="x", status="running",
                        created_at=0.0, started_at=0.0, ended_at=None, pid=None, run_dir=run_dir,
                        osw_path=run_dir / "run" / "in.idf", epw_path=None, exit_code=None, error=None)
    ops._refresh_status(rec)
    assert (rec.status, rec.error) == (status, error)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlink")
def test_launch_drops_grants_that_left_the_owner_run_root(tmp_path, monkeypatch):
    # Validates: a companion dir swapped for a link (here, into bob's area) after run_idf
    # checked it is not granted at launch; the untouched dir still is
    root = _http_tenant(monkeypatch, tmp_path)
    keep = root / "keep"
    keep.mkdir()
    swapped = root / "swapped"
    swapped.symlink_to(root.parent / "bob")
    rec = ops.RunRecord(run_id="r", user_key="alice", name="r", status="queued", created_at=0.0,
                        started_at=None, ended_at=None, pid=None, run_dir=root / "r",
                        osw_path=root / "r" / "run" / "in.idf", epw_path=None, exit_code=None,
                        error=None, extra_ro=(str(keep), str(swapped), str(root.parent / "bob")))
    assert ops._companion_grants(rec) == (str(keep),)


def test_run_idf_stages_edited_idf_and_queues_it(tmp_path, monkeypatch):
    # Validates: run_idf writes the edited IDF to run/in.idf, stages the EPW, and queues a
    # record through the shared scheduler carrying the companion dirs for the launch grant
    root = _http_tenant(monkeypatch, tmp_path)
    monkeypatch.setattr(idf_run, "user_key", lambda: "alice")
    monkeypatch.setenv("ENERGYPLUS_EXE_PATH", sys.executable)
    launched = []
    monkeypatch.setattr(ops, "_launch", lambda rec: launched.append(rec) or setattr(rec, "status", "running"))
    monkeypatch.setattr(ops, "_ensure_dispatcher", lambda: None)
    monkeypatch.setattr(ops, "_pid_alive", lambda _pid: False)
    monkeypatch.setattr(ops, "_RUNS", {})
    monkeypatch.setattr(ops, "_queue", type(ops._queue)())
    src = root / "run_src"
    (src / "files").mkdir(parents=True)
    (src / "files" / "a.csv").write_text("v\n1\n")
    (src / "run").mkdir()
    (src / "run" / "in.idf").write_text(IDF.replace("{a}", str(src / "files" / "a.csv"))
                                        .replace("{b}", str(src / "files" / "a.csv")))
    epw = root / "w.epw"
    epw.write_text("LOCATION,x\n")

    res = idf_run.run_idf(str(src / "run" / "in.idf"), str(epw), "seg2", begin_month=3, begin_day=10)

    assert res["ok"] is True, res
    assert res["status"] == "running"
    assert res["name"] == "seg2"
    staged = Path(res["idf_path"])
    assert staged == Path(res["run_dir"]) / "run" / "in.idf"
    assert idf_run.get_fields(staged.read_text(), "runperiod", 2) == ["3"]
    assert Path(res["epw_path"]).read_text() == "LOCATION,x\n"
    assert res["schedule_file_dirs"] == [str((src / "files").resolve())]
    assert [r.run_id for r in launched] == [res["run_id"]]
    assert launched[0].extra_ro == (str((src / "files").resolve()),)
    assert launched[0].osw_path == staged


@pytest.mark.parametrize(("idf_name", "msg"), [
    ("model.osm", "Not an .idf file: "),
    ("missing.idf", "IDF file not found: "),
])
def test_run_idf_rejects_bad_idf_paths(tmp_path, monkeypatch, idf_name, msg):
    # Validates: wrong type or missing IDF is an ok=False error, never an exception
    root = _http_tenant(monkeypatch, tmp_path)
    monkeypatch.setenv("ENERGYPLUS_EXE_PATH", sys.executable)
    res = idf_run.run_idf(str(root / idf_name), str(root / "w.epw"))
    assert res == {"ok": False, "error": msg + str(root / idf_name)}


def test_run_idf_refuses_another_tenants_idf(tmp_path, monkeypatch):
    # Validates: the IDF path is access-checked like run_simulation's OSM
    root = _http_tenant(monkeypatch, tmp_path)
    monkeypatch.setenv("ENERGYPLUS_EXE_PATH", sys.executable)
    victim = root.parent / "bob" / "in.idf"
    victim.write_text(IDF)
    res = idf_run.run_idf(str(victim), str(root / "w.epw"))
    assert res == {"ok": False, "error": f"IDF path not allowed: {victim}"}
