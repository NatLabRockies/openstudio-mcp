from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from mcp_server.config import user_run_root
from mcp_server.confined_copy import copy_tree_confined
from mcp_server.confined_fs import DirHandle
from mcp_server.skills.results.sql_open import _find_first_existing, connect_sql_readonly, connection_for
from mcp_server.util import (
    copy_regular_file_nofollow,
    read_file_bounded,
    read_text_capped,
    reject_escaping_symlinks,
    resolve_run_dir,
    safe_read_text,
)

MAX_ERR_READ_BYTES = 16 * 1024 * 1024
MAX_RECORD_BYTES = 64 * 1024
# copy_file moves simulation outputs (eplusout.sql reaches gigabytes); this bounds a runaway copy.
MAX_COPY_FILE_BYTES = 8 * 1024 * 1024 * 1024


def _run_status_from_record(run_dir: Path) -> str | None:
    """Status from the run's on-disk record (simulation _persist_run_record).

    None for dirs without a readable record (legacy or externally seeded runs)
    — callers then extract whatever result files exist, as before.
    """
    try:  # never through a symlink: the record sits in the tenant-writable run dir
        raw = read_file_bounded(run_dir / "run_record.json", MAX_RECORD_BYTES)
        return json.loads(raw.decode("utf-8", errors="replace")).get("status")
    except (OSError, ValueError, AttributeError):
        return None


def _extract_total_site_energy_from_sql(sql_path: Path | sqlite3.Connection) -> dict[str, Any]:
    """Extract Total Site Energy (GJ) from EnergyPlus SQL via precise query."""
    conn, owned = connection_for(sql_path)
    conn.row_factory = sqlite3.Row
    try:
        # TabularDataWithStrings may be a VIEW — don't filter by type='table'
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE name='TabularDataWithStrings'",
        )
        if not cur.fetchone():
            return {"ok": False, "reason": "missing_tabular_table"}

        row = conn.execute("""
            SELECT Value, Units, ReportName, TableName, RowName, ColumnName
            FROM TabularDataWithStrings
            WHERE ReportName = 'AnnualBuildingUtilityPerformanceSummary'
              AND TableName = 'Site and Source Energy'
              AND RowName = 'Total Site Energy'
              AND ColumnName = 'Total Energy'
            LIMIT 1
        """).fetchone()

        if not row:
            return {"ok": False, "reason": "not_found"}

        value_str = (row["Value"] or "").strip()
        units = (row["Units"] or "").strip() or None
        m = re.search(r"[-+]?\d+(?:\.\d+)?", value_str.replace(",", ""))
        if not m:
            return {"ok": False, "reason": "non_numeric_value", "value": value_str, "units": units}

        return {
            "ok": True,
            "value": float(m.group(0)),
            "units": units,
            "report_name": row["ReportName"],
            "table_name": row["TableName"],
            "row_name": row["RowName"],
            "column_name": row["ColumnName"],
        }
    finally:
        if owned:
            conn.close()


def _extract_total_site_energy_from_html(html_path: Path) -> dict[str, Any]:
    """Extract total site energy from EnergyPlus HTML tabular report."""
    try:
        # safe_read_text refuses symlinks (ValueError) — the HTML is written by the
        # simulation subprocess, same swap exposure as out.osw (PR #105).
        txt = safe_read_text(html_path, max_bytes=800_000)
    except ValueError:
        return {"ok": False, "reason": "unreadable"}
    m = re.search(
        r"Total\s*Site\s*Energy[^\d]{0,200}([-+]?\d[\d,]*(?:\.\d+)?)\s*([A-Za-z/\^0-9]+)?",
        txt,
        re.IGNORECASE,
    )
    if not m:
        return {"ok": False, "reason": "not_found"}
    val = float(m.group(1).replace(",", ""))
    units = m.group(2)
    return {"ok": True, "value": val, "units": units}


