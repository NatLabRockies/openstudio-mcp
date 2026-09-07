"""Unit tests for the C++ header parser behind ``search_api`` return types.

These run without the OpenStudio SDK: every fixture is synthetic header text, so they
execute in the fast ``-m "not integration"`` shard. Each hazard case below is drawn from a
real construct found in the shipped 3.11.0 headers, not invented — the comment on each
says which.

The counterpart integration assertions (real SDK, real values) live in
``test_api_reference.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mcp_server.skills.api_reference._headers import (
    _build,
    _build_by_module,
    _build_typedefs,
    _locate_header_dir,
    _parse_header,
    _parse_typedefs,
    header_module_for,
    map_cpp_type,
)
from mcp_server.skills.api_reference._signatures import _resolve_return_type

pytestmark = pytest.mark.unit


def _write(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _write_tree(base: Path, rel: str, body: str) -> Path:
    """Write a header at a nested relative path, creating parent dirs (for _build)."""
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------
# _resolve_return_type — wrapper annotation rendering
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("annotation", "known_classes", "expected"),
    [
        ("OptionalString", set(), "String, nil"),
        ("StringVector", set(), "Array<String>"),
        ("OptionalStr", set(), "String, nil"),
        ("StrVector", set(), "Array<String>"),
        ("OptionalDouble", set(), "Float, nil"),
        ("DoubleVector", set(), "Array<Float>"),
        ("OptionalFloat", set(), "Float, nil"),
        ("FloatVector", set(), "Array<Float>"),
        ("OptionalInt", set(), "Integer, nil"),
        ("IntVector", set(), "Array<Integer>"),
        ("OptionalBool", set(), "Boolean, nil"),
        ("BoolVector", set(), "Array<Boolean>"),
        ("OptionalThermalZone", {"ThermalZone"}, "ThermalZone, nil"),
        ("ThermalZoneVector", {"ThermalZone"}, "Array<ThermalZone>"),
        ("OptionalUnknown", set(), "Object, nil"),
        ("UnknownVector", set(), "Array"),
    ],
)
def test_wrapper_return_types_resolve_primitives_before_classes(
    annotation, known_classes, expected,
):
    # Regression: OptionalString/StringVector were treated as unknown bound classes instead of String primitives
    """Primitive wrapper names must not be mistaken for unknown bound classes."""
    assert _resolve_return_type(annotation, known_classes) == expected


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
    # Validates: C++ types map to exact Ruby-style renderings (Float, String, nil, Array<X>, Object)
    assert map_cpp_type(cpp) == expected


def test_map_cpp_type_gates_unknown_classes():
    # Validates: header-only classes absent from bindings render as Object, never a name Ruby lacks
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
    # Validates: plain, optional, bool, void and static declarations parse with exact C++ return types
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
    # Regression: CoilCoolingWater.hpp doc comment '<li> bool addToNode(...)' parsed as a real method
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
    # Validates: OS_DEPRECATED is stripped, REGISTER_LOGGER registers logChannel -> Logger, no macro leaks
    """REGISTER_LOGGER appears 621 times, OS_DEPRECATED 295 times inside class bodies.

    OS_DEPRECATED is stripped and the declaration kept; REGISTER_LOGGER expands to
    ``static Logger logChannel();`` — a real static accessor, so it is registered
    literally (deliberate: the utilities classes expose logChannel and it must
    resolve to a type, not `?`).
    """
    src = """
