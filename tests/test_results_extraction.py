"""Tests for SQL results extraction tools (Tier 1 + Tier 2).

Uses pre-baked eplusout_seb4.sql fixture — no Docker/simulation needed.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

# Pre-baked SQL fixture from SEB4 baseboard simulation
SQL_PATH = Path(__file__).parent / "assets" / "eplusout_seb4.sql"


@pytest.fixture
def sql_path():
    assert SQL_PATH.exists(), f"Test fixture missing: {SQL_PATH}"
    return SQL_PATH


# ---------------------------------------------------------------------------
# Tier 1: extract_end_use_breakdown
# ---------------------------------------------------------------------------

class TestEndUseBreakdown:
    def test_happy_path_ip(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
        result = extract_end_use_breakdown(sql_path, units="IP")
        assert result["ok"] is True
        assert len(result["end_uses"]) > 0
        assert result["totals"]  # non-empty totals
        # Should have Heating in some form
        names = [e["name"] for e in result["end_uses"]]
        assert any("Heating" in n for n in names)
        # IP units — values should be kBtu (large numbers)
        assert "kBtu" in result.get("units_note", "")

    def test_happy_path_si(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
        result = extract_end_use_breakdown(sql_path, units="SI")
        assert result["ok"] is True
        assert len(result["end_uses"]) > 0
        assert "SI" in result.get("units_note", "")

    def test_totals_match_sum(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
        result = extract_end_use_breakdown(sql_path, units="SI")
        # Electricity total should roughly equal sum of individual electricity values
        if "Electricity" in result["totals"]:
            total_elec = result["totals"]["Electricity"]
            sum_elec = sum(
                e.get("Electricity", 0) for e in result["end_uses"]
            )
            assert abs(total_elec - sum_elec) < 0.1


# ---------------------------------------------------------------------------
# Tier 1: extract_envelope_summary
# ---------------------------------------------------------------------------

class TestEnvelopeSummary:
    def test_happy_path(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_envelope_summary
        result = extract_envelope_summary(sql_path)
        assert result["ok"] is True
        assert len(result["opaque_exterior"]) > 0
        assert len(result["fenestration"]) > 0
        # Opaque should have construction info
        first_opaque = result["opaque_exterior"][0]
        assert "name" in first_opaque
        assert "construction" in first_opaque or any("construct" in k for k in first_opaque)
        # Fenestration should have glass properties
        first_fen = result["fenestration"][0]
        assert "name" in first_fen


# ---------------------------------------------------------------------------
# Tier 1: extract_hvac_sizing
# ---------------------------------------------------------------------------

class TestHVACSizing:
    def test_happy_path(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_hvac_sizing
        result = extract_hvac_sizing(sql_path)
        assert result["ok"] is True
        assert len(result["zone_sizing"]) > 0
        assert len(result["system_sizing"]) > 0
        # Zone should have cooling/heating prefixed keys
        first_zone = result["zone_sizing"][0]
        assert "zone" in first_zone
        cooling_keys = [k for k in first_zone if k.startswith("cooling_")]
        heating_keys = [k for k in first_zone if k.startswith("heating_")]
        assert len(cooling_keys) > 0
        assert len(heating_keys) > 0


# ---------------------------------------------------------------------------
# Tier 1: extract_zone_summary
# ---------------------------------------------------------------------------

class TestZoneSummary:
    def test_happy_path(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_zone_summary
        result = extract_zone_summary(sql_path)
        assert result["ok"] is True
        assert len(result["zones"]) > 0
        first_zone = result["zones"][0]
        assert "zone" in first_zone
        # Should have area info
        assert any("area" in k for k in first_zone)

    def test_zone_count(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_zone_summary
        result = extract_zone_summary(sql_path)
        # SEB4 has 10 zones (from exploration)
        assert len(result["zones"]) >= 5


# ---------------------------------------------------------------------------
# Tier 1: extract_component_sizing
# ---------------------------------------------------------------------------

class TestComponentSizing:
    def test_happy_path(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_component_sizing
        result = extract_component_sizing(sql_path)
        assert result["ok"] is True
        assert len(result["components"]) > 0
        first = result["components"][0]
        assert "type" in first
        assert "name" in first
        assert "properties" in first

    def test_filter_by_type(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_component_sizing
        result = extract_component_sizing(sql_path, component_type="Coil")
        assert result["ok"] is True
        # All returned components should contain "Coil" in type
        for c in result["components"]:
            assert "Coil" in c["type"] or "coil" in c["type"].lower()

    def test_filter_no_match(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_component_sizing
        result = extract_component_sizing(sql_path, component_type="NonexistentWidget")
        assert result["ok"] is True
        assert result["components"] == []


# ---------------------------------------------------------------------------
# Tier 2: query_timeseries
# ---------------------------------------------------------------------------

class TestQueryTimeseries:
    def test_happy_path_daily(self, sql_path):
        from mcp_server.skills.results.sql_extract import query_timeseries
        result = query_timeseries(sql_path, variable_name="Electricity:Facility", frequency="Daily")
        assert result["ok"] is True
        assert result["count"] > 0
        assert len(result["data"]) > 0
        # Each data point should have month/day/value
        first = result["data"][0]
        assert "month" in first
        assert "day" in first
        assert "value" in first

    def test_date_range_filter(self, sql_path):
        from mcp_server.skills.results.sql_extract import query_timeseries
        result = query_timeseries(
            sql_path, variable_name="Electricity:Facility",
            frequency="Daily", start_month=1, end_month=1,
        )
        assert result["ok"] is True
        # All data should be in January
        for pt in result["data"]:
            assert pt["month"] == 1

    def test_cap_enforcement(self, sql_path):
        from mcp_server.skills.results.sql_extract import query_timeseries
        result = query_timeseries(
            sql_path, variable_name="Electricity",
            max_points=5,
        )
        assert result["ok"] is True
        assert result["count"] <= 5
        if result["total_available"] > 5:
            assert result["truncated"] is True

    def test_no_match_variable(self, sql_path):
        from mcp_server.skills.results.sql_extract import query_timeseries
        result = query_timeseries(sql_path, variable_name="Nonexistent:Variable")
        assert result["ok"] is True
        assert result["count"] == 0
        assert result["data"] == []


# ---------------------------------------------------------------------------
# Error paths: missing SQL
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Example 11: Full workflow
# ---------------------------------------------------------------------------

class TestExampleWorkflow:
    """Example 11: Results extraction workflow using pre-baked SQL."""

    def test_full_results_deep_dive(self, sql_path):
        from mcp_server.skills.results.sql_extract import (
            extract_component_sizing,
            extract_end_use_breakdown,
            extract_envelope_summary,
            extract_hvac_sizing,
            extract_zone_summary,
            query_timeseries,
        )
        # Step 1: End use breakdown
        end_uses = extract_end_use_breakdown(sql_path, units="IP")
        assert end_uses["ok"] and len(end_uses["end_uses"]) > 0

        # Step 2: Envelope
        envelope = extract_envelope_summary(sql_path)
        assert envelope["ok"] and len(envelope["opaque_exterior"]) > 0

        # Step 3: HVAC sizing
        sizing = extract_hvac_sizing(sql_path)
        assert sizing["ok"] and len(sizing["zone_sizing"]) > 0

        # Step 4: Zone summary
        zones = extract_zone_summary(sql_path)
        assert zones["ok"] and len(zones["zones"]) > 0

        # Step 5: Component sizing (coils only)
        coils = extract_component_sizing(sql_path, component_type="Coil")
        assert coils["ok"]
        for c in coils["components"]:
            assert "coil" in c["type"].lower()

        # Step 6: January daily electricity
        ts = query_timeseries(
            sql_path, "Electricity:Facility",
            frequency="Daily", start_month=1, end_month=1,
        )
        assert ts["ok"] and ts["count"] > 0
        assert all(pt["month"] == 1 for pt in ts["data"])


# ---------------------------------------------------------------------------
# Regression: extract_eui — must return GJ total, not MJ/m2 per-area column
# ---------------------------------------------------------------------------

class TestExtractEui:
    def test_total_site_energy_value(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_eui
        result = extract_eui(sql_path)
        assert result["total_site_energy"] == pytest.approx(6965.32, abs=0.1)

    def test_building_area(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_eui
        result = extract_eui(sql_path)
        assert result["total_building_area"] == pytest.approx(10000.0, abs=1.0)

    def test_computed_eui(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_eui
        result = extract_eui(sql_path)
        assert result["computed_eui"] == pytest.approx(0.696532, rel=1e-3)
        assert result["eui_MJ_m2"] == pytest.approx(696.532, rel=1e-3)
        assert result["eui_kBtu_ft2"] == pytest.approx(61.34, rel=1e-2)

    def test_units_are_gj(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_eui
        result = extract_eui(sql_path)
        assert result["total_site_energy_units"] == "GJ"

    def test_decoy_column_ignored(self, sql_path, tmp_path):
        """ColumnName='Area' filter must prevent LIMIT 1 from picking a decoy col."""
        import shutil, sqlite3
        decoy_sql = tmp_path / "decoy.sql"
        shutil.copy(sql_path, decoy_sql)
        conn = sqlite3.connect(str(decoy_sql))
        # TabularDataWithStrings is a view over TabularData + Strings.
        # Insert a decoy via the underlying tables.
        # First, find existing StringIndex values for reuse
        row = conn.execute(
            "SELECT ReportNameIndex, ReportForStringIndex, TableNameIndex, RowNameIndex, UnitsIndex "
            "FROM TabularData td "
            "JOIN Strings cn ON cn.StringIndex = td.ColumnNameIndex "
            "JOIN Strings tn ON tn.StringIndex = td.TableNameIndex "
            "WHERE cn.Value = 'Area' AND tn.Value = 'Building Area' "
            "LIMIT 1"
        ).fetchone()
        # Add a new string for the bogus column name (Strings has 3 cols: index, type, value)
        max_idx = conn.execute("SELECT MAX(StringIndex) FROM Strings").fetchone()[0]
        bogus_idx = max_idx + 1
        # StringTypeIndex=5 is the ColumnName type (same as existing ColumnName entries)
        col_type = conn.execute(
            "SELECT StringTypeIndex FROM Strings s "
            "JOIN TabularData td ON td.ColumnNameIndex = s.StringIndex "
            "LIMIT 1"
        ).fetchone()[0]
        conn.execute("INSERT INTO Strings VALUES (?, ?, 'BogusColumn')", (bogus_idx, col_type))
        # Insert decoy row reusing existing indexes but with bogus ColumnName
        conn.execute(
            "INSERT INTO TabularData "
            "(ReportNameIndex, ReportForStringIndex, TableNameIndex, RowNameIndex, "
            "ColumnNameIndex, UnitsIndex, SimulationIndex, RowId, ColumnId, Value) "
            "VALUES (?, ?, ?, ?, ?, ?, 1, 0, 0, '99.0')",
            (row[0], row[1], row[2], row[3], bogus_idx, row[4]),
        )
        conn.commit()
        conn.close()

        from mcp_server.skills.results.sql_extract import extract_eui
        result = extract_eui(decoy_sql)
        # Must still return the real 10000 m², not the decoy 99.0
        assert result["total_building_area"] == pytest.approx(10000.0, abs=1.0)


# ---------------------------------------------------------------------------
# Regression: extract_unmet_hours — must not return None/None
# ---------------------------------------------------------------------------

class TestExtractUnmetHours:
    def test_heating(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_unmet_hours
        result = extract_unmet_hours(sql_path)
        assert result["heating"] == pytest.approx(1808.33, abs=0.1)

    def test_cooling(self, sql_path):
        from mcp_server.skills.results.sql_extract import extract_unmet_hours
        result = extract_unmet_hours(sql_path)
        assert result["cooling"] == pytest.approx(0.0, abs=0.1)


# ---------------------------------------------------------------------------
# Regression: _extract_total_site_energy_from_sql — must return GJ, col=Total Energy
# ---------------------------------------------------------------------------

class TestExtractTotalSiteEnergy:
    def test_returns_gj(self, sql_path):
        from mcp_server.skills.results.operations import _extract_total_site_energy_from_sql
        result = _extract_total_site_energy_from_sql(sql_path)
        assert result["ok"] is True
        assert result["value"] == pytest.approx(6965.32, abs=0.1)
        assert result["column_name"] == "Total Energy"
        assert result["units"] == "GJ"


class TestEndUseConversionFactor:
    """C-3 regression: GJ→kBtu factor must be 947.817, not 947817.12."""

    def test_ip_values_in_kbtu_range(self, sql_path):
        """IP end-use values should be kBtu (hundreds to millions), not GBtu."""
        from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
        si = extract_end_use_breakdown(sql_path, units="SI")
        ip = extract_end_use_breakdown(sql_path, units="IP")
        assert si["ok"] and ip["ok"]
        # Pick first non-zero numeric value from SI and IP
        for si_entry, ip_entry in zip(si["end_uses"], ip["end_uses"]):
            for k in si_entry:
                if k == "name":
                    continue
                si_val = si_entry.get(k)
                ip_val = ip_entry.get(k)
                if isinstance(si_val, (int, float)) and si_val > 0:
                    # 1 GJ = 947.817 kBtu — ratio should be ~948, not ~948000
                    ratio = ip_val / si_val
                    assert 900 < ratio < 1000, (
                        f"IP/SI ratio for {k}={ratio:.1f}, expected ~947.8 "
                        f"(si={si_val}, ip={ip_val})"
                    )
                    return  # one check is enough
        pytest.skip("No non-zero SI values found to verify conversion")


class TestMissingSql:
    def test_end_use_bad_path(self):
        from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
        # Nonexistent path should raise (sqlite3 error)
        with pytest.raises((sqlite3.OperationalError, OSError)):
            extract_end_use_breakdown(Path("/nonexistent/eplusout.sql"))

    def test_envelope_bad_path(self):
        from mcp_server.skills.results.sql_extract import extract_envelope_summary
        with pytest.raises((sqlite3.OperationalError, OSError)):
            extract_envelope_summary(Path("/nonexistent/eplusout.sql"))