def _to_kbtu(value: float, units: str | None) -> float | None:
    """Convert common EnergyPlus site-energy units to kBtu (best-effort)."""
    if not units:
        return None
    u = units.strip().lower()
    if u == "kbtu":
        return value
    if u == "mbtu":
        return value * 1000.0
    if u == "gj":
        return value * 947.817
    if u == "mj":
        return value * 0.947817
    if u == "kwh":
        return value * 3.41214163
    return None


def extract_summary_metrics(run_id: str, include_raw: bool = False) -> dict[str, Any]:
    """Extract headline metrics from a completed run (restart-safe)."""
    try:
        run_dir = resolve_run_dir(user_run_root(), run_id)
    except FileNotFoundError:
        return {"ok": False, "error": "run_not_found", "message": f"Unknown run_id: {run_id}"}

    # A failed/unfinished run has no meaningful summary. Answering ok:true
    # with all-null metrics misled agents into reporting success (found via
    # the LLM benchmark: weatherless sims died in ~1s yet extraction
    # "succeeded" silently).
    status = _run_status_from_record(run_dir)
    if status in ("failed", "cancelled"):
        return {
            "ok": False, "run_id": run_id, "status": status,
            "error": (
                f"Run {status} — no summary metrics to extract. Diagnose "
                "with extract_simulation_errors or get_run_logs."),
        }
    if status in ("queued", "running"):
        return {
            "ok": False, "run_id": run_id, "status": status,
            "error": (
                "Run has not finished — poll get_run_status until it is "
                "terminal, then extract."),
        }

    sql_path = _find_first_existing(run_dir, ["run/eplusout.sql", "eplusout.sql"])
    html_path = _find_first_existing(
        run_dir,
        ["run/eplustbl.htm", "run/eplustbl.html", "eplustbl.htm", "eplustbl.html"],
    )

    def _sql_failure(code: str, message: str) -> dict[str, Any]:
        # The run has an eplusout.sql that cannot be opened or read: that is a failure
        # of this extraction, not "no results"; never report success with null
        # metrics over it.
        return {
            "ok": False, "run_id": run_id, "error": code, "message": message,
            "paths": {"run_dir": str(run_dir), "sql": str(sql_path), "html": str(html_path) if html_path else None},
        }

    total_site = None
    total_site_src = None
    unmet = None
    eui = None
    if sql_path and sql_path.suffix.lower() == ".sql":
        from mcp_server.skills.results.sql_extract import (  # type: ignore[import-not-found]
            extract_eui,
            extract_unmet_hours,
        )

        # One private copy of eplusout.sql serves the three reads below.
        try:
            conn = connect_sql_readonly(sql_path)
        except (OSError, ValueError) as e:
            return _sql_failure("sql_unreadable", f"eplusout.sql could not be opened: {e}")
        except sqlite3.Error as e:
            return _sql_failure("sql_error", f"eplusout.sql could not be read: {e}")
        try:
            total_site = _extract(_extract_total_site_energy_from_sql, conn)
            unmet = _extract(extract_unmet_hours, conn)
            eui = _extract(extract_eui, conn)
        finally:
            conn.close()
        total_site_src = "sql"
        for part in (total_site, unmet, eui):
            if part.get("error") in ("sql_unreadable", "sql_error"):
                return _sql_failure(part["error"], part["message"])
        if not total_site.get("ok"):
            total_site = None
    if total_site is None and html_path:
        total_site = _extract_total_site_energy_from_html(html_path)
        total_site_src = "html"
        if not total_site.get("ok"):
            total_site = None

    total_site_kbtu = None
    total_site_units = None
    total_site_value = None
    total_site_detail: dict[str, Any] | None = None
    if total_site:
        total_site_value = total_site.get("value")
        total_site_units = total_site.get("units")
        total_site_kbtu = (
            _to_kbtu(float(total_site_value), total_site_units) if total_site_value is not None else None
        )
        total_site_detail = {k: v for k, v in total_site.items() if k not in ("ok",)}

    metrics: dict[str, Any] = {
        "total_site_energy": {
            "value": total_site_value,
            "units": total_site_units,
            "kbtu": total_site_kbtu,
            "source": total_site_src if total_site_value is not None else None,
            "detail": total_site_detail,
        },
        "unmet_hours_heating": unmet.get("heating") if isinstance(unmet, dict) else None,
        "unmet_hours_cooling": unmet.get("cooling") if isinstance(unmet, dict) else None,
        "eui_MJ_m2": (eui.get("eui_MJ_m2") if isinstance(eui, dict) else None),
        "eui_kBtu_ft2": (eui.get("eui_kBtu_ft2") if isinstance(eui, dict) else None),
    }
    if include_raw:
        metrics["raw"] = {"unmet": unmet, "eui": eui}

    # Sanity warnings
    warnings_list: list[str] = []
    eui_val = metrics.get("eui_kBtu_ft2")
    if eui_val is not None and eui_val <= 0:
        warnings_list.append("EUI is zero or negative — simulation may not have completed")
    elif eui_val is None:
        area_ok = metrics["total_site_energy"].get("value") is not None
        if area_ok:
            warnings_list.append("No conditioned floor area — EUI cannot be computed")

    heating_unmet = metrics.get("unmet_hours_heating")
    cooling_unmet = metrics.get("unmet_hours_cooling")
    total_unmet = (heating_unmet or 0) + (cooling_unmet or 0)
    if total_unmet > 300:
        warnings_list.append(
            f"Unmet hours ({total_unmet:.0f}) exceed 300 — HVAC may be undersized",
        )

    # Run dirs without a status record (legacy/seeded) can still be empty of
    # results — say so instead of returning a silently all-null "success"
    if total_site_value is None and eui is None and unmet is None:
        warnings_list.append(
            "No results found in run directory — simulation may not have "
            "completed successfully",
        )

    return {
        "ok": True,
        "run_id": run_id,
        "paths": {
            "run_dir": str(run_dir),
            "sql": str(sql_path) if sql_path else None,
            "html": str(html_path) if html_path else None,
        },
        "metrics": metrics,
        "warnings": warnings_list,
    }


