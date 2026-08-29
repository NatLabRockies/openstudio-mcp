"""Unit tests for search_api's class collection (no OpenStudio SDK needed).

The class-collection logic in operations.py was factored out of search_api_op so it
can be exercised with fake module objects: identity dedupe of aliased submodules,
per-module attribution, the wrapper-type filter, and the per-module include_base
semantics. Integration behavior against the live SDK lives in test_api_reference.py.
"""
from __future__ import annotations

import sys
import types

import pytest

from mcp_server.skills.api_reference import operations
from mcp_server.skills.api_reference.operations import (
    _collect_classes,
    _decorate,
    _is_wrapper_type,
    _own_methods,
)

pytestmark = pytest.mark.unit


def _mod(**classes) -> object:
    return types.SimpleNamespace(**classes)


# --------------------------------------------------------------------------------------
# _collect_classes — allowlist -> {class_name, module, cls}, deduped by identity
# --------------------------------------------------------------------------------------


def test_collect_classes_dedupes_aliased_modules_by_identity():
    """openstudio.airflow and openstudio.openstudioairflow expose the SAME class
    objects. Identity dedupe must list each class once — under the first module
    enumerated (the canonical short name).
    """
    run_control = type("RunControl", (), {})
    airflow = _mod(RunControl=run_control, IndexModel=type("IndexModel", (), {}))
    airflow_alias = _mod(RunControl=run_control)  # alias module, same objects

    out = _collect_classes([
        ("openstudio.airflow", airflow),
        ("openstudio.openstudioairflow", airflow_alias),
    ])

    assert len(out) == 2
    by_name = {e["class_name"]: e for e in out}
    assert set(by_name) == {"RunControl", "IndexModel"}
    assert by_name["RunControl"]["module"] == "openstudio.airflow"
    assert by_name["IndexModel"]["module"] == "openstudio.airflow"


def test_collect_classes_module_attribution():
    """Each class carries the module it was found in; a class present only in a later
    module keeps that module's label.
    """
    space = type("Space", (), {})
    sql_file = type("SqlFile", (), {})
    out = _collect_classes([
        ("openstudio", _mod(Space=space)),
        ("openstudio.model", _mod(Space=space)),
        ("openstudio.airflow", _mod(SqlFile=sql_file)),
    ])
    by_name = {e["class_name"]: e for e in out}
    assert by_name["Space"]["module"] == "openstudio"  # first module wins for dup ids
    assert by_name["SqlFile"]["module"] == "openstudio.airflow"


def test_collect_classes_skips_wrapper_private_and_iterator_types():
    """Container/optional plumbing must never leak: Optional*, *Vector, *Set/*Map with
    an `object` base, the per-module SwigPyIterator, and underscore-private names.
    Real domain classes sharing a suffix (inheriting a non-object base) are kept.
    """
    class MapBase:
        pass

    class DefaultConstructionSet(MapBase):
        pass

    class GoodMap(MapBase):
        pass

    mod = _mod(
        _Private=type("_Private", (), {}),
        OptionalString=type("OptionalString", (), {}),
        StringVector=type("StringVector", (), {}),
        DefaultConstructionSet=DefaultConstructionSet,
        GoodMap=GoodMap,
        BadSet=type("BadSet", (), {}),          # object base -> wrapper
        BadMap=type("BadMap", (), {}),          # object base -> wrapper
        SwigPyIterator=type("SwigPyIterator", (), {}),
    )
    out = _collect_classes([("openstudio", mod)])
    assert {e["class_name"] for e in out} == {"DefaultConstructionSet", "GoodMap"}


def test_collect_classes_ignores_non_class_attributes():
    """Module-level functions/constants are not classes and must be skipped."""
    mod = _mod(
        the_answer=42,
        helper=lambda: None,
        RunControl=type("RunControl", (), {}),
    )
    out = _collect_classes([("openstudio.airflow", mod)])
    assert [e["class_name"] for e in out] == ["RunControl"]


def test_collect_classes_skips_python_only_lowercase_classes():
    """path / xml_document / xml_node / baseUnitConversionFactor are Python-binding
    internals at the openstudio root. _signatures excludes lowercase names from the
    wrapper parse (no types exist for them); the class list must mirror that rule so
    search_api never returns an untyped class.
    """
    mod = _mod(
        path=type("path", (), {}),
        xml_document=type("xml_document", (), {}),
        RunControl=type("RunControl", (), {}),
    )
    out = _collect_classes([("openstudio", mod)])
    assert [e["class_name"] for e in out] == ["RunControl"]


def test_collect_classes_prefers_wrapper_parsed_name_for_aliases():
    """Legacy aliases: model.DistrictHeating IS model.DistrictHeatingWater (same
    object). Identity dedupe keeps whichever name dir() lists first, but the wrapper
    parse knows only the proxy name — so the preferred (parsed) name must win,
    otherwise the class renders untyped under its alias.
    """
    cls = type("DistrictHeatingWater", (), {})
    mod = _mod(DistrictHeating=cls, DistrictHeatingWater=cls)  # alias, same object
    out = _collect_classes(
        [("openstudio.model", mod)],
        preferred_names={"DistrictHeatingWater"},
    )
    assert len(out) == 1
    assert out[0]["class_name"] == "DistrictHeatingWater"
    assert out[0]["module"] == "openstudio.model"

    # Without preferences, the first-seen name wins (pre-existing behavior).
    out2 = _collect_classes([("openstudio.model", mod)])
    assert out2[0]["class_name"] == "DistrictHeating"


