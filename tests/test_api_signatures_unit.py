"""Unit tests for the C++ header parser behind ``search_api`` return types.

These run without the OpenStudio SDK: every fixture is synthetic header text, so they
execute in the fast ``-m "not integration"`` shard. Each hazard case below is drawn from a
real construct found in the shipped 3.11.0 headers, not invented — the comment on each
says which.

The counterpart integration assertions (real SDK, real values) live in
``test_api_reference.py``.
"""
from __future__ import annotations

import pytest

from mcp_server.skills.api_reference._headers import (
    _build,
    _locate_header_dir,
    _parse_header,
    map_cpp_type,
)

pytestmark = pytest.mark.unit


def _write(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------
# map_cpp_type — the C++ -> Ruby rendering table
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cpp", "expected"),
    [
        # The case that motivated the whole change: identical `-> Object` under the old
        # name-guesser, opposite handling in Ruby.
        ("double", "Float"),
        ("boost::optional<double>", "Float, nil"),
        # ThermalZone#isConditioned — the guesser called this Boolean. It is not.
        ("boost::optional<std::string>", "String, nil"),
        ("void", "void"),
        ("bool", "Boolean"),
        ("int", "Integer"),
        ("unsigned", "Integer"),
        ("size_t", "Integer"),
        ("std::string", "String"),
        ("float", "Float"),
        # SDK object returns
        ("Schedule", "Schedule"),
        ("boost::optional<ThermalZone>", "ThermalZone, nil"),
        ("std::vector<Space>", "Array<Space>"),
        ("std::vector<std::string>", "Array<String>"),
        # const / ref / ptr decoration must not change the rendered type
        ("const std::string", "String"),
        ("double&", "Float"),
        # Types with no useful Ruby rendering degrade to Object, never to a guess.
        ("std::map<UUID, UUID>", "Object"),
        # A vector of un-renderable elements is plain `Array` — `Array<Object>` would add
        # noise without adding information.
        ("std::vector<std::pair<std::string, std::string>>", "Array"),
        ("boost::optional<std::pair<ConstructionBase, int>>", "Object, nil"),
    ],
)
def test_map_cpp_type(cpp, expected):
    assert map_cpp_type(cpp) == expected


def test_map_cpp_type_gates_unknown_classes():
    """Header-only classes absent from the bindings must not render a name Ruby lacks.

    `Connection`, `ComponentWatcher` and `DesignSpecificationZoneAirDistribution` are
    declared in headers but confirmed absent from `OpenStudio::Model` in Ruby.
    """
    known = {"ThermalZone", "Space"}
    assert map_cpp_type("ThermalZone", known) == "ThermalZone"
    assert map_cpp_type("ComponentWatcher", known) == "Object"
    assert map_cpp_type("boost::optional<ComponentWatcher>", known) == "Object, nil"
    assert map_cpp_type("std::vector<Space>", known) == "Array<Space>"


# --------------------------------------------------------------------------------------
# _parse_header — declaration extraction and its hazards
# --------------------------------------------------------------------------------------


def test_parses_public_declarations(tmp_path):
    src = """
class MODEL_API ZoneHVACBaseboardConvectiveElectric : public ZoneHVACComponent {
 public:
    double efficiency() const;
    boost::optional<double> nominalCapacity() const;
    bool setEfficiency(double efficiency);
    void autosizeNominalCapacity();
    bool isNominalCapacityAutosized() const;
    static IddObjectType iddObjectType();
};
"""
    parsed = _parse_header(_write(tmp_path, "X.hpp", src))
    methods = parsed["ZoneHVACBaseboardConvectiveElectric"]
    assert methods["efficiency"] == "double"
    assert methods["nominalCapacity"] == "boost::optional<double>"
    assert methods["setEfficiency"] == "bool"
    assert methods["autosizeNominalCapacity"] == "void"
    assert methods["isNominalCapacityAutosized"] == "bool"
    assert methods["iddObjectType"] == "IddObjectType"  # `static` stripped


def test_ignores_declarations_inside_comments(tmp_path):
    """Real hazard: CoilCoolingWater.hpp:29 has `*  <li> bool addToNode(Node & node);</li>`."""
    src = """
class MODEL_API CoilCoolingWater : public WaterToAirComponent {
 /** Doxygen block:
  *  <li> bool addToNode(Node & node);</li>
  *  You can then call the helper method `bool assignHistoricalEffectivenessCurves()`
  */
 public:
    // bool commentedOut() const;
    double realMethod() const;
};
"""
    methods = _parse_header(_write(tmp_path, "C.hpp", src))["CoilCoolingWater"]
    assert "realMethod" in methods
    assert "addToNode" not in methods
    assert "assignHistoricalEffectivenessCurves" not in methods
    assert "commentedOut" not in methods


