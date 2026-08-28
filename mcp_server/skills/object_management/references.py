"""Find every object that references a given object, and everything it references.

Answers "what's the blast radius if I delete this?" — a question
clean_unused_objects can't: it only sweeps objects with zero references, and
says nothing about what currently holds one. delete_object's own error path
(an opaque OpenStudio exception, or occasionally a silent success that leaves
a dangling reference) is the failure mode this exists to prevent.

Built directly on the underlying Workspace/IdfObject API every ModelObject
exposes: `sources()` (objects that point at this one) and `getTarget(i)` per
field index (what this object points at). Verified against the installed
openstudio 3.11.0 bindings — see the module-level note on `_type_label` for
what that API actually returns and why it's used as-is rather than guessed at.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.skills.object_management.operations import _find_object

# Same cap style as gbxml_import/operations.py's MAX_REPORTED_ISSUES — keeps
# the response small on a heavily-shared object (e.g. a construction used by
# every space in a prototype building) without erroring.
MAX_REPORTED_REFERENCES = 50


def _type_label(model: openstudio.model.Model, obj: openstudio.WorkspaceObject) -> str:
    """The object's IDD type, e.g. "OS:Material".

    sources()/getTarget() return a generic WorkspaceObject, which has no
    iddObjectType() of its own (verified against the installed 3.11.0
    bindings — it raises AttributeError) — only the resolved ModelObject
    does, hence the re-lookup through model.getModelObject() below rather
    than calling it on `obj` directly.

    Not the SWIG Python class name (e.g. "StandardOpaqueMaterial") — a
    generic reference has no cheap way to recover that without trying every
    concrete getter in turn, which is exactly the string-based-dispatch
    pattern this project's rules forbid. iddObjectType() is a single,
    always-available SDK method with no per-type branching, at the cost of
    being coarser than the wrapper class name (OpenStudio's IDD genuinely
    unifies some subtypes, e.g. every opaque/no-mass/air-gap material
    variant under plain "OS:Material").
    """
    resolved = model.getModelObject(obj.handle())
    if resolved.is_initialized():
        return resolved.get().iddObjectType().valueDescription()
    return obj.iddObject().name()  # fallback: still correct, just via a different accessor


def _object_summary(model: openstudio.model.Model, obj: openstudio.WorkspaceObject) -> dict[str, Any]:
    opt_name = obj.name()
    return {
        "type": _type_label(model, obj),
        "name": opt_name.get() if opt_name.is_initialized() else None,
        "handle": str(obj.handle()),
    }


def _field_name(obj: openstudio.WorkspaceObject, index: int) -> str:
    field = obj.iddObject().getField(index)
    return field.get().name() if field.is_initialized() else f"field {index}"


def _outbound_references(model: openstudio.model.Model, obj: openstudio.WorkspaceObject) -> list[dict[str, Any]]:
    """Every object `obj` points at, one entry per pointer field."""
    refs: list[dict[str, Any]] = []
    for i in range(obj.numFields()):
        target = obj.getTarget(i)
        if not target.is_initialized():
            continue
        entry = _object_summary(model, target.get())
        entry["via_field"] = _field_name(obj, i)
        refs.append(entry)
    return refs


def _inbound_references(model: openstudio.model.Model, obj: openstudio.WorkspaceObject) -> list[dict[str, Any]]:
    """Every object that points at `obj`, one entry per pointer field that does."""
    target_handle = obj.handle()
    refs: list[dict[str, Any]] = []
    for source in obj.sources():
        for i in range(source.numFields()):
            t = source.getTarget(i)
            if t.is_initialized() and t.get().handle() == target_handle:
                entry = _object_summary(model, source)
                entry["via_field"] = _field_name(source, i)
                refs.append(entry)
    return refs


def find_object_references(
    object_type: str,
    object_name: str | None = None,
    object_handle: str | None = None,
) -> dict[str, Any]:
    """Find what references a model object, and what it references.

    Args:
        object_type: CamelCase, IDD colon, or IDD underscore format
        object_name: Object name (provide name or handle)
        object_handle: Object UUID handle
    """
    try:
        model = get_model()

        if not object_name and not object_handle:
            return {"ok": False, "error": "Provide object_name or object_handle"}

        obj, norm = _find_object(model, object_type, object_name, object_handle)
        if obj is None:
            identifier = object_name or object_handle
            return {"ok": False, "error": f"{norm} '{identifier}' not found"}

        referenced_by = _inbound_references(model, obj)
        references = _outbound_references(model, obj)

        result: dict[str, Any] = {
            "ok": True,
            "type": norm,
            "name": obj.nameString() if hasattr(obj, "nameString") else None,
            "handle": str(obj.handle()),
            "referenced_by_count": len(referenced_by),
            "referenced_by": referenced_by[:MAX_REPORTED_REFERENCES],
            "references_count": len(references),
            "references": references[:MAX_REPORTED_REFERENCES],
        }
        if len(referenced_by) > MAX_REPORTED_REFERENCES:
            result["referenced_by_truncated"] = True
        if len(references) > MAX_REPORTED_REFERENCES:
            result["references_truncated"] = True
        return result

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to find object references: {e}"}