# --------------------------------------------------------------------------------------
# _own_methods — include_base semantics, scoped to model-module classes
# --------------------------------------------------------------------------------------


class _FakeModelObject:
    def name(self):
        return None

    def handle(self):
        return None


class _FakeSpace(_FakeModelObject):
    def name(self):  # overrides the base — must be kept, not subtracted
        return None

    def surfaceArea(self):
        return None


class _FakeSqlFile:  # non-model: does NOT inherit ModelObject
    def name(self):
        return None

    def path(self):
        return None


_BASE_METHODS = {m for m in dir(_FakeModelObject) if not m.startswith("_")}


def test_own_methods_model_class_subtracts_base_unless_include_base():
    """Model-module classes get ModelObject's method set subtracted (default), by
    name — pre-existing search_api behavior, so an override of a base method is
    excluded too. include_base=True keeps everything.
    """
    own = _own_methods(
        _FakeSpace,
        include_base=False,
        is_model_class=True,
        model_base_methods=_BASE_METHODS,
    )
    assert own == {"surfaceArea"}  # `name` (override) and `handle` both subtracted

    with_base = _own_methods(
        _FakeSpace,
        include_base=True,
        is_model_class=True,
        model_base_methods=_BASE_METHODS,
    )
    assert with_base == {"name", "surfaceArea", "handle"}


def test_own_methods_non_model_class_never_subtracts_base():
    """Regression: SqlFile has its own `name` method. Under the old model-only logic it
    would be subtracted as if it were inherited from ModelObject, silently dropping a
    real method from the response.
    """
    own = _own_methods(
        _FakeSqlFile, include_base=False, is_model_class=False, model_base_methods=_BASE_METHODS,
    )
    assert own == {"name", "path"}  # nothing subtracted


def test_own_methods_excludes_swig_data_and_thisown_unconditionally():
    """``dir`` includes SWIG properties/constants and the internal ownership flag.

    ``thisown`` is excluded by name even if a binding version exposes it as callable;
    all other non-callable attributes are excluded from the method buckets.
    """
    class _FakeSwigClass:
        def thisown(self):
            return None

        ExclusiveBound = 1

        @property
        def swig_property(self):
            return "value"

        def realMethod(self):
            return None

    own = _own_methods(
        _FakeSwigClass,
        include_base=False,
        is_model_class=False,
        model_base_methods=set(),
    )
    assert own == {"realMethod"}


def test_decorate_walks_mro_for_inherited_signatures_and_respects_precedence():
    """Parsed signatures come from the first matching class in the live MRO."""
    class _SignatureBase:
        def inherited(self, base_value):
            return None

    class _SignatureMiddle(_SignatureBase):
        def inherited(self, middle_value):
            return None

    class _SignatureLeaf(_SignatureMiddle):
        pass

    sigs = {
        "_SignatureBase": {
            "inherited": {"params": ["baseValue"], "returns": "BaseResult"},
        },
        "_SignatureMiddle": {
            "inherited": {"params": ["middleValue"], "returns": "MiddleResult"},
        },
    }

    assert _decorate("_SignatureLeaf", _SignatureLeaf, ["inherited"], sigs) == [
        "inherited(middleValue) -> MiddleResult",
    ]


def test_decorate_never_returns_a_bare_method_name():
    """Opaque C/SWIG callables still render as an explicit unknown signature."""
    class _OpaqueCallable:
        __signature__ = "unavailable"

        def __call__(self):
            return None

    class _Opaque:
        method = _OpaqueCallable()

    assert _decorate("_Opaque", _Opaque, ["method"], {}) == ["method(...) -> ?"]


def test_search_api_reports_degraded_signature_loading(monkeypatch, capsys):
    """Class/method discovery survives a signature parser failure visibly."""
    class ModelObject:
        def name(self):
            return None

    class FakeWidget(ModelObject):
        def setName(self, name):
            return True

    fake_model = types.ModuleType("openstudio.model")
    fake_model.ModelObject = ModelObject
    fake_model.FakeWidget = FakeWidget
    fake_openstudio = types.ModuleType("openstudio")
    fake_openstudio.model = fake_model
    monkeypatch.setitem(sys.modules, "openstudio", fake_openstudio)

    def fail_signatures():
        raise OSError("signature files unavailable")

    monkeypatch.setattr(operations, "signatures", fail_signatures)

    result = operations.search_api_op("^FakeWidget$")

    assert result["ok"] is True
    assert result["signatures_available"] is False
    assert "signatures are unavailable" in result["warning"]
    assert result["classes"][0]["class_name"] == "FakeWidget"
    assert result["classes"][0]["setters"] == ["setName(name) -> ?"]

    stderr = capsys.readouterr().err
    assert "search_api: failed to load SDK signatures" in stderr
    assert "^FakeWidget$" in stderr
    assert "OSError: signature files unavailable" in stderr


# --------------------------------------------------------------------------------------
# _is_wrapper_type — SwigPyIterator skip (added for the multi-module surface)
# --------------------------------------------------------------------------------------


def test_is_wrapper_type_skips_swig_py_iterator():
    """SwigPyIterator is re-created per module — without the name skip, a pattern like
    "Iterator" would list it once per surfaced namespace (10 times after widening).
    A real *Set domain class (non-object base) is unaffected.
    """
    class ModelParent:
        pass

    assert _is_wrapper_type(type("SwigPyIterator", (), {}))
    assert not _is_wrapper_type(type("DefaultConstructionSet", (ModelParent,), {}))
