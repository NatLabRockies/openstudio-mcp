"""Valid ranges for measure arguments: measure.xml first, then a bundled bounds file.

Almost no measure declares <min_value>/<max_value> (1 of 79 common measures), so
openstudio-mcp ships small per-measure files under measure_bounds/, keyed by the
measure.xml <name>. These limits are the sweep panel's server-side check; the
existing analysis tools don't use them.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
from typing import Any

BOUNDS_DIR = Path(__file__).parent / "measure_bounds"
_NAME_RE = re.compile(r"^[a-z0-9_]{1,128}$")


@lru_cache(maxsize=64)
def _bundled(measure_name: str) -> dict[str, dict[str, Any]]:
    if not _NAME_RE.match(measure_name or ""):
        return {}
    path = BOUNDS_DIR / f"{measure_name}.json"
    return json.loads(path.read_text()) if path.is_file() else {}


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def argument_limits(measure_name: str, xml_limits: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Merge measure.xml limits with the bundled file; measure.xml wins where it declares a value.

    Returns {argument_name: {"units", "min", "max", "label"?}} for arguments that have both bounds.
    """
    merged: dict[str, dict[str, Any]] = {}
    bundled = _bundled(measure_name)
    for name in set(xml_limits) | set(bundled):
        xml, side = xml_limits.get(name, {}), bundled.get(name, {})
        lo = _number(xml.get("min")) if xml.get("min") is not None else _number(side.get("min"))
        hi = _number(xml.get("max")) if xml.get("max") is not None else _number(side.get("max"))
        if lo is None or hi is None:
            continue
        entry = {"units": xml.get("units") or side.get("units", ""), "min": lo, "max": hi}
        if side.get("label"):
            entry["label"] = side["label"]
        merged[name] = entry
    return merged


def measure_limits(measure_path: Path) -> dict[str, dict[str, Any]]:
    """Limits for a measure directory that _read_measure_metadata has already checked."""
    root = ET.parse(measure_path / "measure.xml").getroot()  # noqa: S314 - same file _read_measure_metadata parses
    xml_limits = {
        (arg.findtext("name") or "").strip(): {
            k: (arg.findtext(tag) or "").strip() or None
            for k, tag in (("units", "units"), ("min", "min_value"), ("max", "max_value"))
        }
        for arg in root.findall("./arguments/argument")
    }
    return argument_limits((root.findtext("name") or measure_path.name).strip(), xml_limits)

