"""Search OpenStudio SDK classes and methods by pattern.

Introspects the live SDK — the openstudio root namespace, openstudio.model, and the
non-model submodules (see _MODULES) — to discover real class names, then decorates
each method with its full signature (parameter names + return type) parsed from the
SWIG wrapper files. Primary use case: validating that a method actually exists AND
showing the LLM how to call it before it tries (catches hallucinated methods and
guessed argument lists).
"""
from __future__ import annotations

import inspect
import re

from ._signatures import signatures

# SWIG downcast family inherited from ModelObject (to_Space, to_ThermalZone, ...).
# Hundreds of these exist; enumerating them buries the real domain API. Requires the
# underscore so real methods like toIdfObject/toString are NOT matched.
_CAST_RE = re.compile(r"to_[A-Z]")

_MODEL_MODULE = "openstudio.model"

# Namespaces search_api surfaces, in precedence order: (module label reported to
# callers, attribute name on the openstudio root). ``openstudio`` root and
# ``openstudio.model`` are the domain API; the rest are the non-model modules behind
# the plan's ~265 non-model headers (utilities classes — SqlFile, ThreeUserData, … —
# live at the root, not in a utilities submodule). The submodules are exposed as
# attributes of the root (SWIG sets ``model = openstudiomodel`` in __init__.py), not
# as importable dotted paths, so they are resolved via getattr; a missing attribute
# is skipped, so the allowlist can only shrink. Aliases
# (``openstudio.openstudioairflow``) are deliberately not listed — _collect_classes
# dedupes by identity.
_MODULES = (
    ("openstudio", None),
    (_MODEL_MODULE, "model"),
    ("openstudio.airflow", "airflow"),
    ("openstudio.isomodel", "isomodel"),
    ("openstudio.gltf", "gltf"),
    ("openstudio.gbxml", "gbxml"),
    ("openstudio.alfalfa", "alfalfa"),
    ("openstudio.radiance", "radiance"),
    ("openstudio.sdd", "sdd"),
    ("openstudio.energyplus", "energyplus"),
    ("openstudio.osversion", "osversion"),
    ("openstudio.measure", "measure"),
)


def _is_wrapper_type(obj: type) -> bool:
    """True for SWIG STL/optional wrapper types (collection plumbing, not domain API).

    *Vector / Optional* are matched by name. *Set / *Map need a base-class check because
    real domain classes share those suffixes (DefaultConstructionSet, IlluminanceMap):
    SWIG container wrappers inherit `object` directly, domain classes inherit a model
    parent — same `parent == "object"` test the wrapper parser uses. SwigPyIterator is
    the SWIG iterator class, re-created per module — without the name skip it would be
    listed once per surfaced namespace.
    """
    name = obj.__name__
    if name.startswith("Optional") or name.endswith(("Vector", "Optional")):
        return True
    if name == "SwigPyIterator":
        return True
    return name.endswith(("Set", "Map")) and obj.__bases__ == (object,)


def _collect_classes(
    modules: list[tuple[str, object]],
    preferred_names: set[str] | None = None,
) -> list[dict]:
    """Collect ``{class_name, module, cls}`` for every real class in the modules.

    Dedupes by object identity: aliased submodules (``openstudio.airflow`` vs
    ``openstudio.openstudioairflow``) expose the same class objects under two names,
    and identity keeps each listed once — under whichever module was enumerated first.
    When the same object is also exposed under a second name (legacy aliases such as
    ``DistrictHeating == DistrictHeatingWater``), a name in ``preferred_names`` (the
    wrapper-parsed class names) wins, so the class resolves against the signature
    parse instead of rendering untyped under its alias.

    Skips underscore-private names, Python-only lowercase classes (mirrors
    ``_signatures`` — they carry no wrapper types and are binding internals), and
    SWIG container/optional plumbing.
    """
    seen: dict[int, dict] = {}
    for mod_name, mod in modules:
        for name in dir(mod):
            if name.startswith("_") or name[0].islower():
                continue
            obj = getattr(mod, name, None)
            if not isinstance(obj, type) or _is_wrapper_type(obj):
                continue
            key = id(obj)
            existing = seen.get(key)
            if existing is not None:
                if (
                    preferred_names
                    and name in preferred_names
                    and existing["class_name"] not in preferred_names
                ):
                    seen[key] = {"class_name": name, "module": mod_name, "cls": obj}
                continue
            seen[key] = {"class_name": name, "module": mod_name, "cls": obj}
    return list(seen.values())


