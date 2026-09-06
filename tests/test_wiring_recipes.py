"""Unit tests for HVAC wiring recipes — search accuracy + recipe quality.

No Docker needed — recipes are Python dicts.
"""
from __future__ import annotations

import pytest

from mcp_server.skills.api_reference.operations import search_wiring_patterns_op
from mcp_server.skills.api_reference.wiring_recipes import RECIPES

pytestmark = pytest.mark.unit


# ── Recipe quality checks ────────────────────────────────────────────────

def test_all_recipes_have_required_fields():
    # Validates: every recipe has component_type/connections/ruby/notes fields
    for key, recipe in RECIPES.items():
        for field in ("component_type", "connections", "ruby", "notes"):
            assert field in recipe, f"Recipe '{key}' missing '{field}'"
        assert len(recipe["ruby"].strip()) > 0, f"Recipe '{key}' has empty ruby"
        assert len(recipe["connections"]) > 0, f"Recipe '{key}' has no connections"


def test_recipe_ruby_has_no_geometry():
    # Validates: Ruby snippets focus on HVAC wiring, no geometry/schedule boilerplate
    geometry_markers = ["setLength", "setWidth", "num_floors", "addDefaultConstruction"]
    for key, recipe in RECIPES.items():
        ruby = recipe["ruby"].lower()
        for marker in geometry_markers:
            assert marker.lower() not in ruby, (
                f"Recipe '{key}' contains geometry marker '{marker}'"
            )


def test_recipe_count():
    # Validates: at least 20 recipes covering major HVAC patterns
    assert len(RECIPES) >= 20, f"Only {len(RECIPES)} recipes, expected >= 20"


# ── Search accuracy ──────────────────────────────────────────────────────

SEARCH_CASES = [
    # (query, expected_recipe_id in top results)
    ("four pipe beam", "four_pipe_beam_terminal"),
    ("cooled beam", "cooled_beam_terminal"),
    ("DOAS", "doas_overlay"),
    ("VRF", "vrf_system"),
    ("fan coil", "four_pipe_fan_coil"),
    ("baseboard", "baseboard_convective_water"),
    ("boiler hot water plant", "hot_water_plant_loop"),
    ("chiller plant loop", "chilled_water_plant_loop"),
    ("PTAC", "ptac"),
    ("heat pump plant loop", "plant_loop_heat_pump_air_source"),
    ("unitary system", "unitary_system_dx"),
    ("condenser loop", "condenser_water_loop"),
    ("setpoint manager reset", "setpoint_manager_system_node_reset"),
    ("absorption chiller", "absorption_chiller_indirect"),
    ("VAV no reheat", "vav_no_reheat"),
    ("air loop from scratch", "air_loop_from_scratch"),
    ("water source heat pump zone", "water_to_air_heat_pump"),
    # #149: swapping a coil/fan in place must be discoverable by intent AND by symptom
    ("replace coil in place", "replace_supply_branch_component"),
    ("swap fan on air loop", "replace_supply_branch_component"),
    ("addToNode after remove", "replace_supply_branch_component"),
    ("segfault", "replace_supply_branch_component"),
]


@pytest.mark.parametrize(
    "query,expected_id",
    SEARCH_CASES,
    ids=[c[1] for c in SEARCH_CASES],
)
def test_search_finds_recipe(query, expected_id):
    # Validates: search_wiring_patterns returns expected recipe in top 3 for each query
    result = search_wiring_patterns_op(query, max_results=3)
    assert result["ok"]
    found_ids = [r["recipe_id"] for r in result["recipes"]]
    assert expected_id in found_ids, (
        f"'{expected_id}' not in top 3 for '{query}': {found_ids}"
    )


def test_search_no_match():
    # Validates: nonsense query returns empty results (not error)
    result = search_wiring_patterns_op("zzzzNonexistent99")
    assert result["ok"]
    assert result["recipes"] == []


def test_search_max_results():
    # Validates: max_results parameter caps search output
    result = search_wiring_patterns_op("coil loop", max_results=2)
    assert result["ok"]
    assert len(result["recipes"]) > 0, "Search for 'coil loop' should find at least one recipe"
    assert len(result["recipes"]) <= 2, "max_results=2 should cap output"


def test_available_recipes_always_returned():
    # Validates: every search response includes full available_recipes list
    result = search_wiring_patterns_op("anything")
    assert "available_recipes" in result
    assert len(result["available_recipes"]) == len(RECIPES)


# ── Ruby snippet validation ──────────────────────────────────────────────

