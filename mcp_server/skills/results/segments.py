"""Stitch time-segment results into monthly and annual totals (parallel-annual skill, #247).

Each segment run's segment_results_summary measure writes run/segment_results.json
holding only its kept days (lead-in dropped). Stitching sums energy by month,
takes the max for peak demand, and refuses overlapping or missing days.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from mcp_server.config import user_run_root
from mcp_server.util import is_regular_file_inside, read_file_in_dir_nofollow, resolve_run_dir

SEGMENT_RESULTS_FILE = "segment_results.json"
MAX_SEGMENT_FILE_BYTES = 2_000_000  # ~365 daily values + 12 months of end uses is a few kB


def _days(first: str, last: str) -> list[str]:
    """Every MM-DD from first to last, on a leap-year calendar (Feb 29 is optional, see below)."""
    d, end = date(2024, *map(int, first.split("-"))), date(2024, *map(int, last.split("-")))
    out = []
    while d <= end:
        out.append(d.strftime("%m-%d"))
        d += timedelta(days=1)
    return out


def _cv_rmse_pct(stitched: list[float], reference: list[float]) -> float | None:
    if not reference or sum(reference) == 0:
        return None
    rmse = math.sqrt(sum((s - r) ** 2 for s, r in zip(stitched, reference, strict=True)) / len(reference))
    return 100.0 * rmse / (sum(reference) / len(reference))


def _pct(value: float, reference: float) -> float | None:
    return None if reference == 0 else 100.0 * (value - reference) / reference


def _reference_check(segments: list[dict], daily: dict[str, float],
                     monthly_elec: dict[str, float], reference: dict) -> dict[str, Any]:
    ref_daily = reference["daily_electricity_kwh"]
    missing = sorted(set(daily) - set(ref_daily))
    if missing:
        return {"error": f"reference run lacks {len(missing)} stitched days, e.g. {missing[:3]}"}
    ref_monthly: dict[str, float] = {}
    for day, kwh in ref_daily.items():
        if day in daily:
            ref_monthly[day[:2]] = ref_monthly.get(day[:2], 0.0) + kwh
    months = sorted(monthly_elec)
    days = sorted(daily)
    first_days = []
    for seg in segments[1:]:  # segment 1 has no lead-in; its first day is the year's first day
        day = seg["keep_begin"]
        if day in daily:
            first_days.append({"day": day, "error_pct": _pct(daily[day], ref_daily[day])})
    return {
        "annual_electricity_error_pct": _pct(sum(daily.values()), sum(ref_daily[d] for d in days)),
        "monthly_electricity_bias_pct": {m: _pct(monthly_elec[m], ref_monthly[m]) for m in months},
        "monthly_cv_rmse_pct": _cv_rmse_pct([monthly_elec[m] for m in months], [ref_monthly[m] for m in months]),
        "daily_cv_rmse_pct": _cv_rmse_pct([daily[d] for d in days], [ref_daily[d] for d in days]),
        "first_kept_day_error_pct": first_days,
    }


def stitch(segments: list[dict], reference: dict | None = None) -> dict[str, Any]:
    """Pure stitch of parsed segment_results.json dicts (any order) -> totals, or ok False."""
    segments = sorted(segments, key=lambda s: s["keep_begin"])
    daily: dict[str, float] = {}
    overlaps: list[str] = []
    monthly: dict[str, dict[str, dict[str, float]]] = {}
    peaks: dict[str, float] = {}
    for seg in segments:
        for day, kwh in seg["daily_electricity_kwh"].items():
            if day in daily:
                overlaps.append(day)
            daily[day] = kwh
        for month, fuels in seg["monthly_end_uses_kwh"].items():
            for fuel, uses in fuels.items():
                into = monthly.setdefault(month, {}).setdefault(fuel, {})
                for use, kwh in uses.items():
                    into[use] = into.get(use, 0.0) + kwh
        for month, watts in seg["monthly_peak_electricity_w"].items():
            peaks[month] = max(watts, peaks.get(month, watts))
    if not daily:
        return {"ok": False, "error": "The segments hold no kept days."}
    first, last = min(daily), max(daily)
    # Feb 29 exists only in leap-year runs, so its absence is not a gap
    gaps = [d for d in _days(first, last) if d not in daily and d != "02-29"]
    if overlaps or gaps:
        return {
            "ok": False,
            "error": "Segments overlap or leave gaps, so the totals would be wrong.",
            "overlapping_days": sorted(set(overlaps))[:20],
            "missing_days": gaps[:20],
            "segments": [{"keep_begin": s["keep_begin"], "keep_end": s["keep_end"]} for s in segments],
        }

    annual: dict[str, dict[str, float]] = {}
    for fuels in monthly.values():
        for fuel, uses in fuels.items():
            for use, kwh in uses.items():
                into = annual.setdefault(fuel, {})
                into[use] = into.get(use, 0.0) + kwh
    result: dict[str, Any] = {
        "ok": True,
        "segment_count": len(segments),
        "first_day": first,
        "last_day": last,
        "kept_days": len(daily),
        "units": {"energy": "kWh", "demand": "W"},
        "annual_electricity_kwh": sum(daily.values()),
        "annual_end_uses_kwh": annual,
        "monthly_end_uses_kwh": dict(sorted(monthly.items())),
        "monthly_peak_electricity_w": dict(sorted(peaks.items())),
    }
    if reference is not None:
        monthly_elec = {m: f.get("Electricity", {}).get("Total", 0.0) for m, f in monthly.items()}
        result["reference_check"] = _reference_check(segments, daily, monthly_elec, reference)
    return result


def _load(run_id: str) -> dict:
    """segment_results.json of one run, read without following links; raises ValueError."""
    try:
        run_dir = resolve_run_dir(user_run_root(), run_id)
    except FileNotFoundError:
        raise ValueError(f"Run not found: {run_id}") from None
    path = run_dir / "run" / SEGMENT_RESULTS_FILE
    if not is_regular_file_inside(path, run_dir):
        raise ValueError(
            f"Run {run_id} has no run/{SEGMENT_RESULTS_FILE}: it needs a segment_results_summary "
            "step and a successful run (check get_run_status).",
        )
    try:
        data = json.loads(read_file_in_dir_nofollow(Path(path.parent), SEGMENT_RESULTS_FILE, MAX_SEGMENT_FILE_BYTES))
    except (OSError, ValueError) as e:
        raise ValueError(f"Run {run_id}: unreadable {SEGMENT_RESULTS_FILE}: {e}") from None
    needed = ("keep_begin", "keep_end", "daily_electricity_kwh", "monthly_end_uses_kwh", "monthly_peak_electricity_w")
    if not isinstance(data, dict) or any(k not in data for k in needed):
        raise ValueError(f"Run {run_id}: {SEGMENT_RESULTS_FILE} lacks one of {list(needed)}")
    return data


def stitch_segment_results_op(run_ids: list[str], reference_run_id: str | None = None) -> dict[str, Any]:
    """Load each run's segment results and stitch them; optionally compare to a reference run."""
    if not run_ids:
        return {"ok": False, "error": "run_ids is empty: pass the run_id of every segment run."}
    if len(set(run_ids)) != len(run_ids):
        return {"ok": False, "error": "run_ids lists a run more than once."}
    try:
        segments = [_load(r) for r in run_ids]
        reference = _load(reference_run_id) if reference_run_id else None
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return stitch(segments, reference)
