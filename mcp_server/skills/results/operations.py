from __future__ import annotations

import base64
import mimetypes
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from mcp_server.config import RUN_ROOT
from mcp_server.util import resolve_run_dir, safe_read_text  # resolve_run_dir still used by extract_* ops


def _find_first_existing(run_dir: Path, rel_candidates: list[str]) -> Path | None:
    """Find the first existing file from a list of relative path candidates."""
    for rel in rel_candidates:
        p = run_dir / rel
        if p.exists():
            return p
    # fallback: search a little
    for pat in ["eplusout.sql", "eplustbl.htm", "eplustbl.html"]:
        hits = list(run_dir.rglob(pat))
        if hits:
            return hits[0]
    return None


def _extract_total_site_energy_from_sql(sql_path: Path) -> dict[str, Any]:
    """Extract Total Site Energy (GJ) from EnergyPlus SQL via precise query."""
    conn = sqlite3.connect(str(sql_path))
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
        conn.close()


def _extract_total_site_energy_from_html(html_path: Path) -> dict[str, Any]:
    """Extract total site energy from EnergyPlus HTML tabular report."""
    txt = safe_read_text(html_path, max_bytes=800_000)
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
        run_dir = resolve_run_dir(RUN_ROOT, run_id)
    except FileNotFoundError:
        return {"ok": False, "error": "run_not_found", "message": f"Unknown run_id: {run_id}"}

    sql_path = _find_first_existing(run_dir, ["run/eplusout.sql", "eplusout.sql"])
    html_path = _find_first_existing(
        run_dir,
        ["run/eplustbl.htm", "run/eplustbl.html", "eplustbl.htm", "eplustbl.html"],
    )

    total_site = None
    total_site_src = None
    if sql_path and sql_path.suffix.lower() == ".sql":
        total_site = _extract_total_site_energy_from_sql(sql_path)
        total_site_src = "sql"
        if not total_site.get("ok"):
            total_site = None
    if total_site is None and html_path:
        total_site = _extract_total_site_energy_from_html(html_path)
        total_site_src = "html"
        if not total_site.get("ok"):
            total_site = None

    unmet = None
    eui = None
    if sql_path and sql_path.suffix.lower() == ".sql":
        try:
            from mcp_server.skills.results.sql_extract import (  # type: ignore[import-not-found]
                extract_eui,
                extract_unmet_hours,
            )

            unmet = extract_unmet_hours(sql_path)
            eui = extract_eui(sql_path)
        except Exception:
            unmet = None
            eui = None

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

def _resolve_sql(run_id: str) -> tuple[Path | None, dict | None]:
    """Resolve run_dir and find eplusout.sql. Returns (sql_path, error_dict)."""
    try:
        run_dir = resolve_run_dir(RUN_ROOT, run_id)
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
    return extract_end_use_breakdown(sql_path, units)


def extract_envelope_summary_op(run_id: str) -> dict[str, Any]:
    """Extract opaque exterior and fenestration summary."""
    from mcp_server.skills.results.sql_extract import extract_envelope_summary
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return extract_envelope_summary(sql_path)


def extract_hvac_sizing_op(run_id: str) -> dict[str, Any]:
    """Extract zone and system HVAC sizing data."""
    from mcp_server.skills.results.sql_extract import extract_hvac_sizing
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return extract_hvac_sizing(sql_path)


def extract_zone_summary_op(run_id: str) -> dict[str, Any]:
    """Extract per-zone area and conditions summary."""
    from mcp_server.skills.results.sql_extract import extract_zone_summary
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return extract_zone_summary(sql_path)


def extract_component_sizing_op(
    run_id: str, component_type: str | None = None, max_results: int = 50,
) -> dict[str, Any]:
    """Extract autosized component values."""
    from mcp_server.skills.results.sql_extract import extract_component_sizing
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return extract_component_sizing(sql_path, component_type, max_results=max_results)


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
) -> dict[str, Any]:
    """Query time-series data for a specific variable."""
    from mcp_server.skills.results.sql_extract import query_timeseries
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return query_timeseries(
        sql_path, variable_name, key_value,
        start_month, start_day, end_month, end_day,
        frequency, max_points,
    )


def extract_simulation_errors_op(run_id: str) -> dict[str, Any]:
    """Parse eplusout.err into categorized Fatal/Severe/Warning lists."""
    from mcp_server.skills.results.err_parser import parse_err_file
    try:
        run_dir = resolve_run_dir(RUN_ROOT, run_id)
    except FileNotFoundError:
        return {"ok": False, "error": "run_not_found", "message": f"Unknown run_id: {run_id}"}

    err_path = run_dir / "run" / "eplusout.err"
    if not err_path.exists():
        err_path = run_dir / "energyplus.err"
    if not err_path.exists():
        return {"ok": False, "error": "no_err_file", "message": "No eplusout.err found"}

    parsed = parse_err_file(err_path.read_text(errors="replace"))
    return {"ok": True, "run_id": run_id, "path": str(err_path), **parsed}


