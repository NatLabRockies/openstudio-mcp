"""Tool routing tests — tags (Phase 2) and recommend_tools accuracy (Phase 3).

No Docker needed. Uses FakeMCP for tag verification, and calls
recommend_tools_op directly for routing accuracy.

Phase 2/3 tests are marked xfail until those features are implemented.
They serve as gate tests — flip to strict=True when the feature lands.
"""
from __future__ import annotations

import json

import pytest

from mcp_server.skills import register_all_skills
from tests.test_tool_baseline import CORE_TOOLS

pytestmark = pytest.mark.unit


def _register_tools_with_tags() -> dict[str, dict]:
    """Register all skills via FakeMCP, capturing tags."""
    registered = {}

    class FakeMCP:
        def tool(self, name=None, **kwargs):
            def decorator(fn):
                tool_name = name or fn.__name__
                registered[tool_name] = {
                    "name": tool_name,
                    "doc": fn.__doc__ or "",
                    "tags": kwargs.get("tags", set()),
                }
                return fn
            return decorator

        def prompt(self, **kw):
            return lambda fn: fn

        def resource(self, *a, **kw):
            return lambda fn: fn

    register_all_skills(FakeMCP())
    return registered


# ── Phase 2 gate tests ───────────────────────────────────────────────────

def test_all_tools_have_tags():
    # Validates: every registered MCP tool has at least one tag for routing
    tools = _register_tools_with_tags()
    untagged = [name for name, t in tools.items() if not t["tags"]]
    if untagged:
        print(f"\nUntagged tools ({len(untagged)}):")
        for name in sorted(untagged):
            print(f"  {name}")
    assert not untagged, (
        f"{len(untagged)} tools have no tags: {sorted(untagged)[:10]}..."
    )


def test_group_sizes_balanced():
    # Validates: no tool group exceeds 40 members (prevents core group bloat)
    tools = _register_tools_with_tags()
    groups: dict[str, list[str]] = {}
    for name, t in tools.items():
        for tag in t["tags"]:
            groups.setdefault(tag, []).append(name)

    if not groups:
        pytest.fail("No tools have tags yet")

    print("\nGroup distribution:")
    for group, members in sorted(groups.items()):
        print(f"  {group}: {len(members)} tools")
        assert len(members) <= 40, (
            f"Group '{group}' has {len(members)} tools (max 40)"
        )


# ── Phase 3 gate tests: recommend_tools accuracy ────────────────────────

ROUTING_CASES = [
    # (task_description, expected_group, must_include_tool)
    ("create a measure to fix OA warnings", "measures", "create_measure"),
    ("write a Ruby measure that sets lights", "measures", "create_measure"),
    ("what's the EUI", "results", "extract_summary_metrics"),
    ("show me monthly energy breakdown", "results", "extract_end_use_breakdown"),
    ("generate a report of simulation results", "results", "generate_results_report"),
    ("add VAV reheat to all zones", "hvac", "add_baseline_system"),
    ("add a boiler to the hot water loop", "hvac", "add_supply_equipment"),
    ("set chiller COP to 5.5", "hvac", "set_component_properties"),
    ("create a 2-story office building", "core", "create_new_building"),
    ("run an annual simulation", "simulation", "run_simulation"),
    ("set weather to Boston", "simulation", "change_building_location"),
    ("add R-30 roof insulation", "geometry", "create_construction"),
    ("set window to wall ratio to 40%", "geometry", "set_window_to_wall_ratio"),
    ("add 50 W/m2 plug loads", "loads", "create_electric_equipment"),
    ("show me a 3D view of the building", "core", "view_model"),
    ("adjust cooling setpoint by 2F", "envelope", "adjust_thermostat_setpoints"),
    ("add rooftop solar panels", "envelope", "add_rooftop_pv"),
    ("apply the lighting measure I created", "measures", "apply_measure"),
    ("test my custom measure", "measures", "test_measure"),
    ("what zones are in the building", "core", "list_model_objects"),
    ("read the error file at /inputs/eplusout.err", "core", "read_file"),
    ("extract HVAC sizing from the simulation", "results", "extract_hvac_sizing"),
    ("add a design day for Chicago", "simulation", "add_design_day"),
    ("delete the unused boiler", "hvac", "remove_supply_equipment"),
    ("create a fractional schedule", "loads", "create_schedule_ruleset"),
]


@pytest.mark.parametrize(
    "task,expected_group,must_include",
    ROUTING_CASES,
    ids=[f"{c[1][:30]}→{c[2]}" for c in ROUTING_CASES],
)
def test_recommend_tools(task, expected_group, must_include):
    # Validates: recommend_tools routes task description to correct group and includes expected tool
    from mcp_server.skills.tool_router.operations import recommend_tools_op

    result = recommend_tools_op(task)
    assert result["ok"], f"recommend_tools failed: {result}"
    assert result["recommended_group"] == expected_group, (
        f"Expected group '{expected_group}', got '{result['recommended_group']}'"
    )
    tool_names = [t["name"] for t in result["tools"]]
    assert must_include in tool_names, (
        f"'{must_include}' not in recommended tools for '{task}': {tool_names}"
    )


# ── Schema size comparison ───────────────────────────────────────────────

def test_tool_schema_token_count():
    # Validates: core tool subset is < 30% of full schema size (token reduction target)
    tools = _register_tools_with_tags()

    all_data = [{"name": t["name"], "description": t["doc"]}
                for t in tools.values()]
    core_data = [{"name": t["name"], "description": t["doc"]}
                 for t in tools.values() if t["name"] in CORE_TOOLS]

    all_chars = len(json.dumps(all_data))
    core_chars = len(json.dumps(core_data))

    print(f"\nAll tools: {all_chars:,} chars (~{all_chars // 4:,} tokens)")
    print(f"Core tools: {core_chars:,} chars (~{core_chars // 4:,} tokens)")
    print(f"Reduction: {100 - core_chars / all_chars * 100:.0f}%")

    assert core_chars < all_chars * 0.3, (
        f"Core ({core_chars}) is {core_chars / all_chars * 100:.0f}% of full "
        f"({all_chars}) — must be < 30%"
    )
