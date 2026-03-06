from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def _q(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql, params)
    return cur.fetchall()

def _try_float(s: Any) -> float | None:
    if s is None:
        return None
    try:
        return float(str(s).strip())
    except Exception:
        return None

def extract_unmet_hours(sql_path: Path) -> dict:
    conn = sqlite3.connect(str(sql_path))
    try:
        # Exact-match queries against SystemSummary / Time Setpoint Not Met
        # (matches openstudio_results reference measure)
        heating_rows = _q(conn, """
            SELECT Value FROM TabularDataWithStrings
            WHERE ReportName = 'SystemSummary'
              AND ReportForString = 'Entire Facility'
              AND TableName = 'Time Setpoint Not Met'
              AND RowName = 'Facility'
              AND ColumnName = 'During Occupied Heating'
            LIMIT 1
        """)
        cooling_rows = _q(conn, """
            SELECT Value FROM TabularDataWithStrings
            WHERE ReportName = 'SystemSummary'
              AND ReportForString = 'Entire Facility'
              AND TableName = 'Time Setpoint Not Met'
              AND RowName = 'Facility'
              AND ColumnName = 'During Occupied Cooling'
            LIMIT 1
        """)
        heating = _try_float(heating_rows[0]["Value"]) if heating_rows else None
        cooling = _try_float(cooling_rows[0]["Value"]) if cooling_rows else None
        return {
            "heating": heating, "cooling": cooling,
            "source": "TabularDataWithStrings/SystemSummary/Time Setpoint Not Met",
        }
    finally:
        conn.close()