def list_output_variables_op(run_id: str) -> dict[str, Any]:
    """List available output variables and meters from a completed simulation."""
    from mcp_server.skills.results.sql_extract import list_output_variables
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return list_output_variables(sql_path)


def compare_runs_op(baseline_run_id: str, retrofit_run_id: str) -> dict[str, Any]:
    """Compare two runs — EUI delta, unmet hours delta, per-end-use breakdown."""
    from mcp_server.skills.results.sql_extract import extract_end_use_breakdown

    base_metrics = extract_summary_metrics(baseline_run_id)
    retro_metrics = extract_summary_metrics(retrofit_run_id)

    if not base_metrics.get("ok"):
        return {"ok": False, "error": f"baseline: {base_metrics.get('error', 'extraction failed')}"}
    if not retro_metrics.get("ok"):
        return {"ok": False, "error": f"retrofit: {retro_metrics.get('error', 'extraction failed')}"}

    b = base_metrics["metrics"]
    r = retro_metrics["metrics"]

    b_eui = b.get("eui_kBtu_ft2")
    r_eui = r.get("eui_kBtu_ft2")
    delta_eui = (r_eui - b_eui) if (b_eui is not None and r_eui is not None) else None
    delta_pct = (delta_eui / b_eui * 100) if (delta_eui is not None and b_eui) else None

    b_unmet = (b.get("unmet_hours_heating") or 0) + (b.get("unmet_hours_cooling") or 0)
    r_unmet = (r.get("unmet_hours_heating") or 0) + (r.get("unmet_hours_cooling") or 0)

    # End-use deltas (both in IP/kBtu)
    b_sql, _b_err = _resolve_sql(baseline_run_id)
    r_sql, _r_err = _resolve_sql(retrofit_run_id)
    end_use_deltas: list[dict[str, Any]] = []
    if b_sql and r_sql:
        b_eu = extract_end_use_breakdown(b_sql, units="IP")
        r_eu = extract_end_use_breakdown(r_sql, units="IP")
        if b_eu.get("ok") and r_eu.get("ok"):
            b_map = {e["name"]: e for e in b_eu["end_uses"]}
            r_map = {e["name"]: e for e in r_eu["end_uses"]}
            all_cats = list(dict.fromkeys(list(b_map.keys()) + list(r_map.keys())))
            for cat in all_cats:
                b_total = sum(v for k, v in b_map.get(cat, {}).items()
                              if k != "name" and isinstance(v, (int, float)))
                r_total = sum(v for k, v in r_map.get(cat, {}).items()
                              if k != "name" and isinstance(v, (int, float)))
                d = r_total - b_total
                d_pct = (d / b_total * 100) if b_total else None
                end_use_deltas.append({
                    "category": cat, "baseline_kBtu": round(b_total, 2),
                    "retrofit_kBtu": round(r_total, 2),
                    "delta_kBtu": round(d, 2), "delta_pct": round(d_pct, 1) if d_pct is not None else None,
                })

    return {
        "ok": True,
        "baseline": {"run_id": baseline_run_id, "eui_kBtu_ft2": b_eui, "unmet_hours": b_unmet},
        "retrofit": {"run_id": retrofit_run_id, "eui_kBtu_ft2": r_eui, "unmet_hours": r_unmet},
        "delta_eui_kBtu_ft2": round(delta_eui, 2) if delta_eui is not None else None,
        "delta_eui_pct": round(delta_pct, 1) if delta_pct is not None else None,
        "delta_unmet_hours": round(r_unmet - b_unmet, 1),
        "end_use_deltas": end_use_deltas,
    }


def copy_file(file_path: str, destination: str = "/runs/exports") -> dict[str, Any]:
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

    dest_dir = Path(destination)
    if not is_path_allowed(dest_dir):
        return {
            "ok": False, "error": "invalid_destination",
            "message": f"Destination not in allowed roots: {destination}",
        }
    dest_dir.mkdir(parents=True, exist_ok=True)

    if full.is_dir():
        dest_path = dest_dir / full.name
        if dest_path.exists():
            shutil.rmtree(str(dest_path))
        shutil.copytree(str(full), str(dest_path))
        file_count = sum(1 for _ in dest_path.rglob("*") if _.is_file())
        return {
            "ok": True,
            "source": str(full),
            "destination": str(dest_path),
            "type": "directory",
            "file_count": file_count,
        }

    dest_file = dest_dir / full.name
    shutil.copy2(str(full), str(dest_file))
    return {
        "ok": True,
        "source": str(full),
        "destination": str(dest_file),
        "size_bytes": dest_file.stat().st_size,
    }
