"""Unit tests for mcp_server.skills.gbxml_import.climate_zone.

Pure Python — no `openstudio` import, no Docker. Exercises the WMO-hash /
Haversine lookup and .stat-regex parsing in isolation from the model.
"""
from __future__ import annotations

from mcp_server.skills.gbxml_import.climate_zone import (
    STATION_COORDS,
    WMO_TO_CZ,
    _haversine_a,
    _nearest_station_cz,
    _valid_ashrae_value,
    parse_climate_zone_from_stat,
)


# Validates: the bundled reference table actually loads and is non-trivial —
# would fail if DATA_PATH pointed at the wrong file or the CSV format changed.
def test_reference_table_loaded():
    assert len(WMO_TO_CZ) == 2006
    assert len(STATION_COORDS) == 2559


# Validates: WMO hash tier resolves known stations to their exact CSV zone —
# both a padded 6-digit code and one requiring no padding.
def test_wmo_hash_exact_match():
    assert WMO_TO_CZ["722544"] == "2A"  # Austin-Camp Mabry
    assert WMO_TO_CZ["725090"] == "5A"  # Boston-Logan


# Validates: an unknown WMO number correctly misses the hash tier (None, not
# a KeyError or a wrong fallback value) — callers must fall through to the
# Haversine tier on a miss.
def test_wmo_hash_miss_on_unknown_station():
    assert "999999" not in WMO_TO_CZ


# Validates: Haversine nearest-station selection picks the closer of two
# candidates, not just the first or last in the table — proves the distance
# comparison itself is doing the work, not accidental list ordering.
def test_haversine_picks_nearer_station():
    boston = (42.35, -71.07, "5A")
    austin = (30.32, -97.77, "2A")
    # A point a few km from Boston, much closer to it than to Austin.
    near_boston_lat, near_boston_lon = 42.36, -71.05
    a_boston = _haversine_a(near_boston_lat, near_boston_lon, boston[0], boston[1])
    a_austin = _haversine_a(near_boston_lat, near_boston_lon, austin[0], austin[1])
    assert a_boston < a_austin


# Validates: _nearest_station_cz scans the real bundled table and returns the
# zone of the closest station for a point near a known WMO 722544 (Austin).
def test_nearest_station_cz_against_real_table():
    assert _nearest_station_cz(30.30, -97.75) == "2A"


# Validates: real ASHRAE codes (all 17 distinct values present in the bundled
# CSV) pass validation; the garbage placeholder the vendored
# ChangeBuildingLocation measure can leave behind does not.
def test_valid_ashrae_value_accepts_real_codes_rejects_garbage():
    for cz in ("1A", "2B", "3C", "4A", "5A", "6B", "7", "8"):
        assert _valid_ashrae_value(cz) is True
    assert _valid_ashrae_value("Lookup From Stat File") is False
    assert _valid_ashrae_value("") is False
    assert _valid_ashrae_value("9A") is False
    assert _valid_ashrae_value("5D") is False


# Validates: the regex matches the older stat-file phrasing (the format the
# vendored measure's own Ruby regex already handles) — a trailing "**", label
# "Climate type".
def test_parse_climate_zone_from_stat_matches_older_format(tmp_path):
    stat = tmp_path / "old_format.stat"
    stat.write_text(
        ' - Climate type "5A" (ASHRAE Standard 196-2006 Climate Zone)**\n',
        encoding="utf-8",
    )
    assert parse_climate_zone_from_stat(stat) == "5A"


# Regression: Climate.OneBuilding.org stat files (e.g. the Austin fixture
# added for this feature) use "Climate Zone" (not "Climate type") with no
# trailing "**" — a real-world format the vendored measure's own regex
# entirely misses, silently leaving its garbage placeholder value on the
# model. This is the actual bug ensure_climate_zone's stat-file re-parse tier
# exists to catch.
def test_parse_climate_zone_from_stat_matches_newer_format(tmp_path):
    stat = tmp_path / "new_format.stat"
    stat.write_text(
        ' - Climate Zone "2A" (ASHRAE Standard 169-2021)\n',
        encoding="utf-8",
    )
    assert parse_climate_zone_from_stat(stat) == "2A"


# Validates: a stat file with no climate-zone line at all returns None rather
# than raising or returning a bogus match.
def test_parse_climate_zone_from_stat_returns_none_when_absent(tmp_path):
    stat = tmp_path / "no_zone.stat"
    stat.write_text("Some unrelated stat file content\n", encoding="utf-8")
    assert parse_climate_zone_from_stat(stat) is None


# Validates: a missing file returns None instead of raising (ensure_climate_zone
# passes stat_path through even when the caller's .stat check already
# guarantees existence at import time, but this function must stay safe
# standalone).
def test_parse_climate_zone_from_stat_returns_none_when_file_missing(tmp_path):
    assert parse_climate_zone_from_stat(tmp_path / "does_not_exist.stat") is None