def extract_eui(sql_path: Path) -> dict:
    conn = sqlite3.connect(str(sql_path))
    try:
        # Get building area from the "Building Area" table (units: m2)
        # ColumnName='Area' required — without it LIMIT 1 may pick a wrong col
        area_rows = _q(conn, """
            SELECT Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName = 'AnnualBuildingUtilityPerformanceSummary'
              AND ReportForString = 'Entire Facility'
              AND TableName = 'Building Area'
              AND RowName = 'Total Building Area'
              AND ColumnName = 'Area'
            LIMIT 1
        """)
        area = _try_float(area_rows[0]["Value"]) if area_rows else None
        area_units = area_rows[0]["Units"] if area_rows else None

        # Get total site energy from "Site and Source Energy" table (units: GJ)
        # ColumnName filter needed — table has 3 cols: Total Energy (GJ),
        # Energy Per Total Building Area (MJ/m2), Energy Per Conditioned Building Area (MJ/m2)
        energy_rows = _q(conn, """
            SELECT Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName = 'AnnualBuildingUtilityPerformanceSummary'
              AND ReportForString = 'Entire Facility'
              AND TableName = 'Site and Source Energy'
              AND RowName = 'Total Site Energy'
              AND ColumnName = 'Total Energy'
            LIMIT 1
        """)
        total_site = _try_float(energy_rows[0]["Value"]) if energy_rows else None
        total_site_units = energy_rows[0]["Units"] if energy_rows else None

        eui_gj_m2 = None
        eui_mj_m2 = None
        eui_kbtu_ft2 = None
        if total_site is not None and area not in (None, 0):
            eui_gj_m2 = total_site / area  # GJ / m²
            eui_mj_m2 = eui_gj_m2 * 1000.0  # MJ / m²
            eui_kbtu_ft2 = eui_gj_m2 * 947.817 / 10.7639  # kBtu / ft²

        return {
            "total_site_energy": total_site,
            "total_site_energy_units": total_site_units,
            "total_building_area": area,
            "total_building_area_units": area_units,
            "computed_eui": eui_gj_m2,
            "computed_eui_units": "GJ/m2",
            "eui_MJ_m2": eui_mj_m2,
            "eui_kBtu_ft2": eui_kbtu_ft2,
            "source": "TabularDataWithStrings/AnnualBuildingUtilityPerformanceSummary",
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tier 1: Tabular report extractors
# ---------------------------------------------------------------------------

def extract_end_use_breakdown(sql_path: Path, units: str = "IP") -> dict:
    """Extract end-use energy breakdown by fuel type from AnnualBuildingUtilityPerformanceSummary."""
    conn = sqlite3.connect(str(sql_path))
    try:
        rows = _q(conn, """
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName = 'AnnualBuildingUtilityPerformanceSummary'
              AND TableName = 'End Uses'
        """)
        if not rows:
            return {"ok": True, "end_uses": [], "totals": {},
                    "source": "AnnualBuildingUtilityPerformanceSummary/End Uses"}

        # Collect all fuel columns and end-use rows
        data: dict[str, dict[str, float]] = {}  # row_name -> {col_name: value}

        for r in rows:
            row_name = (r["RowName"] or "").strip()
            col_name = (r["ColumnName"] or "").strip()
            val = _try_float(r["Value"])
            if not row_name or not col_name:
                continue
            if val is not None and val != 0.0:
                data.setdefault(row_name, {})[col_name] = val

        # Build result list (skip rows with all zeros)
        end_uses = []
        totals_row = None
        for row_name, fuels in data.items():
            if row_name.lower().startswith("total"):
                totals_row = fuels
                continue
            entry: dict[str, Any] = {"name": row_name}
            entry.update(fuels)
            end_uses.append(entry)

        # Conversion: GJ -> kBtu for IP
        units_note = "SI (original units from SQL)"
        if units.upper() == "IP":
            factor = 947.817  # GJ -> kBtu (1 GJ = 947.817 kBtu)
            units_note = "Converted to kBtu"
            for entry in end_uses:
                for k, v in list(entry.items()):
                    if k != "name" and isinstance(v, (int, float)):
                        entry[k] = round(v * factor, 2)
            if totals_row:
                totals_row = {k: round(v * factor, 2) for k, v in totals_row.items()}

        return {
            "ok": True,
            "end_uses": end_uses,
            "totals": totals_row or {},
            "units_note": units_note,
            "source": "AnnualBuildingUtilityPerformanceSummary/End Uses",
        }
    finally:
        conn.close()


def extract_envelope_summary(sql_path: Path) -> dict:
    """Extract opaque exterior and fenestration data from EnvelopeSummary."""
    conn = sqlite3.connect(str(sql_path))
    try:
        # Opaque exterior surfaces
        opaque_rows = _q(conn, """
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName = 'EnvelopeSummary'
              AND TableName = 'Opaque Exterior'
        """)
        opaque = _pivot_rows(opaque_rows)

        # Fenestration
        fen_rows = _q(conn, """
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName = 'EnvelopeSummary'
              AND TableName = 'Exterior Fenestration'
        """)
        fenestration = _pivot_rows(fen_rows)

        return {
            "ok": True,
            "opaque_exterior": opaque,
            "fenestration": fenestration,
            "source": "EnvelopeSummary",
        }
    finally:
        conn.close()


def extract_hvac_sizing(sql_path: Path) -> dict:
    """Extract zone and system sizing from HVACSizingSummary."""
    conn = sqlite3.connect(str(sql_path))
    try:
        # Zone sensible cooling
        zone_cool = _q(conn, """
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName = 'HVACSizingSummary'
              AND TableName = 'Zone Sensible Cooling'
        """)
        # Zone sensible heating
        zone_heat = _q(conn, """
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName = 'HVACSizingSummary'
              AND TableName = 'Zone Sensible Heating'
        """)
        # Merge cooling + heating per zone
        cool_map = _pivot_rows_map(zone_cool)
        heat_map = _pivot_rows_map(zone_heat)
        zone_names = list(dict.fromkeys(list(cool_map.keys()) + list(heat_map.keys())))
        zone_sizing = []
        for zn in zone_names:
            entry: dict[str, Any] = {"zone": zn}
            c = cool_map.get(zn, {})
            h = heat_map.get(zn, {})
            for k, v in c.items():
                entry[f"cooling_{k}"] = v
            for k, v in h.items():
                entry[f"heating_{k}"] = v
            zone_sizing.append(entry)

        # System sizing
        sys_rows = _q(conn, """
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName = 'HVACSizingSummary'
              AND TableName = 'System Design Air Flow Rates'
        """)
        system_sizing = _pivot_rows(sys_rows, name_key="system")

        return {
            "ok": True,
            "zone_sizing": zone_sizing,
            "system_sizing": system_sizing,
            "source": "HVACSizingSummary",
        }
    finally:
        conn.close()


def extract_zone_summary(sql_path: Path) -> dict:
    """Extract per-zone area/conditions from InputVerificationandResultsSummary."""
    conn = sqlite3.connect(str(sql_path))
    try:
        rows = _q(conn, """
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName = 'InputVerificationandResultsSummary'
              AND TableName = 'Zone Summary'
        """)
        zones = _pivot_rows(rows, name_key="zone")

        return {
            "ok": True,
            "zones": zones,
            "source": "InputVerificationandResultsSummary/Zone Summary",
        }
    finally:
        conn.close()


def extract_component_sizing(sql_path: Path, component_type: str | None = None) -> dict:
    """Extract autosized component values from ComponentSizingSummary."""
    conn = sqlite3.connect(str(sql_path))
    try:
        if component_type:
            rows = _q(conn, """
                SELECT TableName, RowName, ColumnName, Value, Units
                FROM TabularDataWithStrings
                WHERE ReportName LIKE '%ComponentSizingSummary%'
                  AND TableName LIKE ?
            """, (f"%{component_type}%",))
        else:
            rows = _q(conn, """
                SELECT TableName, RowName, ColumnName, Value, Units
                FROM TabularDataWithStrings
                WHERE ReportName LIKE '%ComponentSizingSummary%'
            """)

        if not rows:
            return {"ok": True, "components": [],
                    "source": "ComponentSizingSummary"}

        # Group by TableName (component type) + RowName (instance)
        grouped: dict[str, dict[str, dict[str, Any]]] = {}
        for r in rows:
            tbl = (r["TableName"] or "").strip()
            row_name = (r["RowName"] or "").strip()
            col = (r["ColumnName"] or "").strip()
            if not tbl or not row_name or not col:
                continue
            val = _try_float(r["Value"])
            grouped.setdefault(tbl, {}).setdefault(row_name, {})[_snake(col)] = (
                val if val is not None else (r["Value"] or "").strip()
            )

        components = []
        for comp_type, instances in grouped.items():
            for inst_name, props in instances.items():
                components.append({
                    "type": comp_type,
                    "name": inst_name,
                    "properties": props,
                })

        return {
            "ok": True,
            "components": components,
            "source": "ComponentSizingSummary",
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tier 2: Time-series extractor
# ---------------------------------------------------------------------------

def query_timeseries(
    sql_path: Path,
    variable_name: str,
    key_value: str = "*",
    start_month: int | None = None,
    start_day: int | None = None,
    end_month: int | None = None,
    end_day: int | None = None,
    frequency: str | None = None,
    max_points: int = 10000,
) -> dict:
    """Query time-series data from ReportData/ReportDataDictionary/Time tables."""
    conn = sqlite3.connect(str(sql_path))
    try:
        # Check if ReportData has any rows
        cnt = _q(conn, "SELECT COUNT(*) as c FROM ReportData")[0]["c"]
        if cnt == 0:
            return {
                "ok": True, "data": [], "count": 0,
                "message": "No timeseries data. Add output variables via add_output_variable before running simulation.",
            }

        # Build query with filters
        where_clauses = ["rdd.Name LIKE ?"]
        params: list[Any] = [f"%{variable_name}%"]

        if key_value != "*":
            where_clauses.append("rdd.KeyValue LIKE ?")
            params.append(f"%{key_value}%")

        if frequency:
            where_clauses.append("rdd.ReportingFrequency LIKE ?")
            params.append(f"%{frequency}%")

        # Date range filters on Time table
        if start_month is not None:
            where_clauses.append("(t.Month > ? OR (t.Month = ? AND t.Day >= ?))")
            params.extend([start_month, start_month, start_day or 1])
        if end_month is not None:
            where_clauses.append("(t.Month < ? OR (t.Month = ? AND t.Day <= ?))")
            params.extend([end_month, end_month, end_day or 31])

        # Only run-period data (skip design days / warmup)
        where_clauses.append("t.WarmupFlag = 0")

        where_sql = " AND ".join(where_clauses)

        # Count total available
        count_sql = f"""
            SELECT COUNT(*) as c
            FROM ReportData rd
            JOIN ReportDataDictionary rdd ON rd.ReportDataDictionaryIndex = rdd.ReportDataDictionaryIndex
            JOIN Time t ON rd.TimeIndex = t.TimeIndex
            WHERE {where_sql}
        """
        total_available = _q(conn, count_sql, tuple(params))[0]["c"]

        # Fetch data with cap
        data_sql = f"""
            SELECT rd.Value, t.Month, t.Day, t.Hour, t.Minute,
                   rdd.Name, rdd.KeyValue, rdd.Units, rdd.ReportingFrequency
            FROM ReportData rd
            JOIN ReportDataDictionary rdd ON rd.ReportDataDictionaryIndex = rdd.ReportDataDictionaryIndex
            JOIN Time t ON rd.TimeIndex = t.TimeIndex
            WHERE {where_sql}
            ORDER BY t.Month, t.Day, t.Hour, t.Minute
            LIMIT ?
        """
        rows = _q(conn, data_sql, (*params, max_points))

        if not rows:
            return {
                "ok": True, "variable": variable_name, "key": key_value,
                "data": [], "count": 0,
                "message": f"No data found for variable '{variable_name}'.",
            }

        data = []
        for r in rows:
            data.append({
                "month": r["Month"], "day": r["Day"],
                "hour": r["Hour"], "minute": r["Minute"],
                "value": r["Value"],
            })

        return {
            "ok": True,
            "variable": rows[0]["Name"],
            "key": rows[0]["KeyValue"] or "*",
            "frequency": rows[0]["ReportingFrequency"],
            "units": rows[0]["Units"],
            "data": data,
            "count": len(data),
            "total_available": total_available,
            "truncated": len(data) < total_available,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Helpers for pivoting TabularDataWithStrings rows
# ---------------------------------------------------------------------------

def _snake(s: str) -> str:
    """Convert column name to snake_case key."""
    return s.lower().replace(" ", "_").replace("-", "_").replace("/", "_")


def _pivot_rows_map(rows: list[sqlite3.Row]) -> dict[str, dict[str, Any]]:
    """Pivot rows into {row_name: {col_snake: value}} map."""
    result: dict[str, dict[str, Any]] = {}
    for r in rows:
        row_name = (r["RowName"] or "").strip()
        col = (r["ColumnName"] or "").strip()
        if not row_name or not col:
            continue
        val = _try_float(r["Value"])
        result.setdefault(row_name, {})[_snake(col)] = val if val is not None else (r["Value"] or "").strip()
    return result


def _pivot_rows(rows: list[sqlite3.Row], name_key: str = "name") -> list[dict[str, Any]]:
    """Pivot rows into list of dicts, one per unique RowName."""
    pivot_map = _pivot_rows_map(rows)
    result = []
    for row_name, cols in pivot_map.items():
        entry: dict[str, Any] = {name_key: row_name}
        entry.update(cols)
        result.append(entry)
    return result
