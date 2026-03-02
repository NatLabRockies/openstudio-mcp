"""Shared helpers for interacting with OpenStudio Python bindings.

Adapted from openstudio-toolkit's helpers.py and _base.py patterns,
but returns plain dicts (no pandas dependency).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import openstudio


def optional_name(os_optional) -> str | None:
    """Extract name string from an OpenStudio Optional, or None.

    Handles the common pattern:
        obj.someRelationship().get().name().get()
    safely, returning None if any step is uninitialized.
    """
    try:
        if os_optional.is_initialized():
            obj = os_optional.get()
            if hasattr(obj, "name") and obj.name().is_initialized():
                return obj.name().get()
    except Exception:
        pass
    return None


def fetch_object(
    model: openstudio.model.Model,
    object_type: str,
    name: str | None = None,
    handle: str | None = None,
) -> Any:
    """Fetch a single OpenStudio object by name or handle.

    Args:
        model: The loaded OpenStudio model
        object_type: Class name, e.g. "Space", "ThermalZone"
        name: Object name (mutually exclusive with handle)
        handle: Object UUID handle (mutually exclusive with name)

    Returns:
        The OpenStudio object, or None if not found.
    """
    if name is not None:
        method = f"get{object_type}ByName"
        if not hasattr(model, method):
            return None
        result = getattr(model, method)(name)
        return result.get() if result.is_initialized() else None

    if handle is not None:
        method = f"get{object_type}"
        if not hasattr(model, method):
            return None
        result = getattr(model, method)(openstudio.toUUID(handle))
        return result.get() if result.is_initialized() else None

    return None


def list_all_as_dicts(
    model: openstudio.model.Model,
    getter_name: str,
    extract_fn: Callable,
) -> list[dict[str, Any]]:
    """Extract all objects of a type as a sorted list of dicts.

    Args:
        model: The loaded OpenStudio model
        getter_name: Model method name, e.g. "getSpaces"
        extract_fn: Function(model, obj) -> dict

    Returns:
        List of dicts, one per object, sorted by 'name' if present.
    """
    getter = getattr(model, getter_name)
    objects = getter()
    results = [extract_fn(model, obj) for obj in objects]
    results.sort(key=lambda d: d.get("name", d.get("Name", "")))
    return results
