"""Search OpenStudio SDK classes and methods by pattern.

Introspects the live openstudio.model module to discover real class names, then
decorates each method with its full signature (parameter names + return type) parsed
from the SWIG wrapper files. Primary use case: validating that a method actually exists
AND showing the LLM how to call it before it tries (catches hallucinated methods and
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


def _is_wrapper_type(obj: type) -> bool:
    """True for SWIG STL/optional wrapper types (collection plumbing, not domain API).

    *Vector / Optional* are matched by name. *Set / *Map need a base-class check because
    real domain classes share those suffixes (DefaultConstructionSet, IlluminanceMap):
    SWIG container wrappers inherit `object` directly, domain classes inherit a model
    parent — same `parent == "object"` test the wrapper parser uses.
    """
    name = obj.__name__
    if name.startswith("Optional") or name.endswith(("Vector", "Optional")):
        return True
    return name.endswith(("Set", "Map")) and obj.__bases__ == (object,)


def _decorate(class_name: str, cls: type, names: list[str], sigs: dict) -> list[str]:
    """Render each method name as ``method(params) -> ReturnType``.

    Uses the parsed wrapper signatures first; falls back to ``inspect.signature`` for
    parameter names when a method isn't in the parse (e.g. C-level), with ``-> ?`` for
    the unknown return; falls back to the bare name if even that fails.
    """
    class_sigs = sigs.get(class_name, {})
    out = []
    for name in names:
        info = class_sigs.get(name)
        if info is not None:
            out.append(f"{name}({', '.join(info['params'])}) -> {info['returns']}")
            continue
        try:
            params = [p for p in inspect.signature(getattr(cls, name)).parameters if p != "self"]
            out.append(f"{name}({', '.join(params)}) -> ?")
        except (ValueError, TypeError):
            out.append(name)
    return out


def search_api_op(
    class_pattern: str,
    method_pattern: str | None = None,
    max_classes: int = 10,
    include_base: bool = False,
) -> dict:
    """Search openstudio.model classes and their methods.

    Args:
        class_pattern: Regex pattern to match class names (case-insensitive).
        method_pattern: Optional regex to filter methods (case-insensitive).
        max_classes: Max number of classes to return (default 10).
        include_base: If True, include methods inherited from ModelObject. The
            inherited to_<Class>() downcast family is collapsed into one summary
            line (unless method_pattern explicitly targets casts).

    Returns:
        {"ok": True, "classes": [{"class_name": ..., "setters": [...],
         "getters": [...], "other": [...]}]} where each setter/getter/other entry
        is a signature string, e.g. "setSurfaceType(surfaceType) -> Boolean".
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

    all_names = [
        name for name in dir(model_module)
        if not name.startswith("_")
        and isinstance(getattr(model_module, name, None), type)
        and not _is_wrapper_type(getattr(model_module, name))
    ]

    matched = [n for n in all_names if cls_re.search(n)]
    matched = matched[:max_classes]

    if not matched:
        return {"ok": True, "classes": [], "query": class_pattern}

    # Build base method set for exclusion
    base_methods: set[str] = set()
    if not include_base:
        base_cls = getattr(model_module, "ModelObject", None)
        if base_cls:
            base_methods = {
                m for m in dir(base_cls) if not m.startswith("_")
            }

    # Compile method filter
    method_re = None
    if method_pattern:
        try:
            method_re = re.compile(method_pattern, re.IGNORECASE)
        except re.error as e:
            return {"ok": False, "error": f"Invalid method_pattern regex: {e}"}

    # Parsed wrapper signatures (params + return types). Degrade to bare names if the
    # parse is unavailable so search_api can never be broken by a SWIG/parser surprise.
    try:
        sigs = signatures()
        sig_ok = True
    except Exception:
        sigs = {}
        sig_ok = False

    results = []
    for class_name in matched:
        cls = getattr(model_module, class_name)
        all_methods = {m for m in dir(cls) if not m.startswith("_")}

        # Exclude base methods unless include_base
        own_methods = all_methods if include_base else all_methods - base_methods

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

        if sig_ok:
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