class MODEL_API ThermalZone : public HVACComponent {
 public:
    REGISTER_LOGGER("openstudio.model.ThermalZone");
    OS_DEPRECATED(3, 1, 0)
    double realMethod() const;
};
"""
    methods = _parse_header(_write(tmp_path, "T.hpp", src))["ThermalZone"]
    assert methods["logChannel"] == "Logger"
    assert methods["realMethod"] == "double"


def test_access_specifiers_do_not_filter_methods(tmp_path):
    # Regression: filtering to public: dropped protected Model#addVersionObject type while dir() still lists it
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
    # Validates: private data members (no parens) like m_handleMapping are never parsed as methods
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
    # Validates: constructors and destructors are excluded; only real methods remain
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
    # Regression: TableMultiVariableLookup macro-with-args class line never opened, dropping all 99 methods
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
    # Validates: greedy macro run backtracks so an ALL-CAPS class name (AVM) still parses
    """The macro run is greedy; backtracking must still yield an ALL-CAPS class name."""
    src = "class MODEL_API AVM : public Base {\n public:\n    double x() const;\n};\n"
    assert "AVM" in _parse_header(_write(tmp_path, "A.hpp", src))


def test_forward_declaration_is_not_a_class(tmp_path):
    # Validates: 'class X_Impl;' forward declarations do not create a class entry
    src = "class ThermalZone_Impl;\nclass MODEL_API ThermalZone : public Base {\n public:\n    double x() const;\n};\n"
    parsed = _parse_header(_write(tmp_path, "F.hpp", src))
    assert "ThermalZone_Impl" not in parsed
    assert parsed["ThermalZone"] == {"x": "double"}


def test_inline_deprecated_prefix_keeps_the_declaration(tmp_path):
    # Regression: 294 OS_DEPRECATED-prefixed declarations were skipped entirely though bindings expose them
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
    # Regression: UtilityBill CVRMSE/NMBE (uppercase names) failed to parse
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
    # Regression: Construction#reverseConstruction was rejected because return type equalled class name
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
    # Regression: clang-format wrapped return type on its own line lost the desiccant setter type
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
    # Regression: ExteriorLoadInstance.hpp doxygen line without '*' ate the quantity() declaration behind it
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
    # Validates: OPENSTUDIO_ENUM macro expands to enumName/value/getValues with exact types
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
    # Validates: SWIG %extend methods (toIdfObject in ModelCore.i) parse with their return type
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
    # Regression: '<[^>]*>' truncated nested templates like boost::optional<std::pair<...>>
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
    # Regression: Space#findSurfaces wrapped across lines lost its std::vector<Surface> type
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


def test_overloads_with_different_returns_are_joined(tmp_path):
    # Regression: SqlFile#timeSeries rendered only the first overload (Array<TimeSeries>),
    # hiding the boost::optional<TimeSeries> form that needs .get in Ruby
    src = """
class MODEL_API Model : public Workspace {
 public:
    bool addObject(const IdfObject& idf);
    boost::optional<double> addObject(int index);
    bool addObject(const std::string& text);
};
"""
    methods = _parse_header(_write(tmp_path, "M.hpp", src))["Model"]
    # Declaration order, same raw type recorded once
    assert methods["addObject"] == "bool | boost::optional<double>"
    assert map_cpp_type(methods["addObject"]) == "Boolean | Float, nil"


def test_overloads_with_same_rendered_return_stay_single(tmp_path):
    # Validates: const Foo& vs Foo overloads render one type, not "Foo | Foo"
    src = """
class MODEL_API Surface : public PlanarSurface {
 public:
    std::vector<Surface> splitSurfaceForSubSurfaces();
    const std::vector<Surface>& splitSurfaceForSubSurfaces(double offset);
};
"""
    methods = _parse_header(_write(tmp_path, "S.hpp", src))["Surface"]
    assert map_cpp_type(methods["splitSurfaceForSubSurfaces"]) == "Array<Surface>"


def test_default_arguments_do_not_break_parsing(tmp_path):
    # Validates: default arguments (overwrite = false) do not break parameter parsing
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
    # Validates: *_Impl.hpp detail headers are never parsed into the public type map
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


def test_build_discovers_nested_submodule_headers(tmp_path):
    # Regression: RunControl/AirflowPath in airflow/contam/PrjObjects.hpp missed by glob('model/*.hpp')
    """Real: ``RunControl`` and ``AirflowPath`` are both declared in
    ``airflow/contam/PrjObjects.hpp`` — a nested subdir, and a filename matching
    neither class. The old ``glob("model/*.hpp")`` never saw them.
    """
    src = """
