"""Shared helpers for interacting with OpenStudio Python bindings.

Adapted from openstudio-toolkit's helpers.py and _base.py patterns,
but returns plain dicts (no pandas dependency).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import openstudio


def parse_str_list(value: list | str | None) -> list[str] | None:
    """Coerce a JSON-string-encoded list to a Python list.

    Some MCP clients serialize array parameters as JSON strings rather than
    native JSON arrays. This helper handles both cases. Returns None for None
    input (for optional list params).
    """
    if value is None:
        return None
    if isinstance(value, str):
        return json.loads(value)
    return list(value)


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
        try:
            uuid = openstudio.toUUID(handle)
        except Exception:
            return None
        result = getattr(model, method)(uuid)
        return result.get() if result.is_initialized() else None

    return None


def list_all_as_dicts(
    model: openstudio.model.Model,
    getter_name: str,
    extract_fn: Callable,
    detailed: bool = True,
) -> list[dict[str, Any]]:
    """Extract all objects of a type as a sorted list of dicts.

    Args:
        model: The loaded OpenStudio model
        getter_name: Model method name, e.g. "getSpaces"
        extract_fn: Function(model, obj) -> dict; may accept `detailed` kwarg
        detailed: Pass through to extract_fn if it accepts it

    Returns:
        List of dicts, one per object, sorted by 'name' if present.
    """
    import inspect

    getter = getattr(model, getter_name)
    objects = getter()

    # Pass detailed kwarg only if extract_fn accepts it
    sig = inspect.signature(extract_fn)
    if "detailed" in sig.parameters:
        results = [extract_fn(model, obj, detailed=detailed) for obj in objects]
    else:
        results = [extract_fn(model, obj) for obj in objects]

    results.sort(key=lambda d: d.get("name", d.get("Name", "")))
    return results


def list_paginated(
    model: openstudio.model.Model,
    getter_name: str,
    extract_fn: Callable,
    *,
    detailed: bool = True,
    max_results: int | None = None,
    obj_filter_fn: Callable | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Like list_all_as_dicts but with server-side filtering and pagination.

    Filters OS objects BEFORE extraction (efficient — skips extract on
    objects that won't be returned). Sorts by nameString(), truncates
    to max_results, then extracts.

    Args:
        obj_filter_fn: (model, os_object) -> bool, applied before extraction
        max_results: Max items to return. None = unlimited.

    Returns:
        (items, total_available) — items is truncated list, total is pre-truncation count.
    """
    import inspect

    getter = getattr(model, getter_name)
    objects = list(getter())

    if obj_filter_fn:
        objects = [o for o in objects if obj_filter_fn(model, o)]

    total = len(objects)
    objects.sort(key=lambda o: o.nameString() if hasattr(o, "nameString") else "")

    if max_results is not None and total > max_results:
        objects = objects[:max_results]

    sig = inspect.signature(extract_fn)
    if "detailed" in sig.parameters:
        items = [extract_fn(model, obj, detailed=detailed) for obj in objects]
    else:
        items = [extract_fn(model, obj) for obj in objects]

    return items, total


def build_list_response(
    key: str,
    items: list[dict[str, Any]],
    total: int,
    max_results: int | None = None,
) -> dict[str, Any]:
    """Build standardized list response with truncation metadata.

    When truncated, adds total_available and truncated=True so the LLM
    knows to filter or override max_results.
    """
    resp: dict[str, Any] = {"ok": True, "count": len(items), key: items}
    if max_results is not None and total > max_results:
        resp["total_available"] = total
        resp["truncated"] = True
    return resp
