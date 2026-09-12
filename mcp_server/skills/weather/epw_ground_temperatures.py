"""Parse the GROUND TEMPERATURES record out of an EPW file header.

Nothing else in this server reads an EPW header. `_estimate_climate_zone_from_epw`
(weather/operations.py) skips the first 8 lines and reads data rows; the only other
weather-sidecar parser is `parse_climate_zone_from_stat` in gbxml_import. So this is the
first header reader, and it is deliberately kept free of `import openstudio` — the format
handling is where the bugs live, and rule 4 says unit tests never import openstudio. Same
trade `gbxml_import/zone_checks.py` makes, for the same reason.

Record shape, verified against all three EPWs in tests/assets and a staged runs/**/in.epw:

    GROUND TEMPERATURES,<n_sets>,[<depth_m>,<cond>,<dens>,<spec_heat>,<12 monthly C>] * n_sets

e.g. Boston TMY3 (line 4, soil properties blank, depths written as `.5`, `2`, `4`):

    GROUND TEMPERATURES,3,.5,,,,-0.29,-1.36,...,3.79,2,,,,3.63,...,4,,,,6.88,...

Two things a reader is tempted to assume and must not:

- **The depths are not guaranteed to be 0.5/2/4.** Callers ask for a target depth and get
  the nearest available set plus the delta, never `sets[0]` / `sets[2]`.
- **The record is not guaranteed to be line 4.** It is in every file we have, but the scan
  is by keyword over the header, which costs nothing.

The soil property fields are blank in every bundled EPW — that is the normal case, not a
defect, and they parse to None rather than 0.0. A Kiva foundation model consumes them when
a file does populate them, which is why they are carried at all.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mcp_server.util import read_head_bounded

GROUND_TEMPERATURE_KEYWORD = "GROUND TEMPERATURES"

# The 8 EPW header lines before the data rows. DESIGN CONDITIONS alone runs to ~1.5 KB in the
# bundled files, so 128 KB is ~2 orders of margin and never touches the 8760 data rows.
EPW_HEADER_MAX_BYTES = 131_072
MAX_HEADER_LINES = 8

# depth, conductivity, density, specific heat, then 12 monthly temperatures.
FIELDS_PER_SET = 16
MONTHS_PER_SET = 12

# A crafted header could declare n_sets=10**9; the cap is checked before any allocation.
MAX_DEPTH_SETS = 24

# Gross-corruption guards, not climate science. A 900 degree ground temperature is a broken
# file. These will NOT catch a Fahrenheit file — see the spread warning in _validate_set.
MIN_PLAUSIBLE_C = -60.0
MAX_PLAUSIBLE_C = 60.0
MAX_PLAUSIBLE_DEPTH_M = 100.0

# Above this annual spread or mean, the file is likely not in Celsius. Warned, never rejected:
# there is no bulletproof C/F detector and a real climate can be surprising.
SUSPICIOUS_SPREAD_K = 40.0
SUSPICIOUS_MEAN_C = 40.0


class EpwGroundTemperatureError(ValueError):
    """The EPW header carries no usable GROUND TEMPERATURES record.

    Raised rather than returned because every caller in this package is an operation that
    already wraps its body in try/except and turns exceptions into {"ok": False, ...}.
    """


@dataclass(frozen=True)
class GroundTemperatureSet:
    """One depth's worth of the EPW record: 12 monthly temperatures and the soil it assumed."""

    depth_m: float
    monthly_c: tuple[float, ...]
    conductivity_w_mk: float | None
    density_kg_m3: float | None
    specific_heat_j_kgk: float | None


def _parse_float(token: str, what: str, set_index: int) -> float:
    text = token.strip()
    if not text:
        raise EpwGroundTemperatureError(
            f"GROUND TEMPERATURES set {set_index}: {what} is blank",
        )
    try:
        return float(text)
    except ValueError as e:
        raise EpwGroundTemperatureError(
            f"GROUND TEMPERATURES set {set_index}: {what} is not a number ({token.strip()!r})",
        ) from e


