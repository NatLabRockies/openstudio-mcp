"""Tests for EnergyPlus .err file parser — no Docker needed."""
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.skills.results.err_parser import parse_err_file

ERR_FIXTURE = Path(__file__).parent / "assets" / "eplusout_sample.err"


@pytest.fixture
def err_text():
    assert ERR_FIXTURE.exists(), f"Missing fixture: {ERR_FIXTURE}"
    return ERR_FIXTURE.read_text()


class TestParseErrFile:
    def test_fatal_count(self, err_text):
        result = parse_err_file(err_text)
        assert len(result["fatal"]) == 1

    def test_severe_count(self, err_text):
        result = parse_err_file(err_text)
        assert len(result["severe"]) == 2

    def test_warning_count(self, err_text):
        result = parse_err_file(err_text)
        assert result["warning_count"] == 25

    def test_continuation_lines_merged(self, err_text):
        result = parse_err_file(err_text)
        # Severe about DX coil should have continuation merged
        coil_severe = [s for s in result["severe"] if "GetDXCoils" in s]
        assert len(coil_severe) == 1
        assert "referenced from" in coil_severe[0]

    def test_warning_continuation_merged(self, err_text):
        result = parse_err_file(err_text)
        # Warning about weather location has continuation
        weather_warn = [w for w in result["warnings"] if "Weather file" in w]
        assert len(weather_warn) == 1
        assert "Location object" in weather_warn[0]

    def test_warnings_capped(self, err_text):
        result = parse_err_file(err_text, max_warnings=5)
        assert len(result["warnings"]) == 5
        assert result["warning_count"] == 25

    def test_summary_format(self, err_text):
        result = parse_err_file(err_text)
        assert "1 Fatal" in result["summary"]
        assert "2 Severe" in result["summary"]
        assert "25 Warnings" in result["summary"]

    def test_empty_input(self):
        result = parse_err_file("")
        assert result["fatal"] == []
        assert result["severe"] == []
        assert result["warnings"] == []
        assert result["warning_count"] == 0
        assert result["summary"] == "No errors"

    def test_clean_run(self):
        clean = (
            "Program Version,EnergyPlus, Version 24.2.0\n"
            "   ************* EnergyPlus Completed Successfully-- 0 Warning; 0 Severe Errors\n"
        )
        result = parse_err_file(clean)
        assert result["fatal"] == []
        assert result["severe"] == []
        assert result["warning_count"] == 0
