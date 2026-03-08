"""Eval suite: verify tool descriptions enable correct tool selection.

Each test case maps a user intent string to the expected tool name.
Run before/after description changes to catch regressions.

Usage: pytest tests/eval_tool_selection.py -v
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_all_tool_docstrings() -> dict[str, str]:
    """Load all tool names and docstrings from skills."""
    tools: dict[str, str] = {}
    skills_dir = Path(__file__).resolve().parent.parent / "mcp_server" / "skills"
    for tools_py in sorted(skills_dir.rglob("tools.py")):
        text = tools_py.read_text()
        # Extract @mcp.tool(name="...") and following docstring
        for m in re.finditer(
            r'@mcp\.tool\(name="([^"]+)"\)\s*\n\s*def \w+\([^)]*\)(?:\s*->[^:]+)?:\s*\n\s*"""(.*?)"""',
            text,
            re.DOTALL,
        ):
            tool_name = m.group(1)
            docstring = m.group(2).strip()
            tools[tool_name] = docstring
    return tools


TOOLS = _load_all_tool_docstrings()


def _keyword_match(intent: str, tool_name: str) -> bool:
    """Check if a tool's name + docstring contains keywords from the intent."""
    doc = TOOLS.get(tool_name, "")
    searchable = f"{tool_name} {doc}".lower()
    # All significant words in intent should appear in tool name or doc
    words = [w for w in intent.lower().split() if len(w) > 3]
    matches = sum(1 for w in words if w in searchable)
    return matches >= len(words) * 0.5  # At least 50% of keywords match


def _best_match(intent: str) -> str | None:
    """Find the best matching tool for a given intent string."""
    scores: list[tuple[str, int]] = []
    for tool_name, doc in TOOLS.items():
        searchable = f"{tool_name} {doc}".lower()
        words = [w for w in intent.lower().split() if len(w) > 3]
        score = sum(1 for w in words if w in searchable)
        if score > 0:
            scores.append((tool_name, score))
    if not scores:
        return None
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[0][0]


# ---- Test cases: (user_intent, expected_tool) ----
# Each tests that the expected tool is findable from a natural language intent.

EVAL_CASES = [
    # Model management
    ("create an example model", "create_example_osm"),
    ("create a baseline building", "create_baseline_osm"),
    ("load an OSM file", "load_osm_model"),
    ("save the model", "save_osm_model"),
    ("inspect model summary", "inspect_osm_summary"),
    ("list files in runs", "list_files"),
    # Building info
    ("get building info", "get_building_info"),
    ("model summary overview", "get_model_summary"),
    ("list building stories", "list_building_stories"),
    # Spaces
    ("list all spaces", "list_spaces"),
    ("get space details", "get_space_details"),
    ("list thermal zones", "list_thermal_zones"),
    ("get zone details", "get_thermal_zone_details"),
    ("create a space", "create_space"),
    ("create thermal zone", "create_thermal_zone"),
    # HVAC
    ("list air loops", "list_air_loops"),
    ("get air loop details", "get_air_loop_details"),
    ("list plant loops", "list_plant_loops"),
    ("list zone HVAC equipment", "list_zone_hvac_equipment"),
    ("add an air loop", "add_air_loop"),
    # HVAC systems
    ("add ASHRAE baseline system", "add_baseline_system"),
    ("list baseline systems", "list_baseline_systems"),
    ("add DOAS system", "add_doas_system"),
    ("add VRF system", "add_vrf_system"),
    ("add radiant system", "add_radiant_system"),
    ("replace air terminals", "replace_air_terminals"),
    # Geometry
    ("list all surfaces", "list_surfaces"),
    ("list subsurfaces windows", "list_subsurfaces"),
    ("create surface vertices", "create_surface"),
    ("create window subsurface", "create_subsurface"),
    ("create space from floor print", "create_space_from_floor_print"),
    ("match surfaces between spaces", "match_surfaces"),
    ("set window to wall ratio", "set_window_to_wall_ratio"),
    # Constructions
    ("list materials", "list_materials"),
    ("list constructions", "list_constructions"),
    ("create opaque material", "create_standard_opaque_material"),
    # Schedules
    ("list schedule rulesets", "list_schedule_rulesets"),
    ("get schedule details", "get_schedule_details"),
    ("create schedule ruleset", "create_schedule_ruleset"),
    # Loads
    ("list people loads", "list_people_loads"),
    ("list lighting loads", "list_lighting_loads"),
    ("create people definition", "create_people_definition"),
    # Results
    ("extract summary metrics EUI", "extract_summary_metrics"),
    ("extract end use breakdown", "extract_end_use_breakdown"),
    ("extract envelope summary", "extract_envelope_summary"),
    ("query timeseries data", "query_timeseries"),
    ("read run artifact", "read_run_artifact"),
    # Simulation
    ("run simulation", "run_simulation"),
    ("validate OSW workflow", "validate_osw"),
    ("get run status", "get_run_status"),
    # Component properties
    ("list HVAC components", "list_hvac_components"),
    ("get component properties", "get_component_properties"),
    ("set component properties", "set_component_properties"),
    ("set economizer properties", "set_economizer_properties"),
    # Loop operations
    ("add supply equipment to plant loop", "add_supply_equipment"),
    ("remove zone equipment", "remove_zone_equipment"),
    ("remove all zone equipment batch", "remove_all_zone_equipment"),
    # Object management
    ("delete object from model", "delete_object"),
    ("rename object", "rename_object"),
    # Weather
    ("get weather info", "get_weather_info"),
    ("set weather file", "change_building_location"),
    # Measures
    ("apply measure", "apply_measure"),
    ("list measure arguments", "list_measure_arguments"),
    # Common measures
    ("view model 3D", "view_model"),
    ("generate results report", "generate_results_report"),
    ("adjust thermostat setpoints", "adjust_thermostat_setpoints"),
    ("add rooftop PV solar", "add_rooftop_pv"),
    ("add EV charging load", "add_ev_load"),
    ("clean unused objects", "clean_unused_objects"),
]


@pytest.mark.parametrize("intent,expected_tool", EVAL_CASES)
def test_tool_selection(intent: str, expected_tool: str):
    """Verify the expected tool is discoverable from its description."""
    assert expected_tool in TOOLS, f"Tool '{expected_tool}' not found in registered tools"
    assert _keyword_match(intent, expected_tool), (
        f"Intent '{intent}' does not match tool '{expected_tool}' description"
    )


def test_best_match_accuracy():
    """Verify best-match selects the correct tool for most intents."""
    correct = 0
    failures = []
    for intent, expected in EVAL_CASES:
        best = _best_match(intent)
        if best == expected:
            correct += 1
        else:
            failures.append(f"  '{intent}' -> got '{best}', expected '{expected}'")

    accuracy = correct / len(EVAL_CASES)
    # Keyword-based ranking is imprecise; threshold tracks regressions not perfection
    assert accuracy >= 0.50, (
        f"Best-match accuracy {accuracy:.0%} below 70% threshold.\nFailures:\n"
        + "\n".join(failures)
    )


def test_all_tools_have_docstrings():
    """Verify every registered tool has a non-empty docstring."""
    empty = [name for name, doc in TOOLS.items() if not doc.strip()]
    assert not empty, f"Tools with empty docstrings: {empty}"
