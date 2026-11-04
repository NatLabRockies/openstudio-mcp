"""Pure-Python policy for the hvac_only post-check: what counts as HVAC, and the diff.

No openstudio import here so the unit tests can run without the SDK. The SDK-facing
snapshot and restore live in ``hvac_only_guard.py``.

A snapshot is ``{handle: {"type": "OS:Space", "name": "...", "fields": [str, ...]}}``
where ``fields`` is every IDF field after the handle, as strings (blank = empty).
"""
from __future__ import annotations

from typing import Any

# IDD type-name prefixes the vendored measure is allowed to create, delete or change
# when hvac_only=True. Everything else must come back field-for-field identical.
HVAC_TYPE_PREFIXES: tuple[str, ...] = (
    "OS:AirLoopHVAC",
    "OS:Node",
    "OS:Connection",
    "OS:PortList",
    "OS:Connector:",
    "OS:Pipe:",
    "OS:Duct",
    "OS:Coil:",
    "OS:Fan:",
    "OS:Chiller:",
    "OS:Boiler:",
    "OS:CoolingTower:",
    "OS:FluidCooler:",
    "OS:HeatPump:",
    "OS:HeatExchanger:",
    "OS:AirTerminal:",
    "OS:ZoneHVAC:",
    "OS:Controller:",
    "OS:SetpointManager:",
    "OS:AvailabilityManager",
    "OS:Sizing:",
    "OS:EvaporativeCooler:",
    "OS:Humidifier:",
    "OS:District",
    "OS:ModelObjectList",
    "OS:Curve:",
    "OS:Table:",
    "OS:PlantLoop",
    "OS:PlantEquipmentOperation:",
    "OS:Pump:",
    "OS:HeaderedPumps:",
    "OS:ThermalZone",
    "OS:DesignSpecification:OutdoorAir",
    "OS:AdditionalProperties",
    "OS:ThermalStorage:",
    "OS:SolarCollector",
    "OS:Generator:",
    "OS:ElectricLoadCenter:",
    "OS:Refrigeration:",
)

# Service water heating equipment is the one non-HVAC category the library still
# retunes (model_apply_hvac_efficiency_standard runs on the whole model), so the guard
# restores it field-by-field instead of just reporting it.
SWH_TYPE_PREFIXES: tuple[str, ...] = (
    "OS:WaterHeater:",
)

# Objects the standards HVAC builders legitimately add alongside the new system.
# New instances of these are not reported; pre-existing ones must still be identical.
ALLOWED_NEW_PREFIXES: tuple[str, ...] = (
    "OS:Schedule:",
    "OS:ScheduleTypeLimits",
)

# Fields never copied back by the SWH restore: the handle (field 0) and the loop
# connection fields, which legitimately point at new nodes after a swap. The name
# is restored: the efficiency standard appends " 0.801 Therm Eff" to it.
PORT_FIELD_TOKENS: tuple[str, ...] = ("Port", "Node Name")

MAX_REPORTED_CHANGES = 50


def classify(type_name: str, *, swh_handle: bool = False) -> str:
    """Return "hvac", "swh" or "non_hvac" for an IDD type name.

    ``swh_handle`` marks a pump the guard found on a service-water-heating loop;
    pumps are otherwise HVAC.
    """
    if swh_handle:
        return "swh"
    if type_name.startswith(SWH_TYPE_PREFIXES):
        return "swh"
    if type_name.startswith(HVAC_TYPE_PREFIXES):
        return "hvac"
    return "non_hvac"


def is_port_field(field_name: str) -> bool:
    return any(tok in field_name for tok in PORT_FIELD_TOKENS)


def diff_snapshots(
    pre: dict[str, dict[str, Any]],
    post: dict[str, dict[str, Any]],
    *,
    swh_handles: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Non-HVAC objects that were removed, changed or added between two snapshots.

    HVAC-classified objects are ignored entirely. SWH objects are reported like
    non-HVAC ones (the guard restores them first, so a report here means the restore
    could not fix a field). Returns a bounded, deterministic list.
    """
    changes: list[dict[str, Any]] = []
    for handle in sorted(pre):
        entry = pre[handle]
        kind = classify(entry["type"], swh_handle=handle in swh_handles)
        if kind == "hvac":
            continue
        after = post.get(handle)
        if after is None:
            changes.append({
                "change": "removed", "type": entry["type"], "name": entry["name"],
                "handle": handle,
            })
            continue
        pre_fields = entry["fields"]
        post_fields = after["fields"]
        width = max(len(pre_fields), len(post_fields))
        for i in range(width):
            before = pre_fields[i] if i < len(pre_fields) else ""
            now = post_fields[i] if i < len(post_fields) else ""
            if before != now:
                changes.append({
                    "change": "changed", "type": entry["type"], "name": entry["name"],
                    "handle": handle, "field_index": i,
                    "field_name": entry.get("field_names", [])[i]
                    if i < len(entry.get("field_names", [])) else "",
                    "before": before, "after": now,
                })
    for handle in sorted(set(post) - set(pre)):
        entry = post[handle]
        if entry["type"].startswith(ALLOWED_NEW_PREFIXES):
            continue
        if classify(entry["type"]) == "hvac":
            continue
        changes.append({
            "change": "added", "type": entry["type"], "name": entry["name"],
            "handle": handle,
        })
    return changes


def bound_changes(changes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Cap the reported list (rule 16 spirit) and return (shown, total)."""
    return changes[:MAX_REPORTED_CHANGES], len(changes)