def _parse_optional_float(token: str, what: str, set_index: int) -> float | None:
    """Soil properties are blank in every bundled EPW. Blank is None, never 0.0."""
    text = token.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError as e:
        raise EpwGroundTemperatureError(
            f"GROUND TEMPERATURES set {set_index}: {what} is not a number ({token.strip()!r})",
        ) from e


def _validate_set(gt_set: GroundTemperatureSet, set_index: int, warnings: list[str]) -> None:
    if not 0.0 < gt_set.depth_m <= MAX_PLAUSIBLE_DEPTH_M:
        raise EpwGroundTemperatureError(
            f"GROUND TEMPERATURES set {set_index}: implausible depth {gt_set.depth_m} m",
        )
    for month_index, value in enumerate(gt_set.monthly_c, start=1):
        if not MIN_PLAUSIBLE_C <= value <= MAX_PLAUSIBLE_C:
            raise EpwGroundTemperatureError(
                f"GROUND TEMPERATURES set {set_index}: implausible temperature "
                f"{value} C in month {month_index}",
            )
    spread = max(gt_set.monthly_c) - min(gt_set.monthly_c)
    mean = sum(gt_set.monthly_c) / MONTHS_PER_SET
    if spread > SUSPICIOUS_SPREAD_K or mean > SUSPICIOUS_MEAN_C:
        warnings.append(
            f"Ground temperatures at {gt_set.depth_m} m have an annual spread of "
            f"{spread:.1f} K and a mean of {mean:.1f} — unusually large for soil. "
            f"Check the EPW is in Celsius.",
        )


def parse_ground_temperature_header(line: str) -> tuple[list[GroundTemperatureSet], list[str]]:
    """Parse one GROUND TEMPERATURES header line into its depth sets.

    Returns (sets, warnings). Raises EpwGroundTemperatureError on anything that cannot be
    parsed unambiguously — a missing month is never zero-filled and a blank temperature is
    never treated as 0.0.
    """
    warnings: list[str] = []
    tokens = line.split(",")
    if not tokens or tokens[0].strip().upper() != GROUND_TEMPERATURE_KEYWORD:
        raise EpwGroundTemperatureError(
            f"Not a GROUND TEMPERATURES record: {line[:60]!r}",
        )

    # Real files carry a trailing comma; strip only trailing blanks so an interior blank
    # (a genuinely missing field) still fails the arity check below.
    fields = tokens[1:]
    while fields and not fields[-1].strip():
        fields.pop()

    if not fields:
        raise EpwGroundTemperatureError(
            "GROUND TEMPERATURES record declares no depth-set count",
        )

    declared_text = fields[0].strip()
    try:
        declared = int(declared_text)
    except ValueError as e:
        raise EpwGroundTemperatureError(
            f"GROUND TEMPERATURES depth-set count is not an integer ({declared_text!r})",
        ) from e
    if declared <= 0:
        raise EpwGroundTemperatureError(
            f"GROUND TEMPERATURES declares {declared} depth sets",
        )
    if declared > MAX_DEPTH_SETS:
        raise EpwGroundTemperatureError(
            f"GROUND TEMPERATURES declares {declared} depth sets, above the "
            f"{MAX_DEPTH_SETS} this reader accepts",
        )

    payload = fields[1:]
    if len(payload) % FIELDS_PER_SET != 0:
        raise EpwGroundTemperatureError(
            f"GROUND TEMPERATURES carries {len(payload)} fields, not a multiple of "
            f"{FIELDS_PER_SET} — a depth set is truncated",
        )
    actual = len(payload) // FIELDS_PER_SET
    if actual == 0:
        raise EpwGroundTemperatureError(
            "GROUND TEMPERATURES record carries no depth-set data",
        )
    if actual > MAX_DEPTH_SETS:
        # The declared count is advisory (a mismatch is only warned about below), so the cap has
        # to bind on what the record actually carries or it binds on nothing.
        raise EpwGroundTemperatureError(
            f"GROUND TEMPERATURES carries {actual} depth sets, above the {MAX_DEPTH_SETS} this "
            f"reader accepts",
        )
    if actual != declared:
        warnings.append(
            f"EPW header declares {declared} ground temperature sets but carries {actual}; "
            f"using the {actual} present.",
        )

    sets: list[GroundTemperatureSet] = []
    for index in range(actual):
        chunk = payload[index * FIELDS_PER_SET:(index + 1) * FIELDS_PER_SET]
        monthly = tuple(
            _parse_float(chunk[4 + month], f"month {month + 1} temperature", index)
            for month in range(MONTHS_PER_SET)
        )
        gt_set = GroundTemperatureSet(
            depth_m=_parse_float(chunk[0], "depth", index),
            monthly_c=monthly,
            conductivity_w_mk=_parse_optional_float(chunk[1], "soil conductivity", index),
            density_kg_m3=_parse_optional_float(chunk[2], "soil density", index),
            specific_heat_j_kgk=_parse_optional_float(chunk[3], "soil specific heat", index),
        )
        _validate_set(gt_set, index, warnings)
        sets.append(gt_set)

    seen: dict[float, int] = {}
    deduped: list[GroundTemperatureSet] = []
    for index, gt_set in enumerate(sets):
        if gt_set.depth_m in seen:
            warnings.append(
                f"EPW header repeats depth {gt_set.depth_m} m (sets {seen[gt_set.depth_m]} "
                f"and {index}); keeping the first.",
            )
            continue
        seen[gt_set.depth_m] = index
        deduped.append(gt_set)

    return deduped, warnings


