"""Guarantee an ASHRAE climate zone on a gbXML-imported model.

The vendored ChangeBuildingLocation measure (run as part of import_gbxml_op)
already tries to set a climate zone by regexing the project's .stat file, but
on a regex miss it doesn't fail — it writes the literal string
"Lookup From Stat File" into the model's ClimateZones object as if it were a
real value. resolve_and_ensure() re-validates whatever the measure left behind
and, if it's missing or garbage, re-resolves it: first by re-parsing the same
.stat file directly (cheap, no new data), then by a two-tier WMO-station
lookup (O(1) hash by WMO number, Haversine nearest-station fallback by
lat/lon) over a bundled reference table. If every tier misses, the zone is
left unresolved rather than guessing — a wrong climate zone silently corrupts
every downstream load calc and 90.1 baseline comparison.
"""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).parent / "data" / "wmo_climate_zones.csv"

_ASHRAE_VALUE_RE = re.compile(r"[0-8][ABC]?")


def _load_reference_table() -> tuple[dict[str, str], list[tuple[float, float, str]]]:
    wmo_to_cz: dict[str, str] = {}
    station_coords: list[tuple[float, float, str]] = []
    with DATA_PATH.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            wmo = (row.get("WMO") or "").strip().rjust(6, "0")
            cz = (row.get("ClimateZone") or "").strip()
            if not wmo or not cz:
                continue
            wmo_to_cz[wmo] = cz
            station_coords.append((float(row["Latitude"]), float(row["Longitude"]), cz))
    return wmo_to_cz, station_coords


# Built once at import time from the bundled reference table (2,570 WMO
# stations); never mutated afterward.
WMO_TO_CZ, STATION_COORDS = _load_reference_table()


def _valid_ashrae_value(value: str) -> bool:
    """True for a real ASHRAE 169 zone code (e.g. "5A", "7"), false for
    anything else — including the "Lookup From Stat File" placeholder the
    vendored measure leaves behind on a .stat regex miss."""
    return bool(_ASHRAE_VALUE_RE.fullmatch(value.strip()))


def parse_climate_zone_from_stat(stat_path: Path) -> str | None:
    """Extract ASHRAE climate zone from a .stat file (e.g. "5A", "2B").

    Matches both the older stat-file phrasing (ends in a trailing "**"):
      - Climate type "5A" (ASHRAE Standard 196-2006 Climate Zone)**
    and the newer Climate.OneBuilding.org phrasing the vendored
    ChangeBuildingLocation measure's own regex misses entirely (no "type"
    label, no trailing "**") — the actual real-world case this function
    exists to catch:
      - Climate Zone "2A" (ASHRAE Standard 169-2021)
    """
    try:
        text = stat_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'Climate (?:type|Zone) "([^"]+)" \(ASHRAE Standards?', text)
        if m:
            return m.group(1)
    except OSError:
        pass
    return None


def _haversine_a(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine intermediate value for relative distance comparison only —
    full arc-sine and Earth radius are skipped since nearest-neighbour
    selection only needs consistent ordering, not real distances."""
    deg2rad = math.pi / 180.0
    d_lat = (lat2 - lat1) * deg2rad
    d_lon = (lon2 - lon1) * deg2rad
    return (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1 * deg2rad) * math.cos(lat2 * deg2rad) * math.sin(d_lon / 2) ** 2
    )


def _nearest_station_cz(lat: float, lon: float) -> str | None:
    best_a = math.inf
    best_cz: str | None = None
    for s_lat, s_lon, cz in STATION_COORDS:
        a = _haversine_a(lat, lon, s_lat, s_lon)
        if a < best_a:
            best_a = a
            best_cz = cz
    return best_cz


def ashrae_169_climate_zone(model: Any) -> str | None:
    """Resolve a bare ASHRAE zone suffix (e.g. "5A") from the model's
    WeatherFile WMO number or site coordinates. Tier 1: O(1) WMO hash lookup.
    Tier 2: Haversine nearest-station fallback by lat/lon. Returns None if
    neither tier resolves (e.g. no WeatherFile, or an empty reference table).
    """
    wf = model.getOptionalWeatherFile()
    if not wf.is_initialized():
        return None
    weather = wf.get()

    wmo_raw = weather.wMONumber().strip()
    wmo = wmo_raw.rjust(6, "0") if wmo_raw else ""
    if wmo and wmo in WMO_TO_CZ:
        return WMO_TO_CZ[wmo]

    if not STATION_COORDS:
        return None
    return _nearest_station_cz(float(weather.latitude()), float(weather.longitude()))


def ensure_climate_zone(model: Any, stat_path: Path | None) -> dict[str, Any]:
    """Guarantee the model has a valid ASHRAE climate zone, resolving one if
    the gbXML measure chain left it missing or invalid. Never fabricates a
    value it can't support with real data — see module docstring.
    """
    czs = model.getClimateZones()
    existing = czs.getClimateZones("ASHRAE")
    existing_value = existing[0].value().strip() if existing else ""

    if existing_value and _valid_ashrae_value(existing_value):
        return {"climate_zone": existing_value, "climate_zone_source": "gbxml_measure", "climate_zone_resolved": True}

    prior_invalid_value = existing_value or None

    if stat_path is not None:
        cz = parse_climate_zone_from_stat(stat_path)
        if cz and _valid_ashrae_value(cz):
            czs.setClimateZone("ASHRAE", cz)
            return {
                "climate_zone": cz,
                "climate_zone_source": "stat_file",
                "climate_zone_resolved": True,
                "climate_zone_prior_invalid_value": prior_invalid_value,
            }

    cz = ashrae_169_climate_zone(model)
    if cz:
        czs.setClimateZone("ASHRAE", cz)
        return {
            "climate_zone": cz,
            "climate_zone_source": "wmo_or_geographic_lookup",
            "climate_zone_resolved": True,
            "climate_zone_prior_invalid_value": prior_invalid_value,
        }

    return {
        "climate_zone": None,
        "climate_zone_source": None,
        "climate_zone_resolved": False,
        "climate_zone_prior_invalid_value": prior_invalid_value,
        "climate_zone_warning": (
            "Could not resolve an ASHRAE climate zone from the .stat file, WMO station table, "
            "or site coordinates. Set one explicitly with change_building_location before relying "
            "on any ASHRAE 90.1 baseline comparison."
        ),
    }