def _own_methods(
    cls: type,
    *,
    include_base: bool,
    is_model_class: bool,
    model_base_methods: set[str],
) -> set[str]:
    """The class's method names after include_base handling.

    ModelObject's method set is subtracted only for model-module classes: a non-model
    class (SqlFile, WorkflowStepResult) does not inherit ModelObject, and subtracting
    it would wrongly drop same-named methods like ``name``. ``dir`` also exposes SWIG
    properties, constants, and the internal ownership flag ``thisown``; only callable
    public attributes are methods, and ``thisown`` is never part of the public API.
    """
    all_methods = {
        name
        for name in dir(cls)
        if not name.startswith("_")
        and name != "thisown"
        and callable(getattr(cls, name, None))
    }
    if include_base or not is_model_class:
        return all_methods
    return all_methods - model_base_methods


def _decorate(class_name: str, cls: type, names: list[str], sigs: dict) -> list[str]:
    """Render each method name as ``method(params) -> ReturnType``.

    Uses the parsed wrapper signature for the class or the first matching class in its
    live MRO; falls back to ``inspect.signature`` for parameter names when a method
    isn't in the parse (e.g. C-level), with ``-> ?`` for the unknown return. If even
    that fails, renders an explicit unknown-parameter signature rather than a bare name.
    """
    class_sigs = sigs.get(class_name, {})
    out = []
    for name in names:
        # ``dir(cls)`` includes inherited methods, while ``sigs`` stores each method
        # under the class whose wrapper declares it. Keep the explicit class-name lookup
        # first for parsed aliases, then follow Python's normal MRO for inherited APIs.
        info = class_sigs.get(name)
        if info is None:
            for base in cls.__mro__:
                info = sigs.get(base.__name__, {}).get(name)
                if info is not None:
                    break
        if info is not None:
            out.append(f"{name}({', '.join(info['params'])}) -> {info['returns']}")
            continue
        try:
            params = [p for p in inspect.signature(getattr(cls, name)).parameters if p != "self"]
            out.append(f"{name}({', '.join(params)}) -> ?")
        except (ValueError, TypeError):
            out.append(f"{name}(...) -> ?")
    return out


