"""Search OpenStudio SDK classes and methods by pattern.

Introspects the live openstudio.model module to discover real class names
and method signatures. Primary use case: validating that a method actually
exists before the LLM tries to call it (catches hallucinated methods).
"""
from __future__ import annotations

import re


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
        include_base: If True, include methods inherited from ModelObject.

    Returns:
        {"ok": True, "classes": [{"class_name": ..., "setters": [...],
         "getters": [...], "other": [...]}]}
    """
    try:
        import openstudio  # noqa: F811
        model_module = openstudio.model
    except ImportError:
        return {"ok": False, "error": "openstudio not available"}

    # Find matching classes (skip Vector/Optional wrapper types)
    try:
        cls_re = re.compile(class_pattern, re.IGNORECASE)
    except re.error as e:
        return {"ok": False, "error": f"Invalid class_pattern regex: {e}"}

    all_names = [
        name for name in dir(model_module)
        if not name.startswith("_")
        and isinstance(getattr(model_module, name, None), type)
        and not name.endswith("Vector")
        and not name.endswith("Optional")
        and not name.startswith("Optional")
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

        other = sorted(own_methods - set(setters) - getter_names)

        results.append({
            "class_name": class_name,
            "setters": setters,
            "getters": getters,
            "other": other,
        })

    return {"ok": True, "classes": results, "query": class_pattern}