def read_file(
    file_path: str, max_bytes: int = 50_000, offset: int = 0,
) -> dict[str, Any]:
    """Read a file by absolute path (any allowed mount: /runs, /inputs, /repo, etc.).

    Default 50KB. Use offset+max_bytes for chunked reading of large files.

    - `file_path` must be an absolute path within allowed roots.
    - `offset` allows chunked reading (byte offset to start from).
    - For text-like files, returns `text`.
    - For binary/unknown, returns `base64` + `mime`.
    """
    from mcp_server.config import is_path_allowed

    full = Path(file_path).resolve()
    if not is_path_allowed(full):
        return {
            "ok": False, "error": "invalid_path",
            "message": f"Path not in allowed roots: {file_path}",
        }

    if not full.exists() or not full.is_file():
        return {"ok": False, "error": "not_found", "message": f"File not found: {file_path}"}

    file_size = full.stat().st_size

    # Read with optional offset for chunked reading
    with full.open("rb") as f:
        if offset > 0:
            f.seek(offset)
        data = f.read(max_bytes)

    # Try decode as utf-8 text
    try:
        text = data.decode("utf-8")
        return {
            "ok": True,
            "file_path": str(full),
            "kind": "text",
            "file_size": file_size,
            "offset": offset,
            "bytes_read": len(data),
            "truncated": offset + len(data) < file_size,
            "text": text,
        }
    except Exception:
        mime, _ = mimetypes.guess_type(str(full))
        return {
            "ok": True,
            "file_path": str(full),
            "kind": "base64",
            "mime": mime or "application/octet-stream",
            "file_size": file_size,
            "offset": offset,
            "bytes_read": len(data),
            "truncated": offset + len(data) < file_size,
            "base64": base64.b64encode(data).decode("ascii"),
        }


# ---------------------------------------------------------------------------
# Tier 1 + Tier 2: SQL extraction wrappers
# ---------------------------------------------------------------------------

