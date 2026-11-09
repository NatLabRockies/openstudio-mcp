"""run_idf: simulate an already-translated EnergyPlus IDF through the run queue (issue #246).

Forward translation of a large OSM costs tens of seconds per run. A completed run's
`run/in.idf` is exactly what EnergyPlus consumed, so later runs that differ only in
RunPeriod or warmup days can start from it and skip the translation.

The IDF is edited as text, field by field, so every other byte EnergyPlus sees is the
translated original. Schedule:File companions are not copied: the directories that hold
them are granted read-only to the sandboxed EnergyPlus child (see _launch).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp_server.config import is_path_allowed, user_run_root
from mcp_server.identity import user_key
from mcp_server.skills.simulation.operations import (
    RunRecord,
    _energyplus_exe,
    _now,
    _stage_file,
    _submit,
)
from mcp_server.util import create_run_dir, open_nofollow_for_write, read_file_bounded, safe_name

MAX_IDF_BYTES = 512 * 1024 * 1024

# Field positions with the class name at 0, so an object's Name is 1 (EnergyPlus 9.x+ IDD)
_RUN_PERIOD = "runperiod"
_RP_BEGIN_MONTH, _RP_BEGIN_DAY, _RP_BEGIN_YEAR = 2, 3, 4
_RP_END_MONTH, _RP_END_DAY, _RP_START_WEEKDAY = 5, 6, 8
_BUILDING = "building"
_B_MAX_WARMUP, _B_MIN_WARMUP = 7, 8
_SCHEDULE_FILE = "schedule:file"
_SF_FILE_NAME = 3

_COMMENT = re.compile(r"!.*")


def _objects(text: str, cls: str) -> list[tuple[list[tuple[int, int]], int]]:
    """Every `cls` object as (field spans, offset of its ';'); span 0 is the class name.

    Comments are blanked to spaces first, so offsets index the original text and the edits
    below never touch a comment. The class is matched only at an object start and only as
    the whole name (Schedule:File is not Schedule:File:Shading).
    """
    code = _COMMENT.sub(lambda m: " " * len(m.group()), text)
    head = re.compile(r"(?:\A|;)(\s*" + re.escape(cls) + r"\s*)[,;]", re.IGNORECASE)
    objs = []
    for m in head.finditer(code):
        start = m.start(1)
        semi = code.find(";", m.end(1))
        if semi < 0:
            break  # unterminated last object
        spans, s = [], start
        for comma in re.finditer(",", code[start:semi]):
            spans.append((s, start + comma.start()))
            s = start + comma.start() + 1
        spans.append((s, semi))
        objs.append((spans, semi))
    return objs


def _token(text: str, span: tuple[int, int]) -> tuple[int, int]:
    """The field's value within its span (comment-blanked), or an empty span at its end."""
    code = _COMMENT.sub(lambda m: " " * len(m.group()), text[span[0]:span[1]])
    stripped = code.strip()
    if not stripped:
        return span[1], span[1]
    lead = len(code) - len(code.lstrip())
    return span[0] + lead, span[0] + lead + len(stripped)


def _splice(text: str, edits: list[tuple[int, int, str]]) -> str:
    """Apply non-overlapping (start, end, replacement) edits in one pass."""
    out, last = [], 0
    for a, b, v in sorted(edits):
        out += [text[last:a], v]
        last = b
    return "".join(out) + text[last:]


def get_fields(text: str, cls: str, index: int) -> list[str]:
    """The value of field `index` in every `cls` object ('' when absent or blank)."""
    out = []
    for spans, _semi in _objects(text, cls):
        a, b = _token(text, spans[index]) if index < len(spans) else (0, 0)
        out.append(text[a:b])
    return out


def set_fields(text: str, cls: str, values: dict[int, str]) -> tuple[str, int]:
    """Replace fields of every `cls` object (appending missing trailing fields).

    Returns the new text and how many objects were edited.
    """
    edits: list[tuple[int, int, str]] = []
    objs = _objects(text, cls)
    for spans, semi in objs:
        edits += [(*_token(text, spans[i]), v) for i, v in values.items() if i < len(spans)]
        if max(values) >= len(spans):
            tail = "".join("," + values.get(i, "") for i in range(len(spans), max(values) + 1))
            edits.append((semi, semi, tail))
    return _splice(text, edits), len(objs)


def apply_overrides(text: str, *, begin_month: int | None = None, begin_day: int | None = None,
                    end_month: int | None = None, end_day: int | None = None,
                    max_warmup_days: int | None = None,
                    min_warmup_days: int | None = None) -> tuple[str, str | None]:
    """Set RunPeriod dates and Building warmup days. Returns (text, error)."""
    for label, v, lo, hi in (("begin_month", begin_month, 1, 12), ("end_month", end_month, 1, 12),
                             ("begin_day", begin_day, 1, 31), ("end_day", end_day, 1, 31),
                             ("max_warmup_days", max_warmup_days, 1, 10000),
                             ("min_warmup_days", min_warmup_days, 1, 10000)):
        if v is not None and (isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi):
            return text, f"{label} must be an integer from {lo} to {hi}, got {v!r}"

    rp = {i: str(v) for i, v in ((_RP_BEGIN_MONTH, begin_month), (_RP_BEGIN_DAY, begin_day),
                                 (_RP_END_MONTH, end_month), (_RP_END_DAY, end_day)) if v is not None}
    if rp:
        years = get_fields(text, _RUN_PERIOD, _RP_BEGIN_YEAR)
        if len(years) != 1:
            return text, f"run period overrides need exactly one RunPeriod in the IDF, found {len(years)}"
        if years[0] and (begin_month is not None or begin_day is not None):
            # The translator writes the weekday of the ORIGINAL start date; with a Begin
            # Year present a blank lets EnergyPlus derive the weekday of the new one.
            rp[_RP_START_WEEKDAY] = ""
        text, _ = set_fields(text, _RUN_PERIOD, rp)
    bw = {i: str(v) for i, v in ((_B_MAX_WARMUP, max_warmup_days), (_B_MIN_WARMUP, min_warmup_days))
          if v is not None}
    if bw:
        text, n = set_fields(text, _BUILDING, bw)
        if n != 1:
            return text, f"warmup overrides need exactly one Building object in the IDF, found {n}"
    return text, None


