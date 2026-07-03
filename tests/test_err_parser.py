"""Tests for EnergyPlus .err file parser — no Docker needed."""
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.skills.results.err_parser import parse_err_file

pytestmark = pytest.mark.unit

ERR_FIXTURE = Path(__file__).parent / "assets" / "eplusout_sample.err"


@pytest.fixture
def err_text():
    assert ERR_FIXTURE.exists(), f"Missing fixture: {ERR_FIXTURE}"
    return ERR_FIXTURE.read_text()


class TestParseErrFile:
    def test_fatal_count(self, err_text):
        # Validates: parser extracts exactly 1 fatal error from sample .err file
        result = parse_err_file(err_text)
        assert len(result["fatal"]) == 1

    def test_severe_count(self, err_text):
        # Validates: parser extracts exactly 2 severe errors from sample .err file
        result = parse_err_file(err_text)
        assert len(result["severe"]) == 2

    def test_warning_count(self, err_text):
        # Validates: parser counts all 25 warnings including those beyond max_warnings cap
        result = parse_err_file(err_text)
        assert result["warning_count"] == 25

    def test_continuation_lines_merged(self, err_text):
        # Validates: multi-line severe messages (DX coil) merge continuation into single entry
        result = parse_err_file(err_text)
        coil_severe = [s for s in result["severe"] if "GetDXCoils" in s]
        assert len(coil_severe) == 1
        assert "referenced from" in coil_severe[0]

    def test_warning_continuation_merged(self, err_text):
        # Validates: multi-line warning messages (weather location) merge continuation
        result = parse_err_file(err_text)
        weather_warn = [w for w in result["warnings"] if "Weather file" in w]
        assert len(weather_warn) == 1
        assert "Location object" in weather_warn[0]

    def test_real_fatal_prefix_two_spaces(self):
        # Regression: E+ pads severity labels, so real files write "**  Fatal  **"
        # (two spaces); the parser only matched the single-space form and real
        # fatal lines were silently dropped from the fatal list
        text = (
            "   **  Fatal  ** Errors occurred on processing input file. "
            "Preceding condition(s) cause termination.\n"
        )
        result = parse_err_file(text)
        assert result["fatal"] == [
            "Errors occurred on processing input file. "
            "Preceding condition(s) cause termination.",
        ]
        assert result["summary"] == "1 Fatal"

    def test_orphaned_spm_hint(self):
        # Validates: #83 signature (SPM lost control zone) maps to an actionable
        # hint naming validate_model, and the empty-loop signature maps to its own
        text = (
            "   ** Severe  ** <root>[SetpointManager:SingleZone:Reheat]"
            "[Setpoint Manager Single Zone Reheat 1] - Missing required "
            "property 'control_zone_name'.\n"
            '   ** Severe  ** An outlet node in AirLoopHVAC="AIR LOOP HVAC 1" '
            "is not connected to any zone\n"
        )
        result = parse_err_file(text)
        assert len(result["hints"]) == 2
        assert "lost its control zone" in result["hints"][0]
        assert "validate_model" in result["hints"][0]
        assert "serves no thermal zones" in result["hints"][1]

    def test_no_hints_for_unrelated_errors(self, err_text):
        # Validates: hint list stays empty when no known signature matches,
        # so agents are not misdirected on unrelated failures
        result = parse_err_file(err_text)
        assert result["hints"] == []

    def test_warnings_capped(self, err_text):
        # Validates: max_warnings caps returned list but warning_count reflects true total
        result = parse_err_file(err_text, max_warnings=5)
        assert len(result["warnings"]) == 5
        assert result["warning_count"] == 25

    def test_summary_format(self, err_text):
        # Validates: summary string includes human-readable counts for fatal/severe/warnings
        result = parse_err_file(err_text)
        assert "1 Fatal" in result["summary"]
        assert "2 Severe" in result["summary"]
        assert "25 Warnings" in result["summary"]

    def test_empty_input(self):
        # Validates: empty string input produces zeroed result with "No errors" summary
        result = parse_err_file("")
        assert result["fatal"] == []
        assert result["severe"] == []
        assert result["warnings"] == []
        assert result["warning_count"] == 0
        assert result["summary"] == "No errors"

    def test_clean_run(self):
        # Validates: successful EnergyPlus run with 0 errors produces empty lists
        clean = (
            "Program Version,EnergyPlus, Version 24.2.0\n"
            "   ************* EnergyPlus Completed Successfully-- 0 Warning; 0 Severe Errors\n"
        )
        result = parse_err_file(clean)
        assert result["fatal"] == []
        assert result["severe"] == []
        assert result["warning_count"] == 0
