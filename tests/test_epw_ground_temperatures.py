"""Unit tests for the EPW GROUND TEMPERATURES header parser.

No openstudio, no Docker, no MCP client — the parser is pure by design (CLAUDE.md rule 4),
so the format handling that carries all the risk gets covered without a container. Same
tier as tests/test_gbxml_zone_checks.py.

The three real-EPW cases read tests/assets directly; they are the ground truth for the
format and would catch a parser that only works on synthetic input.
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from mcp_server.skills.weather.epw_ground_temperatures import (
    EPW_HEADER_MAX_BYTES,
    MAX_DEPTH_SETS,
    EpwGroundTemperatureError,
    find_ground_temperature_line,
    nearest_depth_set,
    parse_ground_temperature_header,
    read_ground_temperature_sets,
)

pytestmark = pytest.mark.unit

ASSETS = Path(__file__).parent / "assets"
BOSTON = ASSETS / "USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"
AUSTIN = ASSETS / "USA_TX_Austin-Camp.Mabry.ANGB.722544_TMYx.2009-2023.epw"
GOLDEN = ASSETS / "USA_CO_Golden-NREL.724666_TMY3.epw"

_TWELVE = "1,2,3,4,5,6,7,8,9,10,11,12"


def _line(*sets: str, declared: int | None = None) -> str:
    """A GROUND TEMPERATURES record from pre-built set chunks."""
    n = len(sets) if declared is None else declared
    return f"GROUND TEMPERATURES,{n}," + ",".join(sets)


def _set(depth: str = "0.5", soil: str = ",,,,", months: str = _TWELVE) -> str:
    return f"{depth}{soil}{months}"


def _writable_dir() -> Path:
    """A directory the path allowlist accepts.

    pytest's tmp_path is /tmp, which is_path_allowed rejects (see tests/test_gbxml_deltas.py).
    The parser itself does not gate paths, but keeping every temp file under the run root
    means these fixtures stay usable if a gated caller is ever added here.
    """
    from mcp_server.config import user_run_root

    d = user_run_root() / "pytest_epw_ground_temps" / uuid4().hex[:10]
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- real fixtures


def test_parses_boston_fixture_header_exactly():
    # Validates: the real Boston TMY3 record — three depths, exact endpoint values, and soil
    # properties absent rather than zero
    sets, warnings = read_ground_temperature_sets(BOSTON)

    assert [s.depth_m for s in sets] == [0.5, 2.0, 4.0], sets
    assert sets[0].monthly_c[0] == -0.29
    assert sets[0].monthly_c[11] == 3.79
    assert sets[2].monthly_c[0] == 6.88
    assert sets[2].monthly_c[11] == 9.84
    assert len(sets[0].monthly_c) == 12
    assert sets[0].conductivity_w_mk is None
    assert sets[0].density_kg_m3 is None
    assert sets[0].specific_heat_j_kgk is None
    assert warnings == []


def test_parses_austin_fixture_header_exactly():
    # Validates: a second real file, so Boston passing is not a coincidence
    sets, warnings = read_ground_temperature_sets(AUSTIN)

    assert [s.depth_m for s in sets] == [0.5, 2.0, 4.0], sets
    assert sets[0].monthly_c[0] == 13.34
    assert sets[2].monthly_c[0] == 18.56
    assert sets[2].monthly_c[7] == 25.27
    assert warnings == []


def test_parses_golden_fixture_header_exactly():
    # Validates: the third bundled EPW, which ships without .stat/.ddy companions
    sets, warnings = read_ground_temperature_sets(GOLDEN)

    assert [s.depth_m for s in sets] == [0.5, 2.0, 4.0], sets
    assert sets[0].monthly_c[0] == -0.60
    assert sets[2].monthly_c[0] == 4.84
    assert warnings == []


def test_leading_dot_depth_parses_as_half_a_metre():
    # Regression: every bundled EPW writes the shallow depth as `.5`, not `0.5`
    sets, _ = parse_ground_temperature_header(_line(_set(depth=".5")))

    assert sets[0].depth_m == 0.5


# --------------------------------------------------------------------------- soil properties


def test_blank_soil_properties_are_none_not_zero():
    # Regression: 0.0 conductivity is a physically meaningful (and wrong) value; blank must
    # stay absent so a Kiva caller can tell "not stated" from "zero"
    sets, _ = parse_ground_temperature_header(_line(_set(soil=",,,,")))

    assert sets[0].conductivity_w_mk is None
    assert sets[0].density_kg_m3 is None
    assert sets[0].specific_heat_j_kgk is None


def test_populated_soil_properties_are_parsed():
    # Validates: the Kiva path — no bundled EPW populates these, so this case is synthetic only
    sets, _ = parse_ground_temperature_header(_line(_set(soil=",1.95,1842,419,")))

    assert sets[0].conductivity_w_mk == 1.95
    assert sets[0].density_kg_m3 == 1842.0
    assert sets[0].specific_heat_j_kgk == 419.0


def test_non_numeric_soil_property_is_rejected():
    # Validates: a garbage soil field is an error, not silently dropped to None
    with pytest.raises(EpwGroundTemperatureError, match="soil conductivity"):
        parse_ground_temperature_header(_line(_set(soil=",abc,,,")))


# --------------------------------------------------------------------------- malformed input


def test_record_with_no_depth_set_count_is_rejected():
    # Validates: a record cut off right after the keyword is a named error, not an IndexError on the count field
    with pytest.raises(EpwGroundTemperatureError, match="no depth-set count"):
        parse_ground_temperature_header("GROUND TEMPERATURES,")


def test_zero_declared_sets_is_rejected():
    # Validates: distinct message from "record missing" — the line is present but empty
    with pytest.raises(EpwGroundTemperatureError, match="declares 0 depth sets"):
        parse_ground_temperature_header("GROUND TEMPERATURES,0")


def test_negative_declared_sets_is_rejected():
    # Validates: a negative count is rejected up front instead of driving an empty loop that yields zero sets
    with pytest.raises(EpwGroundTemperatureError, match="declares -1 depth sets"):
        parse_ground_temperature_header("GROUND TEMPERATURES,-1")


def test_absurd_declared_set_count_is_rejected_before_allocating():
    # Regression: a crafted header must not drive an allocation loop
    with pytest.raises(EpwGroundTemperatureError, match="above the 24 this reader accepts"):
        parse_ground_temperature_header("GROUND TEMPERATURES,1000000000")


def test_non_numeric_declared_count_is_rejected():
    # Validates: a non-integer count is reported by name, not as a raw ValueError escaping int()
    with pytest.raises(EpwGroundTemperatureError, match="not an integer"):
        parse_ground_temperature_header("GROUND TEMPERATURES,three,.5,,,," + _TWELVE)


def test_eleven_monthly_values_is_rejected():
    # Validates: a truncated set fails the arity check rather than being zero-padded
    short = "0.5,,,,1,2,3,4,5,6,7,8,9,10,11"
    with pytest.raises(EpwGroundTemperatureError, match="not a multiple of 16"):
        parse_ground_temperature_header(_line(short))


def test_non_numeric_temperature_is_rejected_naming_the_month():
    # Validates: a non-numeric monthly value is rejected and the error names the offending month
    bad = "0.5,,,,1,2,3,NA,5,6,7,8,9,10,11,12"
    with pytest.raises(EpwGroundTemperatureError, match="month 4 temperature"):
        parse_ground_temperature_header(_line(bad))


def test_blank_temperature_is_rejected():
    # Validates: a blank temperature is an error even though a blank soil field is not
    bad = "0.5,,,,1,2,,4,5,6,7,8,9,10,11,12"
    with pytest.raises(EpwGroundTemperatureError, match="month 3 temperature is blank"):
        parse_ground_temperature_header(_line(bad))


def test_blank_depth_is_rejected():
    # Validates: a blank depth field gets a depth-specific message, not a ValueError from float('')
    bad = ",,,,1,2,3,4,5,6,7,8,9,10,11,12"
    with pytest.raises(EpwGroundTemperatureError, match="depth is blank"):
        parse_ground_temperature_header(_line(bad))


def test_implausible_depth_is_rejected():
    # Validates: a 500 m depth trips the plausibility bound instead of being accepted as a valid set
    with pytest.raises(EpwGroundTemperatureError, match="implausible depth"):
        parse_ground_temperature_header(_line(_set(depth="500")))


def test_zero_depth_is_rejected():
    # Validates: depth 0 is rejected — the lower plausibility bound is exclusive, a zero-depth set is meaningless
    with pytest.raises(EpwGroundTemperatureError, match="implausible depth"):
        parse_ground_temperature_header(_line(_set(depth="0")))


def test_implausible_temperature_is_rejected():
    # Validates: a 900 C value trips the temperature bound and the error names both the value and the month
    bad = "0.5,,,,1,2,900,4,5,6,7,8,9,10,11,12"
    with pytest.raises(EpwGroundTemperatureError, match=r"implausible temperature 900\.0 C in month 3"):
        parse_ground_temperature_header(_line(bad))


def test_line_that_is_not_a_ground_temperature_record_is_rejected():
    # Validates: a LOCATION line is refused outright rather than having its fields parsed as depth sets
    with pytest.raises(EpwGroundTemperatureError, match="Not a GROUND TEMPERATURES record"):
        parse_ground_temperature_header("LOCATION,Boston,MA,USA")


# --------------------------------------------------------------------------- tolerated quirks


def test_trailing_comma_is_tolerated():
    # Validates: real EPWs end the record with a trailing comma
    sets, warnings = parse_ground_temperature_header(_line(_set()) + ",")

    assert len(sets) == 1
    assert warnings == []


def test_declared_count_mismatch_warns_and_uses_the_actual_sets():
    # Validates: a miscounted header is recoverable — use what is there and say so
    sets, warnings = parse_ground_temperature_header(
        _line(_set(depth="0.5"), _set(depth="4"), declared=3),
    )

    assert [s.depth_m for s in sets] == [0.5, 4.0]
    assert any("declares 3" in w and "carries 2" in w for w in warnings), warnings


def test_oversized_record_is_rejected_even_when_the_declared_count_is_small():
    # Regression: the depth-set cap was checked only against the declared count, and a declared
    # count that disagreed with the payload was merely warned about — so a record declaring 1
    # set while carrying 25 was parsed in full
    one_set = ",".join(["0.5", "", "", ""] + ["10"] * 12)
    line = "GROUND TEMPERATURES,1," + ",".join([one_set] * (MAX_DEPTH_SETS + 1))

    with pytest.raises(EpwGroundTemperatureError, match=f"carries {MAX_DEPTH_SETS + 1} depth sets"):
        parse_ground_temperature_header(line)


def test_duplicate_depth_keeps_the_first_and_warns():
    # Validates: a repeated depth collapses to the first set and warns, so nearest_depth_set never sees an ambiguous tie
    sets, warnings = parse_ground_temperature_header(
        _line(_set(depth="0.5"), _set(depth="0.5")),
    )

    assert [s.depth_m for s in sets] == [0.5]
    assert any("repeats depth" in w for w in warnings), warnings


def test_fahrenheit_like_values_warn_but_still_parse():
    # Validates: an honest partial defence — the bounds catch corruption, not a unit error,
    # so a suspicious spread is surfaced rather than rejected
    warm = "0.5,,,,40,41,42,43,44,45,50,55,52,48,44,41"
    sets, warnings = parse_ground_temperature_header(_line(warm))

    assert len(sets) == 1
    assert any("Celsius" in w for w in warnings), warnings


# --------------------------------------------------------------------------- line location


def test_record_is_found_when_it_is_not_on_line_four():
    # Regression: the record is line 4 in every bundled EPW, but the scan must not hardcode it
    header = "\n".join(
        ["LOCATION,x", "DESIGN CONDITIONS,0", "TYPICAL/EXTREME PERIODS,0", "HOLIDAYS,No",
         _line(_set())],
    )

    assert find_ground_temperature_line(header) is not None


def test_record_past_the_header_scan_window_is_not_found():
    # Validates: a record on line 9 is past the EPW header and is not treated as one
    header = "\n".join(["FILLER"] * 8 + [_line(_set())])

    assert find_ground_temperature_line(header) is None


# --------------------------------------------------------------------------- bounded reading


def test_reads_only_the_header_of_an_oversized_file():
    # Validates: the 8760 data rows are never slurped — the file here is far larger than the
    # bounded read, and the record still parses
    path = _writable_dir() / "big.epw"
    header = "\n".join(["LOCATION,x", "DESIGN CONDITIONS,0", "TYPICAL,0", _line(_set())])
    filler = "\n".join("1,1,1,0,0,fill" for _ in range(200_000))
    path.write_text(f"{header}\n{filler}\n", encoding="utf-8")

    assert path.stat().st_size > EPW_HEADER_MAX_BYTES
    sets, _ = read_ground_temperature_sets(path)
    assert len(sets) == 1


def test_single_enormous_line_is_rejected_rather_than_parsed():
    # Regression: the degenerate input the bounded read exists to survive (cf. the
    # billion-laughs case in tests/test_gbxml_deltas.py)
    path = _writable_dir() / "oneline.epw"
    path.write_text("x" * (EPW_HEADER_MAX_BYTES * 2), encoding="utf-8")

    with pytest.raises(EpwGroundTemperatureError, match="No line break"):
        read_ground_temperature_sets(path)


def test_file_without_a_ground_temperature_record_is_rejected():
    # Validates: an EPW header lacking the record is a named error, not an empty set list handed to the caller
    path = _writable_dir() / "nogt.epw"
    path.write_text("LOCATION,x\nDESIGN CONDITIONS,0\nDATA PERIODS,1\n", encoding="utf-8")

    with pytest.raises(EpwGroundTemperatureError, match="no GROUND TEMPERATURES record"):
        read_ground_temperature_sets(path)


def test_missing_file_is_rejected_as_unreadable():
    # Validates: a missing path is wrapped in EpwGroundTemperatureError, not a raw FileNotFoundError through MCP
    with pytest.raises(EpwGroundTemperatureError, match="Cannot read EPW header"):
        read_ground_temperature_sets(_writable_dir() / "absent.epw")


def test_directory_is_rejected_as_not_a_regular_file():
    # Validates: a directory path is wrapped in EpwGroundTemperatureError, not a raw IsADirectoryError
    with pytest.raises(EpwGroundTemperatureError, match="Cannot read EPW header"):
        read_ground_temperature_sets(_writable_dir())


def test_non_utf8_bytes_in_the_header_are_tolerated():
    # Validates: the repo's own .stat files carry latin-1 degree signs, so this is not
    # hypothetical for weather sidecars
    path = _writable_dir() / "latin1.epw"
    path.write_bytes(b"COMMENTS 1,45\xb0C soil\n" + _line(_set()).encode() + b"\n")

    sets, _ = read_ground_temperature_sets(path)
    assert len(sets) == 1


# --------------------------------------------------------------------------- depth selection


def test_nearest_depth_prefers_an_exact_match():
    # Validates: the 0.5/4.0 split the .stat guidance calls for, on a real file
    sets, _ = read_ground_temperature_sets(BOSTON)

    shallow, shallow_delta = nearest_depth_set(sets, 0.5)
    deep, deep_delta = nearest_depth_set(sets, 4.0)

    assert (shallow.depth_m, shallow_delta) == (0.5, 0.0)
    assert (deep.depth_m, deep_delta) == (4.0, 0.0)
    assert deep.monthly_c[0] == 6.88
    assert shallow.monthly_c[0] == -0.29


def test_nearest_depth_on_nonstandard_depths():
    # Regression: 0.5/2/4 is the common case, not a guarantee — selection must not index
    sets, _ = parse_ground_temperature_header(_line(_set(depth="1"), _set(depth="3")))

    assert nearest_depth_set(sets, 0.5) == (sets[0], 0.5)
    assert nearest_depth_set(sets, 4.0) == (sets[1], 1.0)


def test_nearest_depth_with_a_single_set_serves_every_target():
    # Validates: a one-set file serves both the shallow and deep targets with correct deltas instead of failing
    sets, _ = parse_ground_temperature_header(_line(_set(depth="2")))

    assert nearest_depth_set(sets, 0.5) == (sets[0], 1.5)
    assert nearest_depth_set(sets, 4.0) == (sets[0], 2.0)


def test_nearest_depth_tie_breaks_to_the_shallower_set():
    # Validates: deterministic choice, so two files with the same depths never disagree
    sets, _ = parse_ground_temperature_header(_line(_set(depth="3"), _set(depth="5")))

    chosen, delta = nearest_depth_set(sets, 4.0)
    assert (chosen.depth_m, delta) == (3.0, 1.0)


def test_depth_order_in_the_file_does_not_change_the_selection():
    # Regression: guards against a reintroduced sets[0] / sets[2] index lookup
    forward, _ = parse_ground_temperature_header(
        _line(_set(depth="0.5"), _set(depth="2"), _set(depth="4")),
    )
    reversed_, _ = parse_ground_temperature_header(
        _line(_set(depth="4"), _set(depth="2"), _set(depth="0.5")),
    )

    assert nearest_depth_set(forward, 4.0)[0].depth_m == 4.0
    assert nearest_depth_set(reversed_, 4.0)[0].depth_m == 4.0
    assert nearest_depth_set(reversed_, 0.5)[0].depth_m == 0.5


def test_nearest_depth_on_an_empty_list_is_rejected():
    # Validates: an empty set list raises a named error rather than min() failing on an empty sequence
    with pytest.raises(EpwGroundTemperatureError, match="No ground temperature sets"):
        nearest_depth_set([], 0.5)
