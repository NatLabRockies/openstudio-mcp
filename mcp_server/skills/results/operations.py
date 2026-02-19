from __future__ import annotations

import base64
import mimetypes
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Optional

from mcp_server.config import RUN_ROOT
from mcp_server.util import resolve_run_dir, safe_read_text


def _find_first_existing(run_dir: Path, rel_candidates: list[str]) -> Optional[Path]:
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
    """Best-effort extraction of Total Site Energy from EnergyPlus SQL.

    EnergyPlus stores tabular reports in TabularDataWithStrings. Column/row names vary slightly
    across versions and report configurations, so we search flexibly.
    """
    conn = sqlite3.connect(str(sql_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='TabularDataWithStrings'"
        )
        if not cur.fetchone():
            return {"ok": False, "reason": "missing_tabular_table"}

        q = """
        SELECT *
        FROM TabularDataWithStrings
        WHERE
          (lower(TableName) LIKE '%site%' AND lower(TableName) LIKE '%energy%')
          AND (lower(RowName) LIKE '%total site energy%')
        LIMIT 10
        """
        rows = conn.execute(q).fetchall()
        if not rows:
            q2 = """
            SELECT *
            FROM TabularDataWithStrings
            WHERE lower(RowName) LIKE '%total site energy%'
            LIMIT 10
            """
            rows = conn.execute(q2).fetchall()

        if not rows:
            return {"ok": False, "reason": "not_found"}

        def score(r: sqlite3.Row) -> int:
            """Rank candidate rows by relevance to total site energy."""
            s = 0
            if (r["TableName"] or "").lower().find("site") >= 0:
                s += 3
            if (r["ReportName"] or "").lower().find("annual") >= 0:
                s += 1
            if (r["Units"] or "").strip():
                s += 1
            if re.search(r"[-+]?\d+(\.\d+)?", (r["Value"] or "")):
                s += 2
            return s

        best = sorted(rows, key=score, reverse=True)[0]
        value_str = (best["Value"] or "").strip()
        units = (best["Units"] or "").strip() or None

        m = re.search(r"[-+]?\d+(?:\.\d+)?", value_str.replace(",", ""))
        if not m:
            return {"ok": False, "reason": "non_numeric_value", "value": value_str, "units": units}

        val = float(m.group(0))
        return {
            "ok": True,
            "value": val,
            "units": units,
            "report_name": best["ReportName"],
            "table_name": best["TableName"],
            "row_name": best["RowName"],
            "column_name": best["ColumnName"],
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


def _to_kbtu(value: float, units: Optional[str]) -> Optional[float]:
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


def extract_summary_metrics(run_id: str) -> dict[str, Any]:
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
            from mcp_server.skills.results.sql_extract import extract_unmet_hours, extract_eui  # type: ignore

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

    return {
        "ok": True,
        "run_id": run_id,
        "paths": {
            "run_dir": str(run_dir),
            "sql": str(sql_path) if sql_path else None,
            "html": str(html_path) if html_path else None,
        },
        "metrics": {
            "total_site_energy": {
                "value": total_site_value,
                "units": total_site_units,
                "kbtu": total_site_kbtu,
                "source": total_site_src if total_site_value is not None else None,
                "detail": total_site_detail,
            },
            "unmet_hours_heating": unmet.get("heating") if isinstance(unmet, dict) else None,
            "unmet_hours_cooling": unmet.get("cooling") if isinstance(unmet, dict) else None,
            "eui": (eui.get("computed_eui") if isinstance(eui, dict) else None),
            "eui_units": (eui.get("computed_eui_units") if isinstance(eui, dict) else None),
            "raw": {"unmet": unmet, "eui": eui},
        },
    }


def read_run_artifact(
    run_id: str, path: str, max_bytes: int = 400_000, offset: int = 0,
) -> dict[str, Any]:
    """Read an artifact file from a run directory safely.

    - `path` must be relative to the run directory (no absolute paths).
    - `offset` allows chunked reading (byte offset to start from).
    - For text-like files, returns `text`.
    - For binary/unknown, returns `base64` + `mime`.
    """
    try:
        run_dir = resolve_run_dir(RUN_ROOT, run_id)
    except FileNotFoundError:
        return {"ok": False, "error": "run_not_found", "message": f"Unknown run_id: {run_id}"}

    if path.startswith("/") or path.startswith("\\"):
        return {"ok": False, "error": "invalid_path", "message": "path must be relative to run_dir"}

    full = (run_dir / path).resolve()
    if run_dir.resolve() not in full.parents and full != run_dir.resolve():
        return {"ok": False, "error": "invalid_path", "message": "path escapes run_dir"}

    if not full.exists() or not full.is_file():
        return {"ok": False, "error": "not_found", "message": f"Missing file: {path}", "run_id": run_id}

    file_size = full.stat().st_size

    # Read with optional offset for chunked reading
    with open(full, "rb") as f:
        if offset > 0:
            f.seek(offset)
        data = f.read(max_bytes)

    # Try decode as utf-8 text
    try:
        text = data.decode("utf-8")
        return {
            "ok": True,
            "run_id": run_id,
            "path": path,
            "abs_path": str(full),
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
            "run_id": run_id,
            "path": path,
            "abs_path": str(full),
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

def _resolve_sql(run_id: str) -> tuple[Optional[Path], Optional[dict]]:
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


def extract_component_sizing_op(run_id: str, component_type: Optional[str] = None) -> dict[str, Any]:
    """Extract autosized component values."""
    from mcp_server.skills.results.sql_extract import extract_component_sizing
    sql_path, err = _resolve_sql(run_id)
    if err:
        return err
    return extract_component_sizing(sql_path, component_type)


def query_timeseries_op(
    run_id: str,
    variable_name: str,
    key_value: str = "*",
    start_month: Optional[int] = None,
    start_day: Optional[int] = None,
    end_month: Optional[int] = None,
    end_day: Optional[int] = None,
    frequency: Optional[str] = None,
    max_points: int = 10000,
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


def copy_run_artifact(run_id: str, path: str, destination: str = "/runs/exports") -> dict[str, Any]:
    """Copy a run artifact to an accessible location without streaming through MCP.

    Bypasses the MCP 1MB transport limit for large files like HTML reports.
    The destination is on the same bind-mounted volume, so the file is
    directly accessible on the host filesystem.
    """
    try:
        run_dir = resolve_run_dir(RUN_ROOT, run_id)
    except FileNotFoundError:
        return {"ok": False, "error": "run_not_found", "message": f"Unknown run_id: {run_id}"}

    if path.startswith("/") or path.startswith("\\"):
        return {"ok": False, "error": "invalid_path", "message": "path must be relative to run_dir"}

    full = (run_dir / path).resolve()
    if run_dir.resolve() not in full.parents and full != run_dir.resolve():
        return {"ok": False, "error": "invalid_path", "message": "path escapes run_dir"}

    if not full.exists() or not full.is_file():
        return {"ok": False, "error": "not_found", "message": f"Missing file: {path}", "run_id": run_id}

    dest_dir = Path(destination)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / full.name

    shutil.copy2(str(full), str(dest_file))

    return {
        "ok": True,
        "run_id": run_id,
        "source": str(full),
        "destination": str(dest_file),
        "size_bytes": dest_file.stat().st_size,
    }
