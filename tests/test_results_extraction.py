"""Tests for SQL results extraction tools (Tier 1 + Tier 2).

Uses pre-baked eplusout_seb4.sql fixture — no Docker/simulation needed.
"""
from __future__ import annotations

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
            extract_end_use_breakdown, extract_envelope_summary,
            extract_hvac_sizing, extract_zone_summary,
            extract_component_sizing, query_timeseries,
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


class TestMissingSql:
    def test_end_use_bad_path(self):
        from mcp_server.skills.results.sql_extract import extract_end_use_breakdown
        # Nonexistent path should raise (sqlite3 error)
        with pytest.raises(Exception):
            extract_end_use_breakdown(Path("/nonexistent/eplusout.sql"))

    def test_envelope_bad_path(self):
        from mcp_server.skills.results.sql_extract import extract_envelope_summary
        with pytest.raises(Exception):
            extract_envelope_summary(Path("/nonexistent/eplusout.sql"))