def test_ignores_macros(tmp_path):
    """REGISTER_LOGGER appears 621 times, OS_DEPRECATED 295 times inside class bodies."""
    src = """
class MODEL_API ThermalZone : public HVACComponent {
 public:
    REGISTER_LOGGER("openstudio.model.ThermalZone");
    OS_DEPRECATED(3, 1, 0)
    double realMethod() const;
};
"""
    methods = _parse_header(_write(tmp_path, "T.hpp", src))["ThermalZone"]
    assert set(methods) == {"realMethod"}


def test_access_specifiers_do_not_filter_methods(tmp_path):
    """Access level is deliberately ignored — this map only answers "what does X return".

    search_api lists methods from `dir()` on the live bindings, which expose some protected
    members (`Model#addVersionObject` sits under `protected:` in Model.hpp yet is callable).
    Filtering to `public:` dropped their types without hiding the methods — it cost coverage
    and hid nothing. The `public:`/`protected:` lines themselves must still not parse as
    declarations.
    """
    src = """
class MODEL_API ThermalZone : public HVACComponent {
 public:
    double publicMethod() const;
 protected:
    double protectedMethod() const;
 private:
    double privateMethod() const;
};
"""
    methods = _parse_header(_write(tmp_path, "T.hpp", src))["ThermalZone"]
    assert methods == {
        "publicMethod": "double",
        "protectedMethod": "double",
        "privateMethod": "double",
    }


def test_data_members_are_not_mistaken_for_methods(tmp_path):
    """Access level is unfiltered, so private *data* must still be excluded — it is, by
    having no `(`. Real line from PlanarSurface.hpp: `std::map<UUID, UUID> m_handleMapping;`
    """
    src = """
class MODEL_API Sneaky : public Base {
 private:
    std::map<UUID, UUID> m_handleMapping;
    double m_someValue;
 public:
    double realMethod() const;
};
"""
    methods = _parse_header(_write(tmp_path, "S.hpp", src))["Sneaky"]
    assert set(methods) == {"realMethod"}


def test_skips_constructors_and_destructors(tmp_path):
    src = """
class MODEL_API ThermalZone : public HVACComponent {
 public:
    explicit ThermalZone(const Model& model);
    virtual ~ThermalZone() override = default;
    double realMethod() const;
};
"""
    methods = _parse_header(_write(tmp_path, "T.hpp", src))["ThermalZone"]
    assert "ThermalZone" not in methods
    assert set(methods) == {"realMethod"}


def test_class_declared_with_macro_taking_arguments(tmp_path):
    """Real: TableMultiVariableLookup.hpp:51. Allowing only one *bare* macro before the
    name meant the class never opened and all 99 of its methods were dropped.
    """
    src = """
class OS_DEPRECATED(3, 5, 0) MODEL_API TableMultiVariableLookup : public Curve {
 public:
    static IddObjectType iddObjectType();
    static std::vector<std::string> interpolationMethodValues();
};
"""
    parsed = _parse_header(_write(tmp_path, "T.hpp", src))
    assert "TableMultiVariableLookup" in parsed
    assert parsed["TableMultiVariableLookup"]["iddObjectType"] == "IddObjectType"
    assert parsed["TableMultiVariableLookup"]["interpolationMethodValues"] == "std::vector<std::string>"


def test_all_caps_class_name_still_parses(tmp_path):
    """The macro run is greedy; backtracking must still yield an ALL-CAPS class name."""
    src = "class MODEL_API AVM : public Base {\n public:\n    double x() const;\n};\n"
    assert "AVM" in _parse_header(_write(tmp_path, "A.hpp", src))


def test_forward_declaration_is_not_a_class(tmp_path):
    src = "class ThermalZone_Impl;\nclass MODEL_API ThermalZone : public Base {\n public:\n    double x() const;\n};\n"
    parsed = _parse_header(_write(tmp_path, "F.hpp", src))
    assert "ThermalZone_Impl" not in parsed
    assert parsed["ThermalZone"] == {"x": "double"}


def test_inline_deprecated_prefix_keeps_the_declaration(tmp_path):
    """Real: AirLoopHVACUnitarySystem.hpp. 294 declarations carry this prefix; skipping the
    whole line because it *starts* with a macro discarded every one of them. The methods are
    deprecated, not absent — the bindings still expose them.
    """
    src = """
class MODEL_API AirLoopHVACUnitarySystem : public ZoneHVACComponent {
 public:
    REGISTER_LOGGER("openstudio.model.AirLoopHVACUnitarySystem");
    OS_DEPRECATED(3, 7, 0) double maximumCyclingRate() const;
    OS_DEPRECATED(3, 7, 0) bool isMaximumCyclingRateDefaulted() const;
    OS_DEPRECATED(3, 3, 0) static std::vector<std::string> validHumidityIndicatingTypeValues();
};
"""
    methods = _parse_header(_write(tmp_path, "A.hpp", src))["AirLoopHVACUnitarySystem"]
    assert methods["maximumCyclingRate"] == "double"
    assert methods["isMaximumCyclingRateDefaulted"] == "bool"
    assert methods["validHumidityIndicatingTypeValues"] == "std::vector<std::string>"
    assert "REGISTER_LOGGER" not in methods


