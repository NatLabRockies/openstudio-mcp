"""SDK-facing half of the hvac_only post-check: snapshot, SWH restore, remaining diff.

The vendored create_typical measure gates every non-HVAC step it can
(see measures/create_typical_building_from_model/VENDORED.md). One library call it
cannot gate, model_apply_hvac_efficiency_standard, runs on the whole model and also
retunes retained service-water-heating equipment. This module copies those fields
back from a pre-measure snapshot, then diffs every other non-HVAC object so the
response can show what still differs (expected: nothing).

Handles survive the measure round-trip (the OSM stores them), so objects are
matched by handle. Classification lives in hvac_only_policy.py (pure Python).
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.skills.comstock.hvac_only_policy import (
    bound_changes,
    classify,
    diff_snapshots,
    is_port_field,
)

_MAX_NAMES = 10


def swh_pump_handles(model: openstudio.model.Model) -> frozenset[str]:
    """Handles of pumps on plant loops whose demand side serves water use (SWH loops).

    Pumps are HVAC everywhere else; these are the ones the restore must cover.
    """
    handles: set[str] = set()
    for loop in model.getPlantLoops():
        demand = list(loop.demandComponents())
        if not any(c.to_WaterUseConnections().is_initialized() for c in demand):
            continue
        for comp in list(loop.supplyComponents()) + demand:
            if (comp.to_PumpVariableSpeed().is_initialized()
                    or comp.to_PumpConstantSpeed().is_initialized()
                    or comp.to_HeaderedPumpsVariableSpeed().is_initialized()
                    or comp.to_HeaderedPumpsConstantSpeed().is_initialized()):
                handles.add(str(comp.handle()))
    return frozenset(handles)


def snapshot_fields(model: openstudio.model.Model) -> dict[str, dict[str, Any]]:
    """Every model object as {handle: {type, name, fields, field_names}}.

    ``fields[i]`` is IDF field ``i + 1`` (the handle at index 0 is skipped) as a
    string, blank when unset. Cheap: one pass, strings only, no cloning.
    """
    snap: dict[str, dict[str, Any]] = {}
    for obj in model.getModelObjects():
        idd = obj.iddObject()
        fields: list[str] = []
        names: list[str] = []
        for i in range(1, obj.numFields()):
            value = obj.getString(i, False, True)
            fields.append(value.get() if value.is_initialized() else "")
            field = idd.getField(i)
            names.append(field.get().name() if field.is_initialized() else "")
        name = obj.name()
        snap[str(obj.handle())] = {
            "type": idd.name(),
            "name": name.get() if name.is_initialized() else "",
            "fields": fields,
            "field_names": names,
        }
    return snap


def restore_swh_equipment(
    pre: dict[str, dict[str, Any]],
    model: openstudio.model.Model,
    swh_handles: frozenset[str],
) -> list[dict[str, Any]]:
    """Copy pre-measure field values back onto surviving SWH equipment.

    Copies every field including the name (the efficiency standard appends
    " 0.801 Therm Eff" to a water heater's name on each pass, and WaterHeater:Sizing
    reports that rename through its reference field). Skips loop connection
    (port/node) fields, which may point at new nodes after the swap. Returns one
    ``restored`` entry per category with the object names (capped) and the field
    names that were put back.
    """
    objects: list[str] = []
    fields_touched: list[str] = []
    for obj in model.getModelObjects():
        handle = str(obj.handle())
        entry = pre.get(handle)
        if entry is None:
            continue
        if classify(entry["type"], swh_handle=handle in swh_handles) != "swh":
            continue
        changed: list[str] = []
        for i in range(1, obj.numFields()):
            idx = i - 1
            if idx >= len(entry["fields"]):
                break
            field_name = entry["field_names"][idx]
            if is_port_field(field_name):
                continue
            current = obj.getString(i, False, True)
            current_value = current.get() if current.is_initialized() else ""
            if current_value == entry["fields"][idx]:
                continue
            if obj.setString(i, entry["fields"][idx]):
                changed.append(field_name)
        if changed:
            objects.append(entry["name"] or entry["type"])
            for f in changed:
                if f not in fields_touched:
                    fields_touched.append(f)
    if not objects:
        return []
    return [{
        "category": "swh_equipment",
        "count": len(objects),
        "objects": objects[:_MAX_NAMES],
        "fields": fields_touched,
    }]


def remaining_changes(
    pre: dict[str, dict[str, Any]],
    model: openstudio.model.Model,
    swh_handles: frozenset[str],
) -> tuple[list[dict[str, Any]], int]:
    """Non-HVAC objects that still differ from the snapshot: (shown, total)."""
    post = snapshot_fields(model)
    return bound_changes(diff_snapshots(pre, post, swh_handles=swh_handles))