def find_ground_temperature_line(header_text: str) -> str | None:
    """The GROUND TEMPERATURES line from an EPW header blob, or None.

    Scans the first MAX_HEADER_LINES by keyword rather than indexing line 4 — it is line 4
    in every EPW we have, but that costs nothing to not rely on.
    """
    for line in header_text.splitlines()[:MAX_HEADER_LINES]:
        if line.strip().upper().startswith(GROUND_TEMPERATURE_KEYWORD):
            return line
    return None


def read_ground_temperature_sets(epw_path: Path) -> tuple[list[GroundTemperatureSet], list[str]]:
    """Read and parse the GROUND TEMPERATURES record from an EPW file.

    Uses util.read_head_bounded, which refuses symlinks and non-regular files and never
    slurps the 8760 data rows. Raises EpwGroundTemperatureError; the caller turns that into
    {"ok": False, ...}.
    """
    try:
        raw = read_head_bounded(epw_path, EPW_HEADER_MAX_BYTES)
    except ValueError as e:
        raise EpwGroundTemperatureError(f"Cannot read EPW header: {e}") from e

    text = raw.decode("utf-8", errors="replace")
    if "\n" not in text:
        # A header this long with no line break is not an EPW — it is the degenerate input
        # the bounded read exists to survive (cf. the billion-laughs case in gbxml deltas).
        raise EpwGroundTemperatureError(
            f"No line break in the first {EPW_HEADER_MAX_BYTES} bytes — not an EPW header",
        )

    lines = text.splitlines()
    if len(raw) == EPW_HEADER_MAX_BYTES and not text.endswith(("\n", "\r")):
        # The read cut mid-line; that last fragment is not a record.
        lines.pop()

    line = find_ground_temperature_line("\n".join(lines))
    if line is None:
        raise EpwGroundTemperatureError(
            f"EPW header has no {GROUND_TEMPERATURE_KEYWORD} record: {epw_path.name}",
        )
    return parse_ground_temperature_header(line)


def nearest_depth_set(
    sets: list[GroundTemperatureSet],
    target_m: float,
) -> tuple[GroundTemperatureSet, float]:
    """The set whose depth is nearest `target_m`, with the absolute delta in metres.

    Never an index lookup: EPW depths are commonly 0.5/2/4 but nothing guarantees it, and a
    file with a single 2 m set must still answer a 4 m request (with a delta the caller can
    warn about).

    Ties break to the shallower depth, so the choice is deterministic across files.
    """
    if not sets:
        raise EpwGroundTemperatureError("No ground temperature sets to choose from")
    best = min(sets, key=lambda s: (abs(s.depth_m - target_m), s.depth_m))
    return best, abs(best.depth_m - target_m)
