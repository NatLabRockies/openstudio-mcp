from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any, Optional

def _q(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    cur = conn.execute(sql, params)
    return cur.fetchall()

def _try_float(s: Any) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(str(s).strip())
    except Exception:
        return None

def extract_unmet_hours(sql_path: Path) -> dict:
    conn = sqlite3.connect(str(sql_path))
    try:
        rows = _q(conn, '''
            SELECT ReportName, TableName, RowName, ColumnName, Value
            FROM TabularDataWithStrings
            WHERE ReportName LIKE '%AnnualBuildingUtilityPerformanceSummary%'
              AND TableName LIKE '%Comfort%Setpoint%Not Met%'
        ''')
        heating = None
        cooling = None
        for r in rows:
            col = (r["ColumnName"] or "").lower()
            val = _try_float(r["Value"])
            if val is None:
                continue
            if heating is None and ("heating" in col) and ("occupied" in col):
                heating = val
            if cooling is None and ("cooling" in col) and ("occupied" in col):
                cooling = val
        return {"heating": heating, "cooling": cooling, "source": "TabularDataWithStrings/Comfort and Setpoint Not Met Summary"}
    finally:
        conn.close()

def extract_eui(sql_path: Path) -> dict:
    conn = sqlite3.connect(str(sql_path))
    try:
        rows = _q(conn, '''
            SELECT ReportName, TableName, RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName LIKE '%AnnualBuildingUtilityPerformanceSummary%'
        ''')
        total_site = None
        total_site_units = None
        area = None
        area_units = None

        for r in rows:
            table = (r["TableName"] or "").lower()
            row = (r["RowName"] or "").lower()
            col = (r["ColumnName"] or "").lower()
            val = _try_float(r["Value"])
            if val is None:
                continue

            if area is None and ("area" in row or "area" in col or "building area" in table):
                if "total" in row or "total" in col:
                    area = val
                    area_units = r["Units"]

            if total_site is None and ("site" in table or "site" in row or "site" in col):
                if ("total" in row and "energy" in row) or ("total site energy" in row) or ("net site energy" in row):
                    total_site = val
                    total_site_units = r["Units"]

        eui = None
        if total_site is not None and area not in (None, 0):
            eui = total_site / area

        return {
            "total_site_energy": total_site,
            "total_site_energy_units": total_site_units,
            "total_building_area": area,
            "total_building_area_units": area_units,
            "computed_eui": eui,
            "computed_eui_units": f"{total_site_units}/{area_units}" if (total_site_units and area_units) else None,
            "source": "TabularDataWithStrings/AnnualBuildingUtilityPerformanceSummary"
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
        rows = _q(conn, '''
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName LIKE '%AnnualBuildingUtilityPerformanceSummary%'
              AND TableName = 'End Uses'
        ''')
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
            factor = 947817.12  # GJ -> kBtu
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
        opaque_rows = _q(conn, '''
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName LIKE '%EnvelopeSummary%'
              AND TableName LIKE '%Opaque Exterior%'
        ''')
        opaque = _pivot_rows(opaque_rows)

        # Fenestration
        fen_rows = _q(conn, '''
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName LIKE '%EnvelopeSummary%'
              AND TableName LIKE '%Exterior Fenestration%'
              AND TableName NOT LIKE '%Shaded%'
        ''')
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
        zone_cool = _q(conn, '''
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName LIKE '%HVACSizingSummary%'
              AND TableName LIKE '%Zone Sensible Cooling%'
        ''')
        # Zone sensible heating
        zone_heat = _q(conn, '''
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName LIKE '%HVACSizingSummary%'
              AND TableName LIKE '%Zone Sensible Heating%'
        ''')
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
        sys_rows = _q(conn, '''
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName LIKE '%HVACSizingSummary%'
              AND TableName LIKE '%System Design Air Flow%'
        ''')
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
        rows = _q(conn, '''
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE ReportName LIKE '%InputVerification%Results%'
              AND TableName LIKE '%Zone Summary%'
        ''')
        zones = _pivot_rows(rows, name_key="zone")

        return {
            "ok": True,
            "zones": zones,
            "source": "InputVerificationandResultsSummary/Zone Summary",
        }
    finally:
        conn.close()


def extract_component_sizing(sql_path: Path, component_type: Optional[str] = None) -> dict:
    """Extract autosized component values from ComponentSizingSummary."""
    conn = sqlite3.connect(str(sql_path))
    try:
        if component_type:
            rows = _q(conn, '''
                SELECT TableName, RowName, ColumnName, Value, Units
                FROM TabularDataWithStrings
                WHERE ReportName LIKE '%ComponentSizingSummary%'
                  AND TableName LIKE ?
            ''', (f'%{component_type}%',))
        else:
            rows = _q(conn, '''
                SELECT TableName, RowName, ColumnName, Value, Units
                FROM TabularDataWithStrings
                WHERE ReportName LIKE '%ComponentSizingSummary%'
            ''')

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
    start_month: Optional[int] = None,
    start_day: Optional[int] = None,
    end_month: Optional[int] = None,
    end_day: Optional[int] = None,
    frequency: Optional[str] = None,
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
        params: list[Any] = [f'%{variable_name}%']

        if key_value != "*":
            where_clauses.append("rdd.KeyValue LIKE ?")
            params.append(f'%{key_value}%')

        if frequency:
            where_clauses.append("rdd.ReportingFrequency LIKE ?")
            params.append(f'%{frequency}%')

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
        count_sql = f'''
            SELECT COUNT(*) as c
            FROM ReportData rd
            JOIN ReportDataDictionary rdd ON rd.ReportDataDictionaryIndex = rdd.ReportDataDictionaryIndex
            JOIN Time t ON rd.TimeIndex = t.TimeIndex
            WHERE {where_sql}
        '''
        total_available = _q(conn, count_sql, tuple(params))[0]["c"]

        # Fetch data with cap
        data_sql = f'''
            SELECT rd.Value, t.Month, t.Day, t.Hour, t.Minute,
                   rdd.Name, rdd.KeyValue, rdd.Units, rdd.ReportingFrequency
            FROM ReportData rd
            JOIN ReportDataDictionary rdd ON rd.ReportDataDictionaryIndex = rdd.ReportDataDictionaryIndex
            JOIN Time t ON rd.TimeIndex = t.TimeIndex
            WHERE {where_sql}
            ORDER BY t.Month, t.Day, t.Hour, t.Minute
            LIMIT ?
        '''
        rows = _q(conn, data_sql, tuple(params + [max_points]))

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
