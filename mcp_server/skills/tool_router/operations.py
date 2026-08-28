"""Keyword-based tool routing — matches task descriptions to tool groups.

No embedding model needed. Simple token overlap scoring against per-group
keyword sets. Returns the best-matching group with its tool descriptions.
"""
from __future__ import annotations

import re

# Keyword sets per group. Tokens from task description are matched against
# these. Higher overlap = better match. Keywords are lowercase.
GROUP_KEYWORDS: dict[str, set[str]] = {
    "core": {
        "building", "model", "load", "save", "open", "create", "office",
        "view", "3d", "visualization", "zones", "list", "objects", "fields",
        "read", "file", "error", "err", "summary", "info",
    },
    "geometry": {
        "surface", "surfaces", "subsurface", "window", "windows", "door",
        "wall", "walls", "floor", "roof", "wwr", "ratio", "space", "spaces",
        "construction", "constructions", "material", "materials", "insulation",
        "floorplan", "floor_print", "match", "assign",
    },
    "hvac": {
        "hvac", "vav", "reheat", "boiler", "chiller", "coil", "pump", "fan",
        "air_loop", "airloop", "plant_loop", "plantloop", "loop", "terminal",
        "doas", "vrf", "radiant", "equipment", "component", "cop",
        "economizer", "sizing", "setpoint", "supply", "demand", "zone_equipment",
        "baseline_system", "system", "delete",
    },
    "simulation": {
        "simulation", "simulate", "run", "weather", "epw", "location",
        "boston", "chicago", "design_day", "designday", "ddy",
        "run_period", "annual", "simulation_control",
    },
    "results": {
        "results", "eui", "energy", "breakdown", "end_use", "enduse",
        "extract", "report", "qaqc", "qa", "sizing", "timeseries",
        "output", "variables", "compare", "envelope_summary",
        "component_sizing", "zone_summary", "monthly",
    },
    "measures": {
        "measure", "measures", "ruby", "script", "comstock", "apply",
        "test_measure", "edit_measure", "create_measure", "custom",
        "authoring",
    },
    "loads": {
        "people", "lights", "lighting", "equipment", "electric", "gas",
        "infiltration", "plug", "loads", "schedule", "schedules",
        "fractional", "space_type",
    },
    "envelope": {
        "thermostat", "setpoint", "cooling_setpoint", "heating_setpoint",
        "setpoints", "solar", "pv", "photovoltaic", "rooftop",
        "ev", "charging", "ventilation", "adiabatic", "ideal_air",
        "cleanup", "unused", "cost", "lifecycle", "window_construction",
    },
    "analysis": {
        "osaf", "analysis", "analyses", "osa", "sampling", "sample",
        "sweep", "sweeps", "optimization", "optimize", "calibration",
        "calibrate", "algorithm", "algorithms", "datapoint", "datapoints",
        "submit", "batch", "lhs", "doe", "morris", "sobol", "nsga",
        "pareto", "sensitivity", "seed", "server",
    },
    "files": {
        "upload", "uploads", "download", "downloads", "transfer", "file",
        "files", "laptop", "local", "remote", "stage", "staging", "url",
        "quota", "zip",
    },
    "meta": {
        "version", "versions", "status", "health", "server", "sdk",
        "energyplus", "openstudio", "installed",
    },
    "space_types": {
        "space_type", "space_types", "standards", "wizard", "attribution",
        "attribute", "template", "templates", "gbxml", "building_type",
        "assign", "conditioned",
    },
}

# Tool descriptions per group — derived from the registration collector
# (mcp_server.tool_registry), lazily and once per collected roster.
# Maps group (tag) -> list of {"name": ..., "description": ...}
_TOOL_INDEX: dict[str, list[dict[str, str]]] = {}
_INDEX_BUILT = False


def reset_tool_index() -> None:
    """Drop the cached index (tests re-seed the descriptor registry)."""
    global _INDEX_BUILT
    _TOOL_INDEX.clear()
    _INDEX_BUILT = False


def _build_tool_index() -> None:
    """Build the tag -> tools index from collected ToolDescriptors (lazy)."""
    global _INDEX_BUILT
    if _INDEX_BUILT:
        return

    from mcp_server.tool_registry import descriptors, ensure_collected

    ensure_collected()
    for d in sorted(descriptors().values(), key=lambda d: d.name):
        for tag in d.tags:
            _TOOL_INDEX.setdefault(tag, []).append({
                "name": d.name,
                "description": d.description,
            })
    _INDEX_BUILT = True


def _tokenize(text: str) -> set[str]:
    """Split text into lowercase tokens, including underscored compounds."""
    # Split on whitespace and punctuation
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    tokens = set(words)
    # Also add sub-tokens from underscored words
    for w in list(tokens):
        if "_" in w:
            tokens.update(w.split("_"))
    return tokens


def _score_group(tokens: set[str], group: str) -> float:
    """Score a group by keyword overlap with task tokens."""
    keywords = GROUP_KEYWORDS.get(group, set())
    if not keywords:
        return 0.0
    overlap = tokens & keywords
    return len(overlap) / len(keywords) * len(overlap)


def recommend_tools_op(task_description: str) -> dict:
    """Recommend a tool group based on task description.

    Args:
        task_description: Natural language description of the task.

    Returns:
        {"ok": True, "recommended_group": "...", "tools": [...],
         "also_available": [...]}
    """
    _build_tool_index()

    tokens = _tokenize(task_description)
    if not tokens:
        return {"ok": False, "error": "Empty task description"}

    # Score each group
    scores = {
        group: _score_group(tokens, group)
        for group in GROUP_KEYWORDS
    }

    # Best group (break ties by preferring non-core for specificity)
    best = max(scores, key=lambda g: (scores[g], g != "core"))

    # If best score is 0, fall back to core
    if scores[best] == 0:
        best = "core"

    tools = _TOOL_INDEX.get(best, [])
    other_groups = sorted(g for g in GROUP_KEYWORDS if g != best)

    return {
        "ok": True,
        "recommended_group": best,
        "tools": tools,
        "also_available": other_groups,
    }
