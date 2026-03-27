"""Integration tests for search_api tool — validates class/method discovery.

Requires Docker — needs openstudio Python bindings to introspect the SDK.

The key value: proves the tool catches hallucinated methods (methods the LLM
invents that don't exist on the real class). This is the original motivation
for building search_api.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def _import_search_api_op():
    """Import lazily — only available inside Docker with openstudio."""
    from mcp_server.skills.api_reference.operations import search_api_op
    return search_api_op


# ── Exact match ──────────────────────────────────────────────────────────

def test_search_class_exact_match():
    # Validates: exact class name returns single match for CoilCoolingFourPipeBeam
    search = _import_search_api_op()
    result = search("CoilCoolingFourPipeBeam")
    assert result["ok"]
    assert len(result["classes"]) == 1
    assert result["classes"][0]["class_name"] == "CoilCoolingFourPipeBeam"


# ── Pattern matching ─────────────────────────────────────────────────────

def test_search_class_pattern():
    # Validates: partial pattern CoilCooling returns multiple matching classes
    search = _import_search_api_op()
    result = search("CoilCooling")
    assert result["ok"]
    assert len(result["classes"]) > 1
    for cls in result["classes"]:
        assert "CoilCooling" in cls["class_name"]


def test_search_class_case_insensitive():
    # Validates: case-insensitive search finds classes
    search = _import_search_api_op()
    result = search("coilcooling")
    assert result["ok"]
    assert len(result["classes"]) >= 1


def test_search_class_no_match():
    # Validates: nonexistent class pattern returns empty classes list
    search = _import_search_api_op()
    result = search("NonexistentWidget99")
    assert result["ok"]
    assert result["classes"] == []


def test_max_classes_cap():
    # Validates: max_classes parameter caps result count
    search = _import_search_api_op()
    result = search("Coil", max_classes=3)
    assert result["ok"]
    assert len(result["classes"]) <= 3


# ── Method grouping ──────────────────────────────────────────────────────

def test_method_grouping():
    # Validates: methods grouped into setters/getters/other with correct prefixes
    search = _import_search_api_op()
    result = search("CoilCoolingFourPipeBeam")
    cls = result["classes"][0]
    assert "setters" in cls
    assert "getters" in cls
    assert "other" in cls
    # Setters start with "set"
    for m in cls["setters"]:
        assert m.startswith("set"), f"Setter '{m}' doesn't start with 'set'"
    # Getters don't start with "set"
    for m in cls["getters"]:
        assert not m.startswith("set"), f"Getter '{m}' starts with 'set'"


def test_method_pattern_filter():
    # Validates: method_pattern filters methods, all results match pattern
    search = _import_search_api_op()
    unfiltered = search("CoilCoolingFourPipeBeam")
    filtered = search("CoilCoolingFourPipeBeam", method_pattern="Rated|COP")
    assert filtered["ok"]

    cls_f = filtered["classes"][0]
    cls_u = unfiltered["classes"][0]
    total_f = len(cls_f["setters"]) + len(cls_f["getters"]) + len(cls_f["other"])
    total_u = len(cls_u["setters"]) + len(cls_u["getters"]) + len(cls_u["other"])
    assert total_f < total_u, "Filtered should have fewer methods"
    # All returned methods should match pattern
    for m in cls_f["setters"] + cls_f["getters"] + cls_f["other"]:
        assert "rated" in m.lower() or "cop" in m.lower(), (
            f"Method '{m}' doesn't match Rated|COP pattern"
        )


def test_exclude_base_methods():
    # Validates: base methods (clone/remove/name) excluded by default, included with flag
    search = _import_search_api_op()
    # Default: base methods excluded
    result = search("CoilCoolingFourPipeBeam")
    cls = result["classes"][0]
    all_methods = cls["setters"] + cls["getters"] + cls["other"]
    base_methods = {"clone", "remove", "name"}
    for bm in base_methods:
        assert bm not in all_methods, (
            f"Base method '{bm}' should be excluded by default"
        )

    # With include_base=True: they appear
    result_incl = search("CoilCoolingFourPipeBeam", include_base=True)
    cls_incl = result_incl["classes"][0]
    all_incl = cls_incl["setters"] + cls_incl["getters"] + cls_incl["other"]
    # At least "name" should appear (every ModelObject has it)
    assert "name" in all_incl, "'name' should appear when include_base=True"


def test_nonexistent_method_returns_empty():
    # Validates: nonexistent method_pattern returns empty setter/getter/other lists
    search = _import_search_api_op()
    result = search("CoilCoolingFourPipeBeam", method_pattern="zzzzNonexistent")
    assert result["ok"]
    cls = result["classes"][0]
    assert cls["setters"] == []
    assert cls["getters"] == []
    assert cls["other"] == []


# ── Hallucination detection (the whole reason for this tool) ─────────────

def test_validates_real_methods_exist():
    """Known good methods must appear; known bad (hallucinated) must not.

    The bad methods come from an actual debug session where the LLM invented
    method names that don't exist on CoilCoolingFourPipeBeam.
    """
    # Validates: known real methods exist, known hallucinated methods do not
    search = _import_search_api_op()
    result = search("CoilCoolingFourPipeBeam", include_base=True)
    cls = result["classes"][0]
    all_methods = set(cls["setters"] + cls["getters"] + cls["other"])

    # Known GOOD methods (from Ruby/Python API)
    good_methods = {"setName", "setBeamRatedCoolingCapacityperBeamLength"}
    for m in good_methods:
        assert m in all_methods, f"Real method '{m}' not found"

    # Known BAD methods (hallucinated by LLM in debug session)
    bad_methods = {
        "setRatedCoolingCoefficientOfPerformance",
        "setLatentEffectivenessat75CoolingAirFlow",
        "setMaximumCyclingRate",
    }
    for m in bad_methods:
        assert m not in all_methods, (
            f"Hallucinated method '{m}' should NOT exist"
        )


def test_ruby_python_method_parity_spot_check():
    """Spot-check that Python bindings expose known Ruby setter names."""
    # Validates: Python bindings expose known Ruby setter names for four-pipe beam
    search = _import_search_api_op()
    result = search("CoilCoolingFourPipeBeam")
    cls = result["classes"][0]
    setters = set(cls["setters"])

    # These setter names are confirmed in the Ruby API docs
    # Note: heating setters are on CoilHeatingFourPipeBeam, not Cooling
    expected_setters = [
        "setBeamRatedCoolingCapacityperBeamLength",
        "setBeamRatedChilledWaterVolumeFlowRateperBeamLength",
    ]
    for m in expected_setters:
        assert m in setters, f"Expected Ruby-parity setter '{m}' not found"


# ── MCP integration ─────────────────────────────────────────────────────

def test_search_api_via_mcp():
    """search_api tool works through full MCP stack."""
    # Validates: search_api works through full MCP server stack
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def _test():
        params = StdioServerParameters(
            command="openstudio-mcp", args=[], env=None,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(
                    "search_api",
                    {"class_pattern": "CoilCoolingFourPipeBeam"},
                )
                # Result is a list of TextContent blocks
                import json
                data = json.loads(result.content[0].text)
                assert data["ok"]
                assert len(data["classes"]) == 1

    asyncio.run(_test())
