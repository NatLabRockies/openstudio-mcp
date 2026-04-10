"""Tests for SQL results extraction tools (Tier 1 + Tier 2).

Uses pre-baked eplusout_seb4.sql fixture — no Docker/simulation needed.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

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
        # Validates: extract_end_use_breakdown IP returns Heating end-use in kBtu units
        from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
        result = extract_end_use_breakdown(sql_path, units="IP")
        assert result["ok"] is True
        assert len(result["end_uses"]) > 0
        assert len(result["totals"]) > 0, "Totals should be non-empty"
        names = [e["name"] for e in result["end_uses"]]
        assert any("Heating" in n for n in names)
        assert "kBtu" in result["units_note"]
        # Concrete value checks for SEB4 fixture
        assert result["totals"]["Electricity"] > 0, "SEB4 should have positive Electricity total"
        heating_entry = next(e for e in result["end_uses"] if "Heating" in e["name"])
        heating_total = sum(v for k, v in heating_entry.items() if isinstance(v, (int, float)))
        assert heating_total > 0, f"SEB4 Heating end-use should have non-zero values: {heating_entry}"

    def test_happy_path_si(self, sql_path):
        # Validates: extract_end_use_breakdown SI returns end-uses with SI units note
        from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
        result = extract_end_use_breakdown(sql_path, units="SI")
        assert result["ok"] is True
        assert len(result["end_uses"]) > 0
        assert "SI" in result["units_note"]

    def test_totals_match_sum(self, sql_path):
        # Validates: Electricity total equals sum of individual Electricity end-use values
        from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
        result = extract_end_use_breakdown(sql_path, units="SI")
        assert "Electricity" in result["totals"], "SEB4 should have Electricity total"
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
        # Validates: extract_envelope_summary returns opaque and fenestration data with names
        from mcp_server.skills.results.sql_extract import extract_envelope_summary
        result = extract_envelope_summary(sql_path)
        assert result["ok"] is True
        assert len(result["opaque_exterior"]) > 0
        assert len(result["fenestration"]) > 0
        first_opaque = result["opaque_exterior"][0]
        assert len(first_opaque["name"]) > 0, "Opaque surface should have a name"
        assert "construction" in first_opaque or any("construct" in k for k in first_opaque)
        first_fen = result["fenestration"][0]
        assert len(first_fen["name"]) > 0, "Fenestration should have a name"


# ---------------------------------------------------------------------------
# Tier 1: extract_hvac_sizing
# ---------------------------------------------------------------------------

class TestHVACSizing:
    def test_happy_path(self, sql_path):
        # Validates: extract_hvac_sizing returns zone and system sizing with cooling/heating keys
        from mcp_server.skills.results.sql_extract import extract_hvac_sizing
        result = extract_hvac_sizing(sql_path)
        assert result["ok"] is True
        assert len(result["zone_sizing"]) > 0
        assert len(result["system_sizing"]) > 0
        first_zone = result["zone_sizing"][0]
        assert len(first_zone["zone"]) > 0, "Zone sizing should have zone name"
        cooling_keys = [k for k in first_zone if k.startswith("cooling_")]
        heating_keys = [k for k in first_zone if k.startswith("heating_")]
        assert len(cooling_keys) > 0, "Zone sizing should have cooling_ prefixed keys"
        assert len(heating_keys) > 0, "Zone sizing should have heating_ prefixed keys"


# ---------------------------------------------------------------------------
# Tier 1: extract_zone_summary
# ---------------------------------------------------------------------------

class TestZoneSummary:
    def test_happy_path(self, sql_path):
        # Validates: extract_zone_summary returns zones with name and area data
        from mcp_server.skills.results.sql_extract import extract_zone_summary
        result = extract_zone_summary(sql_path)
        assert result["ok"] is True
        assert len(result["zones"]) > 0
        first_zone = result["zones"][0]
        assert len(first_zone["zone"]) > 0, "Zone should have a name"
        assert any("area" in k for k in first_zone), "Zone should have area data"

    def test_zone_count(self, sql_path):
        # Validates: SEB4 model has at least 5 zones in zone summary
        from mcp_server.skills.results.sql_extract import extract_zone_summary
        result = extract_zone_summary(sql_path)
        assert len(result["zones"]) >= 5, f"SEB4 should have >= 5 zones, got {len(result['zones'])}"


# ---------------------------------------------------------------------------
# Tier 1: extract_component_sizing
# ---------------------------------------------------------------------------

class TestComponentSizing:
    def test_happy_path(self, sql_path):
        # Validates: extract_component_sizing returns components with type/name/properties
        from mcp_server.skills.results.sql_extract import extract_component_sizing
        result = extract_component_sizing(sql_path)
        assert result["ok"] is True
        assert len(result["components"]) > 0
        first = result["components"][0]
        assert len(first["type"]) > 0, "Component should have a type"
        assert len(first["name"]) > 0, "Component should have a name"
        assert len(first["properties"]) > 0, "Component should have sizing properties"

    def test_filter_by_type(self, sql_path):
        # Validates: component_type filter returns only matching components
        from mcp_server.skills.results.sql_extract import extract_component_sizing
        result = extract_component_sizing(sql_path, component_type="Coil")
        assert result["ok"] is True
        for c in result["components"]:
            assert "coil" in c["type"].lower(), f"Filter leaked non-Coil: {c['type']}"

    def test_filter_no_match(self, sql_path):
        # Validates: nonexistent component_type filter returns empty list (not error)
        from mcp_server.skills.results.sql_extract import extract_component_sizing
        result = extract_component_sizing(sql_path, component_type="NonexistentWidget")
        assert result["ok"] is True
        assert result["components"] == []


# ---------------------------------------------------------------------------
# Tier 2: query_timeseries
# ---------------------------------------------------------------------------

class TestQueryTimeseries:
    def test_happy_path_daily(self, sql_path):
        # Validates: query_timeseries returns daily Electricity data with month/day/value
        from mcp_server.skills.results.sql_extract import query_timeseries
        result = query_timeseries(sql_path, variable_name="Electricity:Facility", frequency="Daily")
        assert result["ok"] is True
        assert result["count"] > 0
        assert len(result["data"]) > 0
        first = result["data"][0]
        assert isinstance(first["month"], int)
        assert isinstance(first["day"], int)
        assert isinstance(first["value"], (int, float))

    def test_date_range_filter(self, sql_path):
        # Validates: start_month/end_month filter restricts data to January only
        from mcp_server.skills.results.sql_extract import query_timeseries
        result = query_timeseries(
            sql_path, variable_name="Electricity:Facility",
            frequency="Daily", start_month=1, end_month=1,
        )
        assert result["ok"] is True
        for pt in result["data"]:
            assert pt["month"] == 1, f"Expected January data only, got month {pt['month']}"

    def test_cap_enforcement(self, sql_path):
        # Validates: max_points caps output and sets truncated flag
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
        # Validates: nonexistent variable returns empty data (not error)
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
        # Validates: full results extraction workflow (end-use -> envelope -> sizing -> zones -> coils -> timeseries)
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
        # Regression: extract_eui must return GJ total (6965.32) not MJ/m2 per-area
        from mcp_server.skills.results.sql_extract import extract_eui
        result = extract_eui(sql_path)
        assert result["total_site_energy"] == pytest.approx(6965.32, abs=0.1)

    def test_building_area(self, sql_path):
        # Validates: extract_eui returns correct building area (10000 m2) from SEB4
        from mcp_server.skills.results.sql_extract import extract_eui
        result = extract_eui(sql_path)
        assert result["total_building_area"] == pytest.approx(10000.0, abs=1.0)

    def test_computed_eui(self, sql_path):
        # Validates: computed EUI in GJ/m2, MJ/m2, and kBtu/ft2 match known SEB4 values
        from mcp_server.skills.results.sql_extract import extract_eui
        result = extract_eui(sql_path)
        assert result["computed_eui"] == pytest.approx(0.696532, rel=1e-3)
        assert result["eui_MJ_m2"] == pytest.approx(696.532, rel=1e-3)
        assert result["eui_kBtu_ft2"] == pytest.approx(61.34, rel=1e-2)

    def test_units_are_gj(self, sql_path):
        # Validates: total_site_energy_units is GJ (not MJ or kBtu)
        from mcp_server.skills.results.sql_extract import extract_eui
        result = extract_eui(sql_path)
        assert result["total_site_energy_units"] == "GJ"

    def test_decoy_column_ignored(self, sql_path, tmp_path):
        # Regression: ColumnName='Area' filter must prevent LIMIT 1 from picking a decoy col
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
        # Regression: extract_unmet_hours must return numeric values (not None)
        from mcp_server.skills.results.sql_extract import extract_unmet_hours
        result = extract_unmet_hours(sql_path)
        assert result["heating"] == pytest.approx(1808.33, abs=0.1)

    def test_cooling(self, sql_path):
        # Validates: SEB4 cooling unmet hours is 0.0 (baseboard heating-only system)
        from mcp_server.skills.results.sql_extract import extract_unmet_hours
        result = extract_unmet_hours(sql_path)
        assert result["cooling"] == pytest.approx(0.0, abs=0.1)


# ---------------------------------------------------------------------------
# Regression: _extract_total_site_energy_from_sql — must return GJ, col=Total Energy
# ---------------------------------------------------------------------------

class TestExtractTotalSiteEnergy:
    def test_returns_gj(self, sql_path):
        # Regression: _extract_total_site_energy must use col='Total Energy' in GJ units
        from mcp_server.skills.results.operations import _extract_total_site_energy_from_sql
        result = _extract_total_site_energy_from_sql(sql_path)
        assert result["ok"] is True
        assert result["value"] == pytest.approx(6965.32, abs=0.1)
        assert result["column_name"] == "Total Energy"
        assert result["units"] == "GJ"


class TestEndUseConversionFactor:
    """C-3 regression: GJ→kBtu factor must be 947.817, not 947817.12."""

    def test_ip_values_in_kbtu_range(self, sql_path):
        # Regression: GJ->kBtu factor must be ~947.817 (IP/SI ratio ~948, not ~948000)
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


# ---------------------------------------------------------------------------
# list_output_variables
# ---------------------------------------------------------------------------

class TestListOutputVariables:
    def test_happy_path(self, sql_path):
        # Validates: list_output_variables returns variables or meters from SEB4 SQL
        from mcp_server.skills.results.sql_extract import list_output_variables
        result = list_output_variables(sql_path)
        assert result["ok"] is True
        total = result.get("variable_count", 0) + result.get("meter_count", 0)
        assert total > 0, "SEB4 should have output variables or meters"

    def test_has_frequency_grouping(self, sql_path):
        # Validates: output variables are grouped by frequency (at least one bucket)
        from mcp_server.skills.results.sql_extract import list_output_variables
        result = list_output_variables(sql_path)
        assert result["ok"] is True
        all_freqs = list(result.get("variables", {}).keys()) + list(result.get("meters", {}).keys())
        assert len(all_freqs) > 0, "Should have at least one frequency grouping"

    def test_entry_structure(self, sql_path):
        # Validates: output variable entries have name/units/key_values fields
        from mcp_server.skills.results.sql_extract import list_output_variables
        result = list_output_variables(sql_path)
        for freq, entries in result.get("variables", {}).items():
            if entries:
                e = entries[0]
                assert len(e["name"]) > 0
                assert len(e["units"]) > 0
                assert isinstance(e["key_values"], list)
                return
        for freq, entries in result.get("meters", {}).items():
            if entries:
                e = entries[0]
                assert len(e["name"]) > 0
                assert len(e["units"]) > 0
                return
        pytest.fail("No variables or meters found to check structure")


# ---------------------------------------------------------------------------
# extract_summary_metrics warnings
# ---------------------------------------------------------------------------

class TestSummaryMetricsWarnings:
    def test_high_unmet_warning(self, sql_path):
        # Validates: SEB4 ~1808 unmet heating hours triggers "Unmet hours" warning
        from mcp_server.skills.results.operations import extract_summary_metrics
        # We need a run_dir with the SQL in it
        import shutil, tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            (run_dir / "run").mkdir(parents=True)
            shutil.copy(sql_path, run_dir / "run" / "eplusout.sql")
            # Monkey-patch resolve_run_dir for this test
            import mcp_server.skills.results.operations as ops
            orig = ops.resolve_run_dir
            ops.resolve_run_dir = lambda root, rid: run_dir
            try:
                result = extract_summary_metrics("test_run")
                assert result["ok"] is True
                assert any("Unmet hours" in w for w in result.get("warnings", []))
            finally:
                ops.resolve_run_dir = orig


# ---------------------------------------------------------------------------
# compare_runs_op: per-fuel deltas, Water exclusion
# ---------------------------------------------------------------------------

class TestCompareRuns:
    """compare_runs_op must return per-fuel deltas and exclude Water from energy totals."""

    @pytest.fixture
    def _patch_runs(self, sql_path):
        """Set up two fake run dirs pointing to the same SQL for shape testing."""
        import shutil, tempfile
        import mcp_server.skills.results.operations as ops
        tmpdir = tempfile.mkdtemp()
        for rid in ("baseline_run", "retrofit_run"):
            run_dir = Path(tmpdir) / rid
            (run_dir / "run").mkdir(parents=True)
            shutil.copy(sql_path, run_dir / "run" / "eplusout.sql")
        orig = ops.resolve_run_dir
        ops.resolve_run_dir = lambda root, rid: Path(tmpdir) / rid
        yield
        ops.resolve_run_dir = orig
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_output_shape(self, sql_path, _patch_runs):
        # Validates: compare_runs_op returns end_use_deltas/fuel_totals/water_use/grand_total keys
        from mcp_server.skills.results.operations import compare_runs_op
        result = compare_runs_op("baseline_run", "retrofit_run")
        assert result["ok"] is True
        assert isinstance(result["end_use_deltas"], list)
        assert isinstance(result["fuel_totals"], list)
        assert isinstance(result["water_use"], list)
        assert isinstance(result["energy_grand_total_kBtu"], dict)

    def test_end_use_deltas_have_fuel_field(self, sql_path, _patch_runs):
        # Validates: each end_use_delta row has fuel/category/baseline/retrofit fields
        from mcp_server.skills.results.operations import compare_runs_op
        result = compare_runs_op("baseline_run", "retrofit_run")
        for row in result["end_use_deltas"]:
            assert "fuel" in row, f"Missing 'fuel' key in end_use_delta: {row}"
            assert "category" in row
            assert "baseline" in row
            assert "retrofit" in row

    def test_water_excluded_from_energy(self, sql_path, _patch_runs):
        # Regression: Water rows must be excluded from energy deltas, placed in water_use
        from mcp_server.skills.results.operations import compare_runs_op
        result = compare_runs_op("baseline_run", "retrofit_run")
        for row in result["end_use_deltas"]:
            assert "water" not in row["fuel"].lower(), (
                f"Water found in end_use_deltas: {row}"
            )
        for row in result["water_use"]:
            assert "water" in row["fuel"].lower()

    def test_fuel_totals_structure(self, sql_path, _patch_runs):
        # Validates: fuel_totals rows have fuel/baseline_total/retrofit_total/delta
        from mcp_server.skills.results.operations import compare_runs_op
        result = compare_runs_op("baseline_run", "retrofit_run")
        for row in result["fuel_totals"]:
            assert isinstance(row["fuel"], str)
            assert isinstance(row["baseline_total"], (int, float))
            assert isinstance(row["retrofit_total"], (int, float))
            assert isinstance(row["delta"], (int, float))

    def test_grand_total_excludes_water(self, sql_path, _patch_runs):
        # Validates: energy_grand_total equals sum of non-water fuel_totals
        from mcp_server.skills.results.operations import compare_runs_op
        result = compare_runs_op("baseline_run", "retrofit_run")
        gt = result["energy_grand_total_kBtu"]
        expected = sum(
            r["baseline_total"] for r in result["fuel_totals"]
            if "water" not in r["fuel"].lower()
        )
        assert abs(gt["baseline"] - expected) < 0.1

    def test_same_run_zero_deltas(self, sql_path, _patch_runs):
        # Validates: comparing same SQL produces zero deltas everywhere
        from mcp_server.skills.results.operations import compare_runs_op
        result = compare_runs_op("baseline_run", "retrofit_run")
        for row in result["end_use_deltas"]:
            assert row["delta"] == 0.0, f"Non-zero delta for same run: {row}"
        gt = result["energy_grand_total_kBtu"]
        assert gt["delta"] == 0.0


class TestMissingSql:
    def test_end_use_bad_path(self):
        # Validates: extract_end_use_breakdown raises on nonexistent SQL path
        from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
        with pytest.raises((sqlite3.OperationalError, OSError)):
            extract_end_use_breakdown(Path("/nonexistent/eplusout.sql"))

    def test_envelope_bad_path(self):
        # Validates: extract_envelope_summary raises on nonexistent SQL path
        from mcp_server.skills.results.sql_extract import extract_envelope_summary
        with pytest.raises((sqlite3.OperationalError, OSError)):
            extract_envelope_summary(Path("/nonexistent/eplusout.sql"))
