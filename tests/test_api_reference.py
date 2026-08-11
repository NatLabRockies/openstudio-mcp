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


def _names(entries):
    """Method names from signature strings like 'setName(name) -> Boolean'."""
    return {e.split("(", 1)[0] for e in entries}


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
    all_methods = _names(cls["setters"] + cls["getters"] + cls["other"])
    base_methods = {"clone", "remove", "name"}
    for bm in base_methods:
        assert bm not in all_methods, (
            f"Base method '{bm}' should be excluded by default"
        )

    # With include_base=True: they appear
    result_incl = search("CoilCoolingFourPipeBeam", include_base=True)
    cls_incl = result_incl["classes"][0]
    all_incl = _names(cls_incl["setters"] + cls_incl["getters"] + cls_incl["other"])
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
    all_methods = _names(cls["setters"] + cls["getters"] + cls["other"])

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
    setters = _names(cls["setters"])

    # These setter names are confirmed in the Ruby API docs
    # Note: heating setters are on CoilHeatingFourPipeBeam, not Cooling
    expected_setters = [
        "setBeamRatedCoolingCapacityperBeamLength",
        "setBeamRatedChilledWaterVolumeFlowRateperBeamLength",
    ]
    for m in expected_setters:
        assert m in setters, f"Expected Ruby-parity setter '{m}' not found"


# ── Signatures (params + return types) ───────────────────────────────────

def test_methods_carry_signatures():
    """Each method entry is 'name(params) -> ReturnType', not a bare name."""
    search = _import_search_api_op()
    result = search("CoilCoolingFourPipeBeam")
    cls = result["classes"][0]

    setter = next(
        s for s in cls["setters"]
        if s.startswith("setBeamRatedCoolingCapacityperBeamLength(")
    )
    # Has a parameter and a rendered return type
    assert "->" in setter
    assert setter.split("(", 1)[1].split(")", 1)[0].strip(), "setter should take an arg"


# ── return types are sourced, not guessed ───────────────────────────────


def _returns(search, class_name, method):
    """The rendered return type of one method, or None.

    class_pattern is a regex `search`, so "Space" also matches SpaceType and
    FloorspaceReverseTranslator — select the exact class rather than trusting order.
    """
    result = search(class_name, method_pattern=f"^{method}$", max_classes=50)
    cls = next((c for c in result["classes"] if c["class_name"] == class_name), None)
    if cls is None:
        return None
    for entry in cls["setters"] + cls["getters"] + cls["other"]:
        if entry.split("(", 1)[0] == method:
            return entry.split("->", 1)[1].strip() if "->" in entry else None
    return None


@pytest.mark.parametrize(
    ("class_name", "method", "expected"),
    [
        # The pair that motivated this: identical `-> Object` under the old name-guesser,
        # yet `.get` is mandatory on one and raises NoMethodError on the other.
        ("ZoneHVACBaseboardConvectiveElectric", "efficiency", "Float"),
        ("ZoneHVACBaseboardConvectiveElectric", "nominalCapacity", "Float, nil"),
        # The guesser reported this as Boolean because the name matches `is[A-Z]`. It is
        # really boost::optional<std::string>, empty until a sizing run — so
        # `next unless zone.isConditioned` silently skipped every zone.
        ("ThermalZone", "isConditioned", "String, nil"),
        ("SpaceType", "spaces", "Array<Space>"),
        ("Space", "thermalZone", "ThermalZone, nil"),
    ],
)
def test_return_types_come_from_headers(class_name, method, expected):
    search = _import_search_api_op()
    assert _returns(search, class_name, method) == expected


def test_swig_synthesized_types_still_resolve():
    """The Model#get* family is declared in no header — it must keep its wrapper-parsed
    type. Guards against 'simplifying' the wrapper pass away: headers cover only 4 of the
    2,876 pairs it supplies.
    """
    search = _import_search_api_op()
    assert _returns(search, "Model", "getThermalZoneByName") == "ThermalZone, nil"