def test_uppercase_method_names(tmp_path):
    """Real: UtilityBill.hpp:250 `boost::optional<double> CVRMSE() const;`"""
    src = """
class MODEL_API UtilityBill : public ModelObject {
 public:
    boost::optional<double> CVRMSE() const;
    boost::optional<double> NMBE() const;
};
"""
    methods = _parse_header(_write(tmp_path, "U.hpp", src))["UtilityBill"]
    assert methods["CVRMSE"] == "boost::optional<double>"
    assert map_cpp_type(methods["NMBE"]) == "Float, nil"


def test_method_may_return_its_own_class(tmp_path):
    """`Construction reverseConstruction() const;` — rejecting return-type == class name
    also killed these. Constructors are excluded by name == class, which is sufficient.
    """
    src = """
class MODEL_API Construction : public LayeredConstruction {
 public:
    explicit Construction(const Model& model);
    Construction(const Construction& other) = default;
    Construction reverseConstruction() const;
    static GeneratorPhotovoltaic simple(const Model& model);
};
"""
    methods = _parse_header(_write(tmp_path, "C.hpp", src))["Construction"]
    assert methods["reverseConstruction"] == "Construction"
    assert methods["simple"] == "GeneratorPhotovoltaic"
    assert "Construction" not in methods  # the ctor, not a method


def test_return_type_on_its_own_line(tmp_path):
    """clang-format wraps a long declaration by putting the return type on its own line.

    Real: HeatExchangerDesiccantBalancedFlowPerformanceDataType1.hpp:209-210. The name is
    long enough to trigger the wrap, and long enough that reproducing it inline would blow
    the 120-char limit — hence the constant.
    """
    setter = "setMinimumRegenerationInletAirRelativeHumidityforTemperatureEquation"
    cls = "HeatExchangerDesiccantBalancedFlowPerformanceDataType1"
    src = (
        f"class MODEL_API {cls} : public ModelObject {{\n"
        " public:\n"
        "    bool\n"
        f"      {setter}(double {setter[3:4].lower() + setter[4:]});\n"
        "    double realMethod() const;\n"
        "};\n"
    )
    methods = _parse_header(_write(tmp_path, "H.hpp", src))[cls]
    assert methods[setter] == "bool"
    assert methods["realMethod"] == "double"


def test_doc_comment_continuation_without_a_star(tmp_path):
    """Real: ExteriorLoadInstance.hpp:50-52. The middle line of this doxygen block starts
    with neither `*` nor `//`, and carries a `(` — a line-at-a-time stripper feeds it into
    the continuation buffer and eats the declaration behind it. Block state must be tracked.
    """
    src = """
class MODEL_API ExteriorLoadInstance : public ModelObject {
 public:
    /** Returns the number of instances this space load instance represents.
  This just forwards to multiplier() here but is included for consistency with SpaceLoadInstance**/
    int quantity() const;
};
"""
    methods = _parse_header(_write(tmp_path, "E.hpp", src))["ExteriorLoadInstance"]
    assert methods["quantity"] == "int"
    assert "multiplier" not in methods  # mentioned only inside the comment


def test_openstudio_enum_members(tmp_path):
    """`OPENSTUDIO_ENUM(DefaultScheduleType, ...)` declares a class by macro expansion —
    no `class` line, no member declarations. The generated set is uniform; every row was
    confirmed against live Ruby. Note the macro sits in DefaultScheduleSet.hpp, a file
    named for a different class.
    """
    src = """
class MODEL_API DefaultScheduleSet : public ResourceObject {
 public:
    double realMethod() const;
};
  OPENSTUDIO_ENUM(DefaultScheduleType,
    ((HoursofOperationSchedule)(Hours of Operation Schedule)(1))
    ((NumberofPeopleSchedule)(Number of People Schedule)(2))
  );
"""
    parsed = _parse_header(_write(tmp_path, "D.hpp", src))
    assert parsed["DefaultScheduleSet"] == {"realMethod": "double"}
    enum = parsed["DefaultScheduleType"]
    assert map_cpp_type(enum["enumName"]) == "String"
    assert map_cpp_type(enum["value"]) == "Integer"
    assert map_cpp_type(enum["getValues"]) == "Array<Integer>"


