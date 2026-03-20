"""Baseline measurements for tool routing optimization.

Captures current state (tool count, schema size, tag coverage) before
any changes. Re-run after each phase to measure impact.

No Docker needed — uses FakeMCP pattern from test_skill_registration.py.
"""
from __future__ import annotations

import json

from mcp_server.skills import register_all_skills

# Core tools — the ~15 always-loaded tools from the routing plan.
# These cover model lifecycle + discovery and should handle the 80% case.
CORE_TOOLS = {
    "load_osm_model", "save_osm_model", "list_files", "list_weather_files",
    "create_new_building", "create_bar_building",
    "get_building_info", "get_model_summary",
    "list_model_objects", "get_object_fields", "set_object_property",
    "run_simulation", "get_run_status",
    "extract_summary_metrics",
    "list_skills", "get_skill",
}


def _register_tools_with_docs() -> dict[str, dict]:
    """Register all skills via FakeMCP, capturing name + docstring."""
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


def test_tool_count():
    """Record current tool count — expect 139 before search_api."""
    tools = _register_tools_with_docs()
    count = len(tools)
    print(f"\nTool count: {count}")
    assert count == 142, f"Expected 142 tools, got {count}"


def test_total_schema_chars():
    """Measure total chars of tool names + docstrings (proxy for tokens).

    ~4 chars/token is a rough estimate. No assertion — just baseline capture.
    """
    tools = _register_tools_with_docs()
    # Serialize name + doc for each tool (approximates schema size)
    schema_data = [{"name": t["name"], "description": t["doc"]}
                   for t in tools.values()]
    total_chars = len(json.dumps(schema_data))
    est_tokens = total_chars // 4
    print(f"\nTotal schema chars: {total_chars:,}")
    print(f"Estimated tokens: {est_tokens:,}")
    # No hard assertion — this is a measurement


def test_tags_coverage():
    """Check how many tools have tags. Before Phase 2: expect 0."""
    tools = _register_tools_with_docs()
    tagged = {name: t for name, t in tools.items() if t["tags"]}
    untagged = {name for name in tools if name not in tagged}

    pct = len(tagged) / len(tools) * 100 if tools else 0
    print(f"\nTagged: {len(tagged)}/{len(tools)} ({pct:.0f}%)")
    if untagged:
        print(f"Untagged: {sorted(untagged)}")

    # Before Phase 2, expect 0 tagged. After Phase 2, update to 100%.
    # For now this is informational — will add assertion after Phase 2.


def test_core_tools_identified():
    """All planned core tools exist in the registered tool set."""
    tools = _register_tools_with_docs()
    registered_names = set(tools.keys())
    missing = CORE_TOOLS - registered_names
    assert not missing, f"Core tools missing from registry: {missing}"

    ratio = len(CORE_TOOLS) / len(registered_names) * 100
    print(f"\nCore tools: {len(CORE_TOOLS)}/{len(registered_names)} ({ratio:.0f}%)")


def test_core_schema_chars():
    """Measure schema size of core-only subset vs full set."""
    tools = _register_tools_with_docs()

    all_data = [{"name": t["name"], "description": t["doc"]}
                for t in tools.values()]
    core_data = [{"name": t["name"], "description": t["doc"]}
                 for t in tools.values() if t["name"] in CORE_TOOLS]

    all_chars = len(json.dumps(all_data))
    core_chars = len(json.dumps(core_data))
    ratio = core_chars / all_chars * 100 if all_chars else 0

    print(f"\nAll tools schema: {all_chars:,} chars (~{all_chars // 4:,} tokens)")
    print(f"Core tools schema: {core_chars:,} chars (~{core_chars // 4:,} tokens)")
    print(f"Core/All ratio: {ratio:.1f}%")