class OS_AIRFLOW_API RunControl : public AirflowObject {
 public:
    int iterationCount() const;
    double convergenceLimit() const;
};
class OS_AIRFLOW_API AirflowPath : public AirflowObject {
 public:
    int nodeCount() const;
};
"""
    _write_tree(tmp_path, "airflow/contam/PrjObjects.hpp", src)
    built = _build(tmp_path)
    assert built["RunControl"] == {"iterationCount": "int", "convergenceLimit": "double"}
    assert built["AirflowPath"] == {"nodeCount": "int"}


def test_build_skips_impl_headers_in_nested_subdirs(tmp_path):
    # Validates: the *_Impl.hpp skip applies in nested subdirs (utilities/sql), not just model/
    """The *_Impl.hpp skip applies everywhere, not just model/."""
    _write_tree(
        tmp_path, "model/ThermalZone.hpp",
        "class MODEL_API ThermalZone {\n public:\n    double publicApi() const;\n};\n",
    )
    _write_tree(
        tmp_path, "utilities/sql/SqlFile.hpp",
        "class OS_UTILITIES_API SqlFile {\n public:\n    std::string path() const;\n};\n",
    )
    _write_tree(
        tmp_path, "utilities/sql/SqlFile_Impl.hpp",
        "class OS_UTILITIES_API SqlFile_Impl {\n public:\n    double implDetail() const;\n};\n",
    )
    built = _build(tmp_path)
    assert built["ThermalZone"] == {"publicApi": "double"}
    assert built["SqlFile"] == {"path": "std::string"}
    assert "SqlFile_Impl" not in built


def test_build_model_precedence_over_submodule(tmp_path):
    # Validates: model/ declaration wins over a same-named submodule declaration
    """First-declaration-wins with model/ parsed first: a method declared in both
    model/ and a submodule keeps the model declaration.
    """
    _write_tree(
        tmp_path, "model/Space.hpp",
        "class MODEL_API Space {\n public:\n    double surfaceArea() const;\n};\n",
    )
    _write_tree(
        tmp_path, "utilities/Space.hpp",
        "class OS_UTILITIES_API Space {\n public:\n    int surfaceArea() const;\n};\n",
    )
    built = _build(tmp_path)
    assert built["Space"] == {"surfaceArea": "double"}


def test_build_parses_extend_in_nested_subdir(tmp_path):
    # Validates: %extend blocks in .i files outside model/ are found by recursion
    """SWIG %extend blocks live in .i files outside model/ too; recursion must find
    them so those methods get types (headers alone don't declare them).
    """
    _write_tree(
        tmp_path, "utilities/sql/SqlFile.i",
        "%extend openstudio::utilities::SqlFile{\n"
        "    bool isOpen() const { return *self; }\n"
        "};\n",
    )
    built = _build(tmp_path)
    assert built["SqlFile"] == {"isOpen": "bool"}


def test_build_hpp_declaration_wins_over_extend(tmp_path):
    # Validates: .hpp declaration beats a same-method %extend regardless of directory
    """A real .hpp declaration beats a %extend of the same method even when the
    %extend sits in model/ — the .hpp-before-.i ordering is global, not per-module.
    """
    _write_tree(
        tmp_path, "model/Space.hpp",
        "class MODEL_API Space {\n public:\n    double surfaceArea() const;\n};\n",
    )
    _write_tree(
        tmp_path, "model/ModelCore.i",
        "%extend openstudio::model::Space{\n"
        "    int surfaceArea() const { return *self; }\n"
        "};\n",
    )
    built = _build(tmp_path)
    assert built["Space"] == {"surfaceArea": "double"}


def test_parses_struct_classes(tmp_path):
    # Regression: 'struct UTILITIES_API IstringFind' was dropped because only 'class' matched
    """Real: `struct UTILITIES_API IstringFind` (Compare.hpp) and
    `struct ISOMODEL_API ISOResults` (SimModel.hpp) — the class regex only matched
    `class` and silently dropped every struct.
    """
    src = """
struct UTILITIES_API IstringFind
{
 public:
    void addTarget(const std::string& target);
    std::string string() const;
};
"""
    methods = _parse_header(_write(tmp_path, "Compare.hpp", src))["IstringFind"]
    assert methods == {"addTarget": "void", "string": "std::string"}


def test_nested_struct_does_not_hijack_enclosing_class(tmp_path):
    # Regression: nested struct CalendarDay stole every following Calendar method
    """Real: Calendar.hpp — `struct CalendarDay` sits inside `class Calendar`; without
    nesting tracking, the struct stole every method that followed it and Calendar got
    none (its logChannel and accessors rendered unknown).
    """
    src = """
class UTILITIES_API Calendar
{
 public:
    REGISTER_LOGGER("utilities.time.Calendar");
    struct CalendarDay
    {
        int dayOfWeek() const;
    };
    void addHoliday(const Date& date, const std::string& name);
    std::string getName(const Date& date) const;
};
"""
    methods = _parse_header(_write(tmp_path, "Calendar.hpp", src))["Calendar"]
    assert methods["logChannel"] == "Logger"
    assert methods["addHoliday"] == "void"
    assert methods["getName"] == "std::string"
    assert "dayOfWeek" not in methods  # belongs to CalendarDay, not Calendar


def test_getters_ending_in_close_brace_do_not_close_the_class(tmp_path):
    # Regression: EpwFile.hpp inline getters ending '};' closed the class early
    """Real: EpwFile.hpp — getters are written `std::string x() const {` / `return …;` /
    `};` — each getter's closing line looks exactly like a class close. Brace-depth
    tracking must keep the class open (the getter close stays at the class depth, the
    class's own `};` drops below it).
    """
    src = """
class UTILITIES_API EpwHoliday
{
 public:
    std::string holidayName() const {
        return m_holidayName;
    };
    std::string holidayDateString() const {
        return m_holidayDateString;
    };
 private:
    std::string m_holidayName;
    std::string m_holidayDateString;
};
"""
    methods = _parse_header(_write(tmp_path, "EpwFile.hpp", src))["EpwHoliday"]
    assert methods == {
        "holidayName": "std::string",
        "holidayDateString": "std::string",
    }


def test_constructor_initializer_list_is_not_a_declaration(tmp_path):
    # Regression: EpwHoliday initializer list parsed as bogus m_holidayName method with type ':'
    """Real: EpwFile.hpp — `EpwHoliday(const std::string& a, const std::string& b)` is
    followed by `: m_holidayName(holidayName), m_holidayDateString(holidayDateString){};`.
    The ctor line ends with `)` so it is flushed as a (skipped) candidate, and the
    initializer list used to parse as a bogus `m_holidayName` method with type `:`.
    """
    src = """
class UTILITIES_API EpwHoliday
{
 public:
    EpwHoliday(const std::string& holidayName, const std::string& holidayDateString)
        : m_holidayName(holidayName), m_holidayDateString(holidayDateString){};
    std::string holidayName() const;
};
"""
    methods = _parse_header(_write(tmp_path, "EpwFile.hpp", src))["EpwHoliday"]
    assert methods == {"holidayName": "std::string"}


def test_build_reads_hxx_declarations(tmp_path):
    # Regression: IddFactory.hxx was never read so IddFactory rendered unknown
    """Real: IddFactory is declared in utilities/idd/IddFactory.hxx — a .hxx, which
    the old glob never read, so IddFactory rendered unknown.
    """
    _write_tree(
        tmp_path, "utilities/idd/IddFactory.hxx",
        "class IddFactory {\n public:\n    static IddFactory& instance();\n};\n",
    )
    built = _build(tmp_path)
    assert built["IddFactory"] == {"instance": "IddFactory"}


def test_build_applies_module_scoped_class_rename(tmp_path):
    # Regression: %rename(ZUnit) openstudio::Unit left ZUnit without Unit methods
    """Real: `%rename(ZUnit) openstudio::Unit;` — the exposed name differs from the
    declared one. The %extend on openstudio::Unit must also surface as ZUnit.
    """
    _write_tree(
        tmp_path, "utilities/units/Unit.hpp",
        "class UTILITIES_API Unit {\n public:\n    double baseUnits() const;\n};\n",
    )
    _write_tree(
        tmp_path, "utilities/UtilitiesUnits.i",
        "%rename(ZUnit) openstudio::Unit;\n",
    )
    built = _build(tmp_path)
    assert built["Unit"]["baseUnits"] == "double"
    assert built["ZUnit"]["baseUnits"] == "double"  # alias carries the methods


def test_build_rename_does_not_cross_modules(tmp_path):
    # Regression: six ForwardTranslator renames bled across modules (Sdd inherited Contam methods)
    """Real: six modules declare a `ForwardTranslator`; each is renamed to its own
    XForwardTranslator. The rename must apply per module — sdd's rename must not
    alias airflow's class, or SddForwardTranslator would inherit Contam's methods.
    """
    _write_tree(
        tmp_path, "airflow/contam/ForwardTranslator.hpp",
        "class AIRFLOW_API ForwardTranslator {\n public:\n    int modelToPrj() const;\n};\n",
    )
    _write_tree(
        tmp_path, "airflow/Airflow.i",
        "%rename(ContamForwardTranslator) openstudio::contam::ForwardTranslator;\n",
    )
    _write_tree(
        tmp_path, "sdd/ForwardTranslator.hpp",
        "class SDD_API ForwardTranslator {\n public:\n    int modelToSDD() const;\n};\n",
    )
    _write_tree(
        tmp_path, "sdd/SDD.i",
        "%rename(SddForwardTranslator) openstudio::sdd::ForwardTranslator;\n",
    )
    built = _build(tmp_path)
    assert built["ContamForwardTranslator"] == {"modelToPrj": "int"}
    assert built["SddForwardTranslator"] == {"modelToSDD": "int"}


def test_build_applies_method_rename(tmp_path):
    # Regression: %rename(toString) OSArgument::print left toString untyped
    """Real: `%rename(toString) openstudio::measure::OSArgument::print;` — a method
    rename: the header declares print, the exposed name is toString.
    """
    _write_tree(
        tmp_path, "measure/OSArgument.hpp",
        "class OS_MEASURE_API OSArgument {\n public:\n    std::string print() const;\n};\n",
    )
    _write_tree(
        tmp_path, "measure/Measure.i",
        "%rename(toString) openstudio::measure::OSArgument::print;\n",
    )
    built = _build(tmp_path)
    assert built["OSArgument"]["print"] == "std::string"
    assert built["OSArgument"]["toString"] == "std::string"


def test_build_applies_inline_swig_class_rename(tmp_path):
    # Regression: inline 'class any' in CommonImport.i renamed to Any surfaced with no methods
    """Real: CommonImport.i defines `class any { ... }` inline and renames it:
    `%rename(Any) boost::any;` — the inline class's methods must surface as Any.
    """
    _write_tree(
        tmp_path, "utilities/core/CommonImport.i",
        "%rename(Any) boost::any;\n"
        "class any {\n"
        " public:\n"
        "    std::string toString();\n"
        "};\n",
    )
    built = _build(tmp_path)
    assert built["Any"] == {"toString": "std::string"}


def test_locate_header_dir_honours_env_override(tmp_path, monkeypatch):
    # Validates: OSMCP_OPENSTUDIO_INCLUDE overrides header directory discovery
    monkeypatch.setenv("OSMCP_OPENSTUDIO_INCLUDE", str(tmp_path))
    assert _locate_header_dir() == tmp_path


def test_locate_header_dir_returns_none_when_missing(tmp_path, monkeypatch):
    # Validates: missing header dir returns None (wheel-only install), not an error
    """No headers is not an error — a wheel-only box simply has no type source."""
    monkeypatch.setenv("OSMCP_OPENSTUDIO_INCLUDE", str(tmp_path / "does-not-exist"))
    assert _locate_header_dir() is None


def test_no_name_based_guessing_remains():
    # Regression: _infer_return_type guessed isConditioned -> Boolean; the name-guesser must stay deleted
    """Guard the core invariant: types are sourced, never inferred from the method name.

    `_infer_return_type` guessed `ThermalZone#isConditioned -> Boolean` (really an
    OptionalString) and rendered `efficiency`/`nominalCapacity` identically despite
    opposite handling. If it ever returns, this fails.
    """
    from mcp_server.skills.api_reference import _signatures

    assert not hasattr(_signatures, "_infer_return_type")


# --------------------------------------------------------------------------------------
# per-module header precedence (class names reused across modules)
# --------------------------------------------------------------------------------------


def test_build_by_module_keeps_same_named_classes_apart(tmp_path):
    # Regression: airflow's ForwardTranslator (alphabetically first) shadowed energyplus's in
    # the merge, so openstudio.energyplus.ForwardTranslator#translateModel rendered Object, nil
    _write_tree(
        tmp_path, "airflow/contam/ForwardTranslator.hpp",
        "class AIRFLOW_API ForwardTranslator {\n public:\n"
        "    boost::optional<IndexModel> translateModel(const Model& model);\n};\n",
    )
    _write_tree(
        tmp_path, "energyplus/ForwardTranslator.hpp",
        "class ENERGYPLUS_API ForwardTranslator {\n public:\n"
        "    Workspace translateModel(const Model& model, ProgressBar* progressBar = nullptr);\n"
        "};\n",
    )
    by_module = _build_by_module(tmp_path)
    assert by_module["energyplus"]["ForwardTranslator"]["translateModel"] == "Workspace"
    assert by_module["airflow"]["ForwardTranslator"]["translateModel"] == (
        "boost::optional<IndexModel>"
    )
    # The merged view still picks airflow (first declaration wins) — which is exactly why
    # _signatures resolves through the bindings module first.
    assert _build(tmp_path)["ForwardTranslator"]["translateModel"] == "boost::optional<IndexModel>"


@pytest.mark.parametrize(
    ("wrapper_stem", "expected"),
    [
        ("openstudioenergyplus", "energyplus"),
        ("openstudiomodelcore", "model"),
        ("openstudiomodelgeometry", "model"),
        ("openstudioutilitiessql", "utilities"),
        ("openstudioairflow", "airflow"),
        ("openstudiogbxml", "gbxml"),
        ("openstudiomeasure", "measure"),
        ("openstudioopenstudio", None),
    ],
)
def test_header_module_for_maps_wrapper_stems(wrapper_stem, expected):
    # Validates: every shipped wrapper stem resolves to its include subdir by longest prefix
    modules = ["model", "utilities", "energyplus", "airflow", "gbxml", "measure", "isomodel"]
    assert header_module_for(wrapper_stem, modules) == expected


# --------------------------------------------------------------------------------------
# typedef / using aliases (OptionalTime, Point3dVector, ...)
# --------------------------------------------------------------------------------------


def test_parse_typedefs_collects_using_and_typedef_forms(tmp_path):
    # Regression: TimeSeries#intervalLength returns the alias OptionalTime, which rendered as
    # Object because no source resolved the alias to boost::optional<Time>
    src = """
namespace openstudio {
using OptionalTime = boost::optional<Time>;
typedef std::vector<Point3d> Point3dVector;
// using OptionalDouble = boost::optional<double>;
/* typedef std::vector<int> IntVector; */
template <class T> using Wrapped = std::vector<T>;
class UTILITIES_API TimeSeries {
 public:
  using OptionalUnsigned = boost::optional<unsigned int>;
};
}
"""
    assert _parse_typedefs(_write(tmp_path, "T.hpp", src)) == {
        "OptionalTime": "boost::optional<Time>",
        "Point3dVector": "std::vector<Point3d>",
        "OptionalUnsigned": "boost::optional<unsigned int>",
    }


_TYPEDEFS = {
    "OptionalTime": "boost::optional<Time>",
    "OptionalUnsigned": "boost::optional<unsigned int>",
    "Point3dVector": "std::vector<Point3d>",
    "Point3dVectorVector": "std::vector<Point3dVector>",
    "OptionalIddObjectTypeVector": "boost::optional<std::vector<IddObjectType>>",
    "Loop": "Loop",
    "string": "std::wstring",
}


@pytest.mark.parametrize(
    ("cpp", "expected"),
    [
        ("OptionalTime", "Time, nil"),
        ("const OptionalTime&", "Time, nil"),
        ("OptionalUnsigned", "Integer, nil"),
        ("Point3dVector", "Array<Point3d>"),
        ("Point3dVectorVector", "Array<Array<Point3d>>"),
        ("OptionalIddObjectTypeVector", "Array<IddObjectType>, nil"),
        ("std::vector<Point3dVector>", "Array<Array<Point3d>>"),
        ("openstudio::OptionalTime", "Time, nil"),  # TimeSeries::intervalLength declares it qualified
        ("openstudio::model::Point3d", "Point3d"),
        ("std::map<std::string, Point3dVector>", "Object"),
        ("std::string", "String"),  # a header aliases `string` to std::wstring; primitives win
        ("boost::optional<std::string>", "String, nil"),
        ("Loop", "Object"),  # self-referential alias must terminate, not recurse forever
        ("NotAnAlias", "Object"),
    ],
)
def test_map_cpp_type_resolves_typedef_aliases(cpp, expected):
    # Regression: OptionalModelObject / Point3dVector / StringVector returns rendered Object
    # (10 bound methods on 3.11.0), hiding the Optional and Array shapes agents must handle
    classes = {"Time", "Point3d", "IddObjectType"}
    assert map_cpp_type(cpp, classes, _TYPEDEFS) == expected


def test_map_cpp_type_without_typedefs_is_unchanged():
    # Validates: callers that pass no alias table keep the pre-alias behaviour (Object)
    assert map_cpp_type("OptionalTime", {"Time"}) == "Object"


def test_build_typedefs_walks_nested_dirs_model_first(tmp_path):
    # Validates: aliases are gathered from every module dir, model/ declaration winning a clash
    _write_tree(tmp_path, "model/ModelObject.hpp", "using OptionalX = boost::optional<ModelX>;\n")
    _write_tree(tmp_path, "utilities/core/Optional.hpp",
                "using OptionalX = boost::optional<UtilX>;\nusing OptionalDouble = boost::optional<double>;\n")
    _write_tree(tmp_path, "utilities/core/Optional_Impl.hpp", "using OptionalHidden = boost::optional<int>;\n")
    assert _build_typedefs(tmp_path) == {
        "OptionalX": "boost::optional<ModelX>",
        "OptionalDouble": "boost::optional<double>",
    }