def _extract(fn, sql_path: Path | sqlite3.Connection, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Run an extractor on sql_path; a file that cannot be opened or read is a tool error, not an exception."""
    try:
        return fn(sql_path, *args, **kwargs)
    except (OSError, ValueError) as e:
        return {"ok": False, "error": "sql_unreadable", "message": f"eplusout.sql could not be opened: {e}"}
    except sqlite3.Error as e:
        return {"ok": False, "error": "sql_error", "message": f"eplusout.sql could not be read: {e}"}


def _resolve_sql(run_id: str) -> tuple[Path | None, dict | None]:
    """Resolve run_dir and find eplusout.sql. Returns (sql_path, error_dict)."""
    try:
        run_dir = resolve_run_dir(user_run_root(), run_id)
    except FileNotFoundError:
        return None, {"ok": False, "error": "run_not_found", "message": f"Unknown run_id: {run_id}"}
    sql_path = _find_first_existing(run_dir, ["run/eplusout.sql", "eplusout.sql"])
    if not sql_path:
        return None, {"ok": False, "error": "no_sql", "message": "No eplusout.sql found"}
    return sql_path, None


def extract_end_use_breakdown_op(run_id: str, units: str = "IP") -> dict[str, Any]:
    """Extract end-use energy breakdown by fuel type."""
    from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return _extract(extract_end_use_breakdown, sql_path, units)


def extract_envelope_summary_op(run_id: str) -> dict[str, Any]:
    """Extract opaque exterior and fenestration summary."""
    from mcp_server.skills.results.sql_extract import extract_envelope_summary
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return _extract(extract_envelope_summary, sql_path)


def extract_hvac_sizing_op(run_id: str) -> dict[str, Any]:
    """Extract zone and system HVAC sizing data."""
    from mcp_server.skills.results.sql_extract import extract_hvac_sizing
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return _extract(extract_hvac_sizing, sql_path)


def extract_zone_summary_op(run_id: str) -> dict[str, Any]:
    """Extract per-zone area and conditions summary."""
    from mcp_server.skills.results.sql_extract import extract_zone_summary
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return _extract(extract_zone_summary, sql_path)


def extract_component_sizing_op(
    run_id: str, component_type: str | None = None, max_results: int = 50,
) -> dict[str, Any]:
    """Extract autosized component values."""
    from mcp_server.skills.results.sql_extract import extract_component_sizing
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return _extract(extract_component_sizing, sql_path, component_type, max_results=max_results)


def query_timeseries_op(
    run_id: str,
    variable_name: str,
    key_value: str = "*",
    start_month: int | None = None,
    start_day: int | None = None,
    end_month: int | None = None,
    end_day: int | None = None,
    frequency: str | None = None,
    max_points: int = 2000,
    environment: str = "run_period",
) -> dict[str, Any]:
    """Query time-series data for a specific variable."""
    from mcp_server.skills.results.sql_extract import query_timeseries
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return _extract(
        query_timeseries, sql_path, variable_name, key_value,
        start_month, start_day, end_month, end_day,
        frequency, max_points, environment=environment,
    )


def extract_simulation_errors_op(run_id: str) -> dict[str, Any]:
    """Parse eplusout.err into categorized Fatal/Severe/Warning lists."""
    from mcp_server.skills.results.err_parser import parse_err_file
    try:
        run_dir = resolve_run_dir(user_run_root(), run_id)
    except FileNotFoundError:
        return {"ok": False, "error": "run_not_found", "message": f"Unknown run_id: {run_id}"}

    err_path = run_dir / "run" / "eplusout.err"
    if not err_path.exists() and not err_path.is_symlink():
        err_path = run_dir / "energyplus.err"
    if not err_path.exists() and not err_path.is_symlink():
        return {"ok": False, "error": "no_err_file", "message": "No eplusout.err found"}

    if not str(err_path.resolve()).startswith(str(run_dir.resolve()) + os.sep):
        return {"ok": False, "error": "unreadable_err_file", "message": f"{err_path.name} resolves outside the run"}
    try:
        # Oversize (warning-flood) err files are parsed from the head and flagged instead of
        # being dropped; a symlink is refused.
        text, truncated = read_text_capped(err_path, MAX_ERR_READ_BYTES)
    except (ValueError, OSError) as e:
        return {"ok": False, "error": "unreadable_err_file", "message": str(e)}
    parsed = parse_err_file(text)
    return {"ok": True, "run_id": run_id, "path": str(err_path), "truncated": truncated, **parsed}


def list_output_variables_op(run_id: str) -> dict[str, Any]:
    """List available output variables and meters from a completed simulation."""
    from mcp_server.skills.results.sql_extract import list_output_variables
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return _extract(list_output_variables, sql_path)


def compare_runs_op(baseline_run_id: str, retrofit_run_id: str) -> dict[str, Any]:
    """Compare two runs — EUI delta, unmet hours delta, per-end-use breakdown."""
    from mcp_server.skills.results.sql_extract import extract_end_use_breakdown

    base_metrics = extract_summary_metrics(baseline_run_id)
    retro_metrics = extract_summary_metrics(retrofit_run_id)

    for label, run_id, metrics in (
        ("baseline", baseline_run_id, base_metrics), ("retrofit", retrofit_run_id, retro_metrics),
    ):
        if not metrics.get("ok"):
            # Keep the error code (sql_error, sql_unreadable, ...) so callers can act on it;
            # which run failed goes in the message.
            return {
                "ok": False, "error": metrics.get("error", "extraction_failed"),
                "message": f"{label} run {run_id}: "
                           f"{metrics.get('message') or metrics.get('error', 'extraction failed')}",
            }

    b = base_metrics["metrics"]
    r = retro_metrics["metrics"]

    b_eui = b.get("eui_kBtu_ft2")
    r_eui = r.get("eui_kBtu_ft2")
    delta_eui = (r_eui - b_eui) if (b_eui is not None and r_eui is not None) else None
    delta_pct = (delta_eui / b_eui * 100) if (delta_eui is not None and b_eui) else None

    b_unmet = (b.get("unmet_hours_heating") or 0) + (b.get("unmet_hours_cooling") or 0)
    r_unmet = (r.get("unmet_hours_heating") or 0) + (r.get("unmet_hours_cooling") or 0)

    # End-use deltas per fuel (both in IP/kBtu), Water excluded from energy
    b_sql, _b_err = _resolve_sql(baseline_run_id)
    r_sql, _r_err = _resolve_sql(retrofit_run_id)
    end_use_deltas: list[dict[str, Any]] = []
    fuel_totals: list[dict[str, Any]] = []
    water_use: list[dict[str, Any]] = []
    energy_grand_total = {"baseline": 0.0, "retrofit": 0.0}
    if b_sql and r_sql:
        b_eu = _extract(extract_end_use_breakdown, b_sql, units="IP")
        r_eu = _extract(extract_end_use_breakdown, r_sql, units="IP")
        for label, eu in (("baseline", b_eu), ("retrofit", r_eu)):
            if eu.get("error") in ("sql_unreadable", "sql_error"):
                return {
                    "ok": False, "error": eu["error"],
                    "message": f"{label} run {baseline_run_id if label == 'baseline' else retrofit_run_id}: "
                               f"{eu['message']}",
                }
        if b_eu.get("ok") and r_eu.get("ok"):
            b_map = {e["name"]: e for e in b_eu["end_uses"]}
            r_map = {e["name"]: e for e in r_eu["end_uses"]}
            all_cats = list(dict.fromkeys(list(b_map.keys()) + list(r_map.keys())))
            # Collect all fuel names across both runs
            all_fuels: list[str] = []
            for m in (b_map, r_map):
                for entry in m.values():
                    for k in entry:
                        if k != "name" and k not in all_fuels:
                            all_fuels.append(k)

            # Per-fuel accumulator for fuel_totals
            fuel_acc: dict[str, dict[str, float]] = {}

            def _is_water(f: str) -> bool:
                return "water" in f.lower()

            for cat in all_cats:
                b_entry = b_map.get(cat, {})
                r_entry = r_map.get(cat, {})
                for fuel in all_fuels:
                    b_val = b_entry.get(fuel, 0.0)
                    r_val = r_entry.get(fuel, 0.0)
                    if not isinstance(b_val, (int, float)):
                        b_val = 0.0
                    if not isinstance(r_val, (int, float)):
                        r_val = 0.0
                    if b_val == 0.0 and r_val == 0.0:
                        continue
                    d = r_val - b_val
                    d_pct = (d / b_val * 100) if b_val else None
                    row = {
                        "category": cat, "fuel": fuel,
                        "baseline": round(b_val, 2), "retrofit": round(r_val, 2),
                        "delta": round(d, 2),
                        "delta_pct": round(d_pct, 1) if d_pct is not None else None,
                    }
                    if _is_water(fuel):
                        water_use.append(row)
                    else:
                        end_use_deltas.append(row)

                    # Accumulate for fuel_totals
                    acc = fuel_acc.setdefault(fuel, {"baseline": 0.0, "retrofit": 0.0})
                    acc["baseline"] += b_val
                    acc["retrofit"] += r_val

            # Build fuel_totals list
            for fuel, acc in fuel_acc.items():
                d = acc["retrofit"] - acc["baseline"]
                d_pct = (d / acc["baseline"] * 100) if acc["baseline"] else None
                row = {
                    "fuel": fuel,
                    "baseline_total": round(acc["baseline"], 2),
                    "retrofit_total": round(acc["retrofit"], 2),
                    "delta": round(d, 2),
                    "delta_pct": round(d_pct, 1) if d_pct is not None else None,
                }
                fuel_totals.append(row)
                if not _is_water(fuel):
                    energy_grand_total["baseline"] += acc["baseline"]
                    energy_grand_total["retrofit"] += acc["retrofit"]

    gt_delta = energy_grand_total["retrofit"] - energy_grand_total["baseline"]
    gt_pct = (gt_delta / energy_grand_total["baseline"] * 100) if energy_grand_total["baseline"] else None

    return {
        "ok": True,
        "baseline": {"run_id": baseline_run_id, "eui_kBtu_ft2": b_eui, "unmet_hours": b_unmet},
        "retrofit": {"run_id": retrofit_run_id, "eui_kBtu_ft2": r_eui, "unmet_hours": r_unmet},
        "delta_eui_kBtu_ft2": round(delta_eui, 2) if delta_eui is not None else None,
        "delta_eui_pct": round(delta_pct, 1) if delta_pct is not None else None,
        "delta_unmet_hours": round(r_unmet - b_unmet, 1),
        "end_use_deltas": end_use_deltas,
        "fuel_totals": fuel_totals,
        "water_use": water_use,
        "energy_grand_total_kBtu": {
            "baseline": round(energy_grand_total["baseline"], 2),
            "retrofit": round(energy_grand_total["retrofit"], 2),
            "delta": round(gt_delta, 2),
            "delta_pct": round(gt_pct, 1) if gt_pct is not None else None,
        },
    }


def copy_file(file_path: str, destination: str | None = None) -> dict[str, Any]:
    """Copy a file or directory to an accessible location.

    Bypasses the MCP 1MB transport limit for large files like HTML reports.
    Supports both individual files and entire directories (e.g. measure dirs).
    Both source and destination must be within allowed roots.
    """
    from mcp_server.config import is_path_allowed

    full = Path(file_path).resolve()
    if not is_path_allowed(full):
        return {
            "ok": False, "error": "invalid_path",
            "message": f"Source not in allowed roots: {file_path}",
        }

    if not full.exists():
        return {"ok": False, "error": "not_found", "message": f"Not found: {file_path}"}

    dest_dir = Path(destination) if destination else (user_run_root() / "exports")
    if not is_path_allowed(dest_dir, write=True):
        return {
            "ok": False, "error": "invalid_destination",
            "message": f"Destination not in allowed roots: {destination}",
        }
    # Created through directory descriptors from the tenant root (#190): a component of the
    # destination swapped for a link after the check above must not be created through.
    try:
        DirHandle.open(dest_dir, create=True).close()
    except (OSError, ValueError) as e:  # ValueError: a '..' component or a non-directory on the way
        return {
            "ok": False, "error": "invalid_destination",
            "message": f"Destination could not be created: {e}",
        }

    if full.is_dir():
        # Run dirs are tenant-written: a planted link would make a pathname copy follow it
        link_err = reject_escaping_symlinks(full)
        if link_err:
            return {"ok": False, "error": "symlink_in_source", "message": link_err}
        dest_path = dest_dir / full.name
        if dest_path.is_symlink():
            return {"ok": False, "error": "invalid_destination", "message": f"Destination is a symlink: {dest_path}"}
        # Both trees walked by descriptor (#190): a component of either swapped for a link after
        # the checks above fails the copy; an existing entry at the destination name is removed
        # through its parent's descriptor, never through a link.
        try:
            counts = copy_tree_confined(full, dest_path, replace=True, max_file_bytes=MAX_COPY_FILE_BYTES)
        except (OSError, ValueError) as e:
            return {"ok": False, "error": "copy_failed", "message": f"Could not copy {full.name}: {e}"}
        return {
            "ok": True,
            "source": str(full),
            "destination": str(dest_path),
            "type": "directory",
            "file_count": counts["files"],
        }

    dest_file = dest_dir / full.name
    if full.is_symlink() or dest_file.is_symlink():
        return {"ok": False, "error": "symlink_refused", "message": "Source or destination is a symlink"}
    # Descriptor-walked no-follow copy (#190): run dirs are tenant-written, so a link
    # planted above either end after the check above must not redirect the copy.
    try:
        copy_regular_file_nofollow(full, dest_file, MAX_COPY_FILE_BYTES)
    except (OSError, ValueError) as e:
        return {"ok": False, "error": "copy_failed", "message": f"Could not copy {full.name}: {e}"}
    result = {
        "ok": True,
        "source": str(full),
        "destination": str(dest_file),
        "size_bytes": dest_file.stat().st_size,
    }
    if full.suffix.lower() == ".osm":
        carried = _copy_model_resources(full, dest_file)
        if not carried["ok"]:
            return {**carried, "destination": str(dest_file)}
        result.update(carried)
    return result


def _copy_model_resources(src_osm: Path, dest_osm: Path) -> dict[str, Any]:
    """Carry a model's companion folder with its OSM copy (the Application's unit).

    The saved resources only (companion folder, legacy sibling until
    migrated): the session's pending workspace is not part of the file on
    disk and the OSM bytes copied are the saved ones. A same-named file at
    the destination is replaced and reported; nothing is deleted. The
    migration marker is written whether or not there were resources, so the
    copy never reads `<dest dir>/files/` as its own legacy resources. A
    regular resource that could not be copied fails the call (the OSM copy
    is still reported in `destination`) and leaves no marker.
    """
    from mcp_server.resources import (
        companion_files_dir,
        copy_resources,
        mark_legacy_migrated,
        resource_dir_issue,
        resource_sources,
    )

    dst_files = companion_files_dir(dest_osm)
    issue = resource_dir_issue(dst_files, write=True)
    if issue:
        return {"ok": False, "error": "invalid_destination",
                "message": f"Model resources not copied: {issue}"}
    try:
        sources = resource_sources(src_osm)
        outcome = (copy_resources(sources, dst_files, overwrite=True) if sources
                   else {"copied": [], "replaced": [], "skipped": []})
    except ValueError as e:
        return {"ok": False, "error": "resources_not_copied", "message": f"Model resources not copied: {e}"}
    failed = [f"{rel} ({why})" for rel, why in outcome["skipped"] if why != "not a regular file"]
    if failed:
        return {"ok": False, "error": "resources_not_copied",
                "message": "Model resources not copied: " + "; ".join(failed)}
    try:
        mark_legacy_migrated(dest_osm)
    except ValueError as e:
        return {"ok": False, "error": "resources_not_copied",
                "message": f"Model resources copied but the migration marker was refused: {e}"}
    return {
        "ok": True,
        "resource_count": len(outcome["copied"]),
        "replaced_resources": sorted(outcome["replaced"]),
        "skipped_resources": [rel for rel, _ in outcome["skipped"]],
    }