def test_swig_extend_block(tmp_path):
    """`toIdfObject` exists in no .hpp — it is a SWIG %extend in ModelCore.i:
    `IdfObject toIdfObject() const { return *self; }`. The .i body is plain C++.
    """
    src = """
%extend openstudio::model::ModelObject{
  // This really should not be necessary
  IdfObject toIdfObject() const {
    return *self;
  }
};
"""
    methods = _parse_header(_write(tmp_path, "ModelCore.i", src))["ModelObject"]
    assert methods["toIdfObject"] == "IdfObject"


def test_balances_nested_templates(tmp_path):
    """`<[^>]*>` would truncate these; real examples from PlanarSurface / CoilHeating*."""
    src = """
class MODEL_API PlanarSurface : public ParentObject {
 public:
    boost::optional<std::pair<ConstructionBase, int>> constructionWithSearchDistance() const;
    boost::optional<std::tuple<int, CoilCoolingDXMultiSpeed>> stageIndexAndParentCoil() const;
};
"""
    methods = _parse_header(_write(tmp_path, "P.hpp", src))["PlanarSurface"]
    assert methods["constructionWithSearchDistance"] == "boost::optional<std::pair<ConstructionBase, int>>"
    assert map_cpp_type(methods["constructionWithSearchDistance"]) == "Object, nil"


def test_joins_multiline_declarations(tmp_path):
    """Real: Space.hpp `findSurfaces(boost::optional<double> minDegreesFromNorth,` wraps."""
    src = """
class MODEL_API Space : public PlanarSurfaceGroup {
 public:
    std::vector<Surface> findSurfaces(boost::optional<double> minDegreesFromNorth,
                                      boost::optional<double> maxDegreesFromNorth);
    double realMethod() const;
};
"""
    methods = _parse_header(_write(tmp_path, "S.hpp", src))["Space"]
    assert methods["findSurfaces"] == "std::vector<Surface>"
    assert methods["realMethod"] == "double"


def test_overload_first_declaration_wins(tmp_path):
    """Matches _signatures' existing `setdefault` first-occurrence-wins convention."""
    src = """
class MODEL_API Model : public Workspace {
 public:
    bool addObject(const IdfObject& idf);
    boost::optional<double> addObject(int index);
};
"""
    methods = _parse_header(_write(tmp_path, "M.hpp", src))["Model"]
    assert methods["addObject"] == "bool"


def test_default_arguments_do_not_break_parsing(tmp_path):
    src = """
class MODEL_API AdditionalProperties : public ModelObject {
 public:
    void merge(const AdditionalProperties& other, bool overwrite = false);
    std::vector<ModelObject> modelObjects(bool sorted = false) const;
};
"""
    methods = _parse_header(_write(tmp_path, "A.hpp", src))["AdditionalProperties"]
    assert methods["merge"] == "void"
    assert methods["modelObjects"] == "std::vector<ModelObject>"


# --------------------------------------------------------------------------------------
# _build / _locate_header_dir — wiring and graceful degradation
# --------------------------------------------------------------------------------------


def test_build_skips_impl_headers(tmp_path):
    """*_Impl.hpp are detail:: internals, never the public Ruby API."""
    model = tmp_path / "model"
    model.mkdir()
    (model / "ThermalZone.hpp").write_text(
        "class MODEL_API ThermalZone : public HVACComponent {\n public:\n"
        "    double publicApi() const;\n};\n",
        encoding="utf-8",
    )
    (model / "ThermalZone_Impl.hpp").write_text(
        "class MODEL_API ThermalZone_Impl : public HVACComponent_Impl {\n public:\n"
        "    double implDetail() const;\n};\n",
        encoding="utf-8",
    )
    built = _build(tmp_path)
    assert built["ThermalZone"] == {"publicApi": "double"}
    assert "ThermalZone_Impl" not in built


def test_locate_header_dir_honours_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("OSMCP_OPENSTUDIO_INCLUDE", str(tmp_path))
    assert _locate_header_dir() == tmp_path


def test_locate_header_dir_returns_none_when_missing(tmp_path, monkeypatch):
    """No headers is not an error — a wheel-only box simply has no type source."""
    monkeypatch.setenv("OSMCP_OPENSTUDIO_INCLUDE", str(tmp_path / "does-not-exist"))
    assert _locate_header_dir() is None


def test_no_name_based_guessing_remains():
    """Guard the core invariant: types are sourced, never inferred from the method name.

    `_infer_return_type` guessed `ThermalZone#isConditioned -> Boolean` (really an
    OptionalString) and rendered `efficiency`/`nominalCapacity` identically despite
    opposite handling. If it ever returns, this fails.
    """
    from mcp_server.skills.api_reference import _signatures

    assert not hasattr(_signatures, "_infer_return_type")