def search_api_op(
    class_pattern: str,
    method_pattern: str | None = None,
    max_classes: int = 10,
    include_base: bool = False,
) -> dict:
    """Search OpenStudio SDK classes and their methods.

    The class list comes from an explicit module allowlist (see _MODULES) rather than
    ``dir(openstudio.model)`` alone: reporting measures reach SqlFile, the airflow
    module has RunControl/IndexModel, isomodel has UserModel — none of which
    ``dir(model)`` exposes. Aliased submodules are deduped by identity.

    Args:
        class_pattern: Regex pattern to match class names (case-insensitive).
        method_pattern: Optional regex to filter methods (case-insensitive).
        max_classes: Max number of classes to return (default 10).
        include_base: If True, include methods inherited from ModelObject. Only
            model-module classes inherit it — non-model classes are unaffected. The
            inherited to_<Class>() downcast family is collapsed into one summary line
            (unless method_pattern explicitly targets casts).

    Returns:
        {"ok": True, "classes": [{"class_name": ..., "module": ..., "setters": [...],
         "getters": [...], "other": [...]}], "query": ...} where each
        setter/getter/other entry is a signature string, e.g.
        "setSurfaceType(surfaceType) -> Boolean", and module names the namespace
        the class lives in ("openstudio", "openstudio.model", "openstudio.airflow",
        ...).
    """
    try:
        import openstudio
        model_module = openstudio.model
    except ImportError:
        return {"ok": False, "error": "openstudio not available"}

    # Find matching classes (skip SWIG container/optional wrapper types — see _is_wrapper_type)
    try:
        cls_re = re.compile(class_pattern, re.IGNORECASE)
    except re.error as e:
        return {"ok": False, "error": f"Invalid class_pattern regex: {e}"}

    # Resolve the allowlist to module objects. The submodules are attributes of the
    # openstudio root rather than importable dotted paths; a missing attribute
    # (module absent from this install) is skipped — the allowlist can only shrink.
    modules = []
    for mod_label, attr in _MODULES:
        mod = openstudio if attr is None else getattr(openstudio, attr, None)
        if mod is None:
            continue
        modules.append((mod_label, mod))

    # Parsed wrapper signatures (params + return types). Degrade to inspected or
    # explicitly unknown signatures if the parse is unavailable, never bare names.
    try:
        sigs = signatures()
        sig_ok = True
    except Exception:
        sigs = {}
        sig_ok = False

    matched = [
        entry for entry in _collect_classes(
            modules,
            preferred_names=set(sigs) if sig_ok else None,
        )
        if cls_re.search(entry["class_name"])
    ]
    matched = matched[:max_classes]

    if not matched:
        return {"ok": True, "classes": [], "query": class_pattern}

    # ModelObject's method set is subtracted only from classes that inherit it
    # (model-module classes); non-model classes keep same-named methods.
    model_base_methods: set[str] = set()
    if not include_base:
        base_cls = getattr(model_module, "ModelObject", None)
        if base_cls:
            model_base_methods = {
                m for m in dir(base_cls) if not m.startswith("_")
            }

    # Compile method filter
    method_re = None
    if method_pattern:
        try:
            method_re = re.compile(method_pattern, re.IGNORECASE)
        except re.error as e:
            return {"ok": False, "error": f"Invalid method_pattern regex: {e}"}

    results = []
    for entry in matched:
        cls = entry["cls"]
        class_name = entry["class_name"]

        # Exclude base methods unless include_base (model-module classes only)
        own_methods = _own_methods(
            cls,
            include_base=include_base,
            is_model_class=entry["module"] == _MODEL_MODULE,
            model_base_methods=model_base_methods,
        )

        # Apply method filter
        if method_re:
            own_methods = {m for m in own_methods if method_re.search(m)}

        # Categorize
        setters = sorted(m for m in own_methods if m.startswith("set"))

        # Getters = methods with a corresponding setter (setFoo -> foo)
        getter_names = set()
        for s in setters:
            getter = s[3:4].lower() + s[4:]
            if getter in own_methods:
                getter_names.add(getter)
        getters = sorted(getter_names)

        other_names = own_methods - set(setters) - getter_names

        # Collapse the to_<Class>() downcast family into one summary line so the
        # response teaches the cast pattern without dumping ~400 inherited methods.
        # Skip the collapse when method_pattern is set: an explicit cast search
        # (e.g. method_pattern="to_Space") should list its matches literally.
        casts: set[str] = set()
        if method_re is None:
            casts = {m for m in other_names if _CAST_RE.match(m)}
        other = sorted(other_names - casts)

        setters = _decorate(class_name, cls, setters, sigs)
        getters = _decorate(class_name, cls, getters, sigs)
        other = _decorate(class_name, cls, other, sigs)

        if casts:
            sample = ", ".join(sorted(casts)[:3])
            other.append(
                f"to_<TargetClass>() -> Optional  # {len(casts)} downcast methods "
                f"(e.g. {sample}); call to_<TargetClass>() to test/cast an object "
                f"to a concrete type",
            )

        results.append({
            "class_name": class_name,
            "module": entry["module"],
            "setters": setters,
            "getters": getters,
            "other": other,
        })

    return {"ok": True, "classes": results, "query": class_pattern}


def search_wiring_patterns_op(
    pattern: str,
    max_results: int = 3,
) -> dict:
    """Search HVAC wiring recipes by component type or keyword.

    Args:
        pattern: Keyword or component type to search for (case-insensitive).
            Examples: "four pipe beam", "DOAS", "boiler", "fan coil",
            "plant loop", "VRF", "PTAC", "unitary"
        max_results: Max recipes to return (default 3).

    Returns:
        {"ok": True, "recipes": [...], "available_recipes": [...]}
    """
    from .wiring_recipes import RECIPES

    pattern_lower = pattern.lower()
    tokens = set(re.findall(r"[a-z0-9]+", pattern_lower))

    # Score each recipe by keyword overlap
    scored = []
    for key, recipe in RECIPES.items():
        searchable = " ".join([
            key,
            recipe.get("component_type", ""),
            " ".join(recipe.get("connections", [])),
            recipe.get("notes", ""),
        ]).lower()
        # Count matching tokens
        score = sum(1 for t in tokens if t in searchable)
        if score > 0:
            scored.append((score, key, recipe))

    scored.sort(key=lambda x: -x[0])
    matches = scored[:max_results]

    results = []
    for _, key, recipe in matches:
        results.append({
            "recipe_id": key,
            "component_type": recipe["component_type"],
            "connections": recipe["connections"],
            "ruby": recipe["ruby"],
            "notes": recipe["notes"],
            "source": recipe.get("source", ""),
        })

    return {
        "ok": True,
        "recipes": results,
        "available_recipes": sorted(RECIPES.keys()),
    }
