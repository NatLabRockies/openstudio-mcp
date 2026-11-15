"""Valid ranges for measure arguments: measure.xml first, then a bundled bounds file.

Almost no measure declares <min_value>/<max_value> (1 of 79 common measures), so
openstudio-mcp ships small per-measure files under measure_bounds/, keyed by the
measure.xml <name>. These limits are the server-side trust boundary for sweeps:
both the sweep panel and add_measure_to_osa_json check against them.
"""
from __future__ import annotations

import json
import re
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


def out_of_bounds(name: str, value: Any, limits: dict[str, dict[str, Any]]) -> str | None:
    """Error text when a numeric value falls outside the argument's limits, else None."""
    spec = limits.get(name)
    if spec is None:
        return None
    num = _number(value)
    if num is None:
        return f"{name}: {value!r} is not a number"
    if not spec["min"] <= num <= spec["max"]:
        units = f" {spec['units']}" if spec["units"] else ""
        return f"{name}: {value}{units} outside [{spec['min']}, {spec['max']}]"
    return None
