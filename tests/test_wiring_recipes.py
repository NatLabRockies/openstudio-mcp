"""Unit tests for HVAC wiring recipes — search accuracy + recipe quality.

No Docker needed — recipes are Python dicts.
"""
from __future__ import annotations

import pytest

from mcp_server.skills.api_reference.operations import search_wiring_patterns_op
from mcp_server.skills.api_reference.wiring_recipes import RECIPES


# ── Recipe quality checks ────────────────────────────────────────────────

def test_all_recipes_have_required_fields():
    """Every recipe must have component_type, connections, ruby, notes."""
    for key, recipe in RECIPES.items():
        for field in ("component_type", "connections", "ruby", "notes"):
            assert field in recipe, f"Recipe '{key}' missing '{field}'"
        assert len(recipe["ruby"].strip()) > 0, f"Recipe '{key}' has empty ruby"
        assert len(recipe["connections"]) > 0, f"Recipe '{key}' has no connections"


def test_recipe_ruby_has_no_geometry():
    """Ruby snippets should not contain geometry/schedule boilerplate."""
    geometry_markers = ["setLength", "setWidth", "num_floors", "addDefaultConstruction"]
    for key, recipe in RECIPES.items():
        ruby = recipe["ruby"].lower()
        for marker in geometry_markers:
            assert marker.lower() not in ruby, (
                f"Recipe '{key}' contains geometry marker '{marker}'"
            )


def test_recipe_count():
    """Should have at least 20 recipes covering major HVAC patterns."""
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
]


@pytest.mark.parametrize(
    "query,expected_id",
    SEARCH_CASES,
    ids=[c[1] for c in SEARCH_CASES],
)
def test_search_finds_recipe(query, expected_id):
    """Search returns expected recipe in top 3 results."""
    result = search_wiring_patterns_op(query, max_results=3)
    assert result["ok"]
    found_ids = [r["recipe_id"] for r in result["recipes"]]
    assert expected_id in found_ids, (
        f"'{expected_id}' not in top 3 for '{query}': {found_ids}"
    )


def test_search_no_match():
    """Nonsense query returns empty results."""
    result = search_wiring_patterns_op("zzzzNonexistent99")
    assert result["ok"]
    assert result["recipes"] == []


def test_search_max_results():
    """max_results caps output."""
    result = search_wiring_patterns_op("coil loop", max_results=2)
    assert result["ok"]
    assert len(result["recipes"]) <= 2


def test_available_recipes_always_returned():
    """Every search returns the full list of available recipe IDs."""
    result = search_wiring_patterns_op("anything")
    assert "available_recipes" in result
    assert len(result["available_recipes"]) == len(RECIPES)


# ── Ruby snippet validation ──────────────────────────────────────────────

def test_terminal_recipes_have_addBranchForZone():
    """Terminal recipes must show zone connection."""
    terminal_recipes = [k for k in RECIPES if "terminal" in k or "vav" in k
                        or "piu" in k or "induction" in k]
    for key in terminal_recipes:
        assert "addBranchForZone" in RECIPES[key]["ruby"], (
            f"Terminal recipe '{key}' missing addBranchForZone"
        )


def test_plant_loop_recipes_have_spm():
    """Plant loop construction recipes must show setpoint manager."""
    plant_recipes = ["hot_water_plant_loop", "chilled_water_plant_loop",
                     "condenser_water_loop"]
    for key in plant_recipes:
        ruby = RECIPES[key]["ruby"]
        assert "SetpointManager" in ruby, (
            f"Plant recipe '{key}' missing SetpointManager"
        )


def test_zone_hvac_recipes_have_addToThermalZone():
    """Zone HVAC recipes must show zone connection."""
    zone_recipes = ["four_pipe_fan_coil", "baseboard_convective_water",
                    "water_to_air_heat_pump", "ptac", "pthp", "unit_heater"]
    for key in zone_recipes:
        assert "addToThermalZone" in RECIPES[key]["ruby"], (
            f"Zone HVAC recipe '{key}' missing addToThermalZone"
        )