def resolve_schedule_files(text: str, idf_dir: Path, run_root: Path) -> tuple[str, list[str], str | None]:
    """Point every Schedule:File at an absolute path and list the dirs to grant read-only.

    Relative names are resolved against the source IDF's directory (EnergyPlus would
    search there; the staged copy lives in the run dir). Each file must exist under the
    caller's own run root: the read-only grant follows links, and shared roots such as
    /inputs are never granted to a tenant's process. Returns (text, dirs, error).
    """
    resolved: list[str] = []
    dirs: list[str] = []
    for name in get_fields(text, _SCHEDULE_FILE, _SF_FILE_NAME):
        p = Path(name)
        p = (p if p.is_absolute() else idf_dir / p).resolve()
        if not p.is_file():
            return text, [], f"Schedule:File '{name}' not found (looked for {p})"
        if not (p.is_relative_to(run_root) and is_path_allowed(p)):
            return text, [], (f"Schedule:File '{name}' resolves to {p}, outside your run area "
                              f"{run_root}; copy it there (copy_file) and reference that copy")
        resolved.append(str(p))
        if str(p.parent) not in dirs:
            dirs.append(str(p.parent))
    edits = [(*_token(text, spans[_SF_FILE_NAME]), resolved[k])
             for k, (spans, _semi) in enumerate(_objects(text, _SCHEDULE_FILE))]
    return _splice(text, edits), dirs, None


def run_idf(idf_path: str, epw_path: str, name: str | None = None, *,
            begin_month: int | None = None, begin_day: int | None = None,
            end_month: int | None = None, end_day: int | None = None,
            max_warmup_days: int | None = None, min_warmup_days: int | None = None) -> dict[str, Any]:
    """Queue an EnergyPlus run of an IDF, optionally with RunPeriod / warmup overrides."""
    exe = _energyplus_exe()
    if exe is None:
        return {"ok": False, "error": "EnergyPlus executable not found (set ENERGYPLUS_EXE_PATH)"}
    idf = Path(idf_path)
    if idf.suffix.lower() != ".idf":
        return {"ok": False, "error": f"Not an .idf file: {idf_path}"}
    if not idf.is_file():
        return {"ok": False, "error": f"IDF file not found: {idf_path}"}
    if not is_path_allowed(idf):
        return {"ok": False, "error": f"IDF path not allowed: {idf_path}"}
    epw = Path(epw_path)
    if not epw.is_file():
        return {"ok": False, "error": f"EPW file not found: {epw_path}"}
    if not is_path_allowed(epw):
        return {"ok": False, "error": f"EPW path not allowed: {epw_path}"}

    try:
        # surrogateescape: bytes that are not UTF-8 go back out unchanged
        text = read_file_bounded(idf, MAX_IDF_BYTES).decode("utf-8", errors="surrogateescape")
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"Could not read the IDF: {e}"}
    text, err = apply_overrides(text, begin_month=begin_month, begin_day=begin_day,
                                end_month=end_month, end_day=end_day,
                                max_warmup_days=max_warmup_days, min_warmup_days=min_warmup_days)
    if err:
        return {"ok": False, "error": err}
    run_root = user_run_root()
    text, ro_dirs, err = resolve_schedule_files(text, idf.parent.resolve(), run_root.resolve())
    if err:
        return {"ok": False, "error": err}

    run_name = safe_name(name or idf.stem)
    run_id, run_dir = create_run_dir(run_root, "run", run_name)
    # run/ is where OpenStudio runs leave in.idf and eplusout.*: get_run_logs,
    # extract_* and apply_measure(run_id=...) read them from there.
    staged_idf = run_dir / "run" / "in.idf"
    staged_epw = run_dir / "files" / epw.name
    try:
        staged_idf.parent.mkdir()
        staged_epw.parent.mkdir()
        with open_nofollow_for_write(staged_idf) as fh:
            fh.buffer.write(text.encode("utf-8", errors="surrogateescape"))
    except (OSError, ValueError) as e:
        return {"ok": False, "error": f"Could not stage the IDF: {e}", "run_dir": str(run_dir)}
    err = _stage_file(epw, staged_epw)
    if err:
        return {"ok": False, "error": err, "run_dir": str(run_dir)}

    rec = RunRecord(
        run_id=run_id, user_key=user_key(), name=run_name, status="queued",
        created_at=_now(), started_at=None, ended_at=None, pid=None,
        run_dir=run_dir, osw_path=staged_idf, epw_path=staged_epw,
        exit_code=None, error=None, extra_ro=tuple(ro_dirs),
    )
    _submit(rec)
    return {
        "ok": True,
        "run_id": run_id,
        "name": run_name,
        "status": rec.status,
        "run_dir": str(run_dir),
        "idf_path": str(staged_idf),
        "epw_path": str(staged_epw),
        "schedule_file_dirs": ro_dirs,
    }