def test_return_types_are_never_guessed():
    """A type is either sourced from a real declaration, or admitted unknown. Never
    inferred from the method's name — that heuristic reported `isConditioned -> Boolean`
    when it is really an empty-until-sizing `boost::optional<std::string>`.
    """
    from mcp_server.skills.api_reference import _signatures

    assert not hasattr(_signatures, "_infer_return_type"), "the name-guesser must not return"


def test_every_returnable_method_has_a_sourced_type():
    """**Ratchet: 100% of what search_api can return.** No `?`, no guesses.

    search_api lists `dir(openstudio.model)`; those 21,691 methods are the ones a caller
    can actually be handed, and every one resolves to a type read from a C++ header, a
    SWIG %extend, or a wrapper annotation. Coverage was 98.01% before the parser fixes and
    10.84% before the headers were used at all.

    This is pinned at exactly 0 rather than a loose bound: an SDK upgrade that introduces a
    declaration shape the parser can't read should fail here loudly, not degrade quietly to
    `?`. If that happens, fix the parser or — if the shape is genuinely unreadable — change
    this assertion deliberately and say why.
    """
    import openstudio

    from mcp_server.skills.api_reference import _signatures

    sigs = _signatures.signatures()
    returnable = {
        name
        for name in dir(openstudio.model)
        if not name.startswith("_") and isinstance(getattr(openstudio.model, name), type)
    }

    unknown = {
        f"{cls}#{method}"
        for cls in returnable & set(sigs)
        for method, info in sigs[cls].items()
        if info["returns"] == _signatures.UNKNOWN_TYPE
    }
    total = sum(len(sigs[cls]) for cls in returnable & set(sigs))

    assert total > 20000, f"expected the full model surface, got {total}"
    assert not unknown, f"{len(unknown)} of {total} methods have no sourced type: {sorted(unknown)[:10]}"


# ── Downcast collapse ────────────────────────────────────────────────────

def test_casts_collapsed_with_include_base():
    """to_<Class>() downcast family collapses to one summary line, not ~400 entries."""
    # Regression: include_base dumped every to_<Class>() cast, bloating the response
    search = _import_search_api_op()
    result = search("People", include_base=True)
    cls = next(c for c in result["classes"] if c["class_name"] == "People")
    other = cls["other"]

    # Exactly one collapsed summary entry, no individual cast entries
    summaries = [e for e in other if e.startswith("to_<TargetClass>(")]
    assert len(summaries) == 1, f"Expected one cast summary, got {summaries}"
    assert "downcast methods" in summaries[0]
    for leaked in ("to_AirGap(", "to_BoilerHotWater(", "to_Space("):
        assert not any(e.startswith(leaked) for e in other), (
            f"Individual cast '{leaked}' should be collapsed"
        )
    # The summary reports how many casts it folded; that count (hundreds) must be
    # far larger than every remaining 'other' entry combined — proving collapse.
    folded = int(summaries[0].split("#", 1)[1].split()[0])
    assert folded > 100, f"Expected hundreds of casts folded, got {folded}"
    assert len(other) < folded, (
        f"'other' ({len(other)}) should be far smaller than folded casts ({folded})"
    )


def test_casts_excluded_by_default():
    # Regression: default (include_base=False) excludes base casts entirely — no summary
    search = _import_search_api_op()
    cls = search("People")["classes"][0]
    summaries = [e for e in cls["other"] if e.startswith("to_<TargetClass>(")]
    assert summaries == [], "No cast summary expected when include_base=False"


def test_explicit_cast_search_not_collapsed():
    # Regression: method_pattern targeting casts lists matches literally, no collapse
    search = _import_search_api_op()
    cls = search("People", include_base=True, method_pattern="to_Space$")["classes"][0]
    all_entries = cls["setters"] + cls["getters"] + cls["other"]
    assert any(e.startswith("to_Space(") for e in all_entries)
    assert not any(e.startswith("to_<TargetClass>(") for e in all_entries)


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