def test_terminal_recipes_have_addBranchForZone():
    # Validates: terminal recipes include addBranchForZone for zone wiring
    terminal_recipes = [k for k in RECIPES if "terminal" in k or "vav" in k
                        or "piu" in k or "induction" in k]
    for key in terminal_recipes:
        assert "addBranchForZone" in RECIPES[key]["ruby"], (
            f"Terminal recipe '{key}' missing addBranchForZone"
        )


def test_plant_loop_recipes_have_spm():
    # Validates: plant loop recipes include SetpointManager for loop control
    plant_recipes = ["hot_water_plant_loop", "chilled_water_plant_loop",
                     "condenser_water_loop"]
    for key in plant_recipes:
        ruby = RECIPES[key]["ruby"]
        assert "SetpointManager" in ruby, (
            f"Plant recipe '{key}' missing SetpointManager"
        )


def test_zone_hvac_recipes_have_addToThermalZone():
    # Validates: zone HVAC recipes include addToThermalZone for zone assignment
    zone_recipes = ["four_pipe_fan_coil", "baseboard_convective_water",
                    "water_to_air_heat_pump", "ptac", "pthp", "unit_heater"]
    for key in zone_recipes:
        assert "addToThermalZone" in RECIPES[key]["ruby"], (
            f"Zone HVAC recipe '{key}' missing addToThermalZone"
        )


# ── #149: replace-in-place recipe + addToNode/remove hazard ─────────────

def test_replace_recipe_orders_addToNode_before_remove():
    # Regression: #149 — remove() deletes the old component's outlet node; addToNode on a
    # node handle captured before remove() segfaults Ruby (exit 134) and Python (139), so
    # the recipe must attach the new component first and say why in the searchable notes
    recipe = RECIPES["replace_supply_branch_component"]
    ruby = recipe["ruby"]
    assert "addToNode" in ruby and ".remove" in ruby
    assert ruby.index("addToNode") < ruby.index(".remove"), "new.addToNode must precede old.remove"
    assert "inletModelObject" in ruby, "recipe anchors on the OLD component's inlet node"
    assert "setName(old_name)" in ruby, "recipe reuses the old name so downstream refs survive"
    assert "[BUG]" in recipe["notes"] and "segfault" in recipe["notes"].lower()
    assert "addBranchForZone" in recipe["notes"], "notes must route terminal swaps to addBranchForZone"
    assert "3.11.0" in recipe["notes"], "verified-on version must be stated"


@pytest.mark.parametrize("query", ["addToNode", "remove component", "swap coil", "delete node"])
def test_hazards_surface_for_node_queries(query):
    # Validates: the addToNode-after-remove hazard rides along with any node/remove/swap query
    # so the agent sees it before writing the crashing code, not after a 134 exit
    result = search_wiring_patterns_op(query)
    assert result["ok"]
    assert result["hazards"][0]["id"] == "addToNode_after_remove", result.get("hazards")
    assert result["hazards"][0]["recipe"] == "replace_supply_branch_component"
    assert "remove()" in result["hazards"][0]["note"]


@pytest.mark.parametrize("query", [
    "DOAS",
    "setpoint manager node",          # bare "node" is not the hazard
    "remove terminal for zone",       # removeBranchForZone is zone-keyed and safe
    "delete construction layer",      # unrelated delete
    "bug in schedule",                # bare "bug" no longer fires
])
def test_hazards_absent_for_unrelated_query(query):
    # Validates: existing response shape is untouched when the query does not describe the
    # dangerous sequence — bare node/remove/delete words must not spam the warning, or the
    # agent learns to ignore it (review finding on #149)
    result = search_wiring_patterns_op(query)
    assert result["ok"]
    assert "hazards" not in result, result["hazards"]


def test_hazards_for_query_helper_tokenizes_and_dedupes():
    # Validates: hazards_for_query matches whole tokens case-insensitively and returns each
    # hazard once even when several triggers hit
    from mcp_server.skills.api_reference.wiring_recipes import HAZARDS, hazards_for_query
    hits = hazards_for_query("CoilCoolingDXSingleSpeed addToNode remove REPLACE")
    assert [h["id"] for h in hits] == ["addToNode_after_remove"]
    assert hazards_for_query("CoilCoolingDXSingleSpeed") == []
    assert hazards_for_query("") == []
    assert all({"id", "triggers", "note", "recipe"} <= set(h) for h in HAZARDS)
    assert all(h["recipe"] in RECIPES for h in HAZARDS), "every hazard points at a real recipe"
