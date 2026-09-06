"""Create and remove setpoint managers on loop nodes (follow-up to #148).

Setpoint managers (SPMs) were only ever created inside whole-system builders;
removing or replacing a supply-branch component (#148) can move one, but
nothing could put a new one on a chosen node. These two tools close that gap.

SDK facts this rests on (dev/issue149-probes/probe_spm_collision.py, OpenStudio
3.11.0):
- SetpointManager.addToNode(node) returns True and, when `node` already carries
  an SPM with the same controlVariable(), silently DELETES that SPM from the
  model. There is no return-value signal, so the collision guard lives here.
- Different control variables coexist on one node (Temperature + HumidityRatio).
- The SDK does validate loop type: an air-loop-only type (Warmest, Coldest,
  SingleZoneReheat) returns False on a plant node and attaches nothing.
- spm.remove() deletes just that SPM; other SPMs on the node stay.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object
from mcp_server.skills.component_properties.operations import SPM_TYPES
from mcp_server.skills.loop_operations.air_loop_supply import _air_ports, _find_on_supply

# The 7 types get_/set_setpoint_manager_properties already understand. A new
# type needs a constructor branch in _construct_spm AND a lookup branch in
# _find_spm (see .claude/rules/component-types.md).
SPM_CONSTRUCTOR_TYPES: tuple[str, ...] = tuple(SPM_TYPES.keys())
AIR_LOOP_ONLY_TYPES = frozenset({
    "SetpointManagerSingleZoneReheat", "SetpointManagerWarmest", "SetpointManagerColdest",
})
NODE_CHOICES = ("supply_outlet", "supply_inlet", "mixed_air")


# ── lookup ───────────────────────────────────────────────────────────────

def _find_spm(model, name: str):
    """(spm, spm_type) for the named SPM across the 7 supported types, else None.

    Explicit calls, one per type (CLAUDE.md rule 12: no getattr dispatch).
    """
    r = model.getSetpointManagerSingleZoneReheatByName(name)
    if r.is_initialized():
        return r.get(), "SetpointManagerSingleZoneReheat"
    r = model.getSetpointManagerScheduledByName(name)
    if r.is_initialized():
        return r.get(), "SetpointManagerScheduled"
    r = model.getSetpointManagerWarmestByName(name)
    if r.is_initialized():
        return r.get(), "SetpointManagerWarmest"
    r = model.getSetpointManagerColdestByName(name)
    if r.is_initialized():
        return r.get(), "SetpointManagerColdest"
    r = model.getSetpointManagerFollowOutdoorAirTemperatureByName(name)
    if r.is_initialized():
        return r.get(), "SetpointManagerFollowOutdoorAirTemperature"
    r = model.getSetpointManagerOutdoorAirResetByName(name)
    if r.is_initialized():
        return r.get(), "SetpointManagerOutdoorAirReset"
    r = model.getSetpointManagerScheduledDualSetpointByName(name)
    if r.is_initialized():
        return r.get(), "SetpointManagerScheduledDualSetpoint"
    return None


def _resolve_loop(model, air_loop_name: str | None, plant_loop_name: str | None):
    """(loop, "air"|"plant", None) or (None, None, error)."""
    if (air_loop_name is None) == (plant_loop_name is None):
        return None, None, "Pass exactly one of air_loop_name or plant_loop_name"
    if air_loop_name is not None:
        loop = fetch_object(model, "AirLoopHVAC", name=air_loop_name)
        if loop is None:
            return None, None, f"Air loop '{air_loop_name}' not found"
        return loop, "air", None
    loop = fetch_object(model, "PlantLoop", name=plant_loop_name)
    if loop is None:
        return None, None, f"Plant loop '{plant_loop_name}' not found"
    return loop, "plant", None


def _resolve_node(loop, kind: str, node: str, after_component: str | None):
    """(Node, None) or (None, error) for the placement the caller asked for."""
    if after_component is not None:
        comp = _find_on_supply(loop, after_component)
        if comp is None:
            return None, f"'{after_component}' not found on the supply side of '{loop.nameString()}'"
        ports = _air_ports(comp)
        if ports is None or ports[2] is None:
            return None, f"'{after_component}' has no outlet node to place a setpoint manager on"
        return ports[2], None
    if node == "supply_outlet":
        return loop.supplyOutletNode(), None
    if node == "supply_inlet":
        return loop.supplyInletNode(), None
    if node == "mixed_air":
        if kind != "air":
            return None, "node='mixed_air' only exists on an air loop"
        oa = loop.airLoopHVACOutdoorAirSystem()
        if not oa.is_initialized():
            return None, f"Air loop '{loop.nameString()}' has no outdoor air system, so no mixed-air node"
        mixed = oa.get().mixedAirModelObject()
        if not mixed.is_initialized() or not mixed.get().to_Node().is_initialized():
            return None, "Outdoor air system has no mixed-air node"
        return mixed.get().to_Node().get(), None
    return None, f"Unknown node '{node}'. Valid: {list(NODE_CHOICES)} or after_component=<name>"


# ── construction ─────────────────────────────────────────────────────────

def _schedule(model, param: str, schedule_name: str | None, spm_type: str):
    """(schedule, None) or (None, error) — required-arg check plus lookup."""
    if schedule_name is None:
        return None, f"{spm_type} requires {param}"
    sched = fetch_object(model, "Schedule", name=schedule_name)
    if sched is None:
        return None, f"Schedule '{schedule_name}' not found"
    return sched, None


def _construct_spm(model, spm_type: str, loop, kind: str, *, schedule_name, cooling_schedule_name,
                   heating_schedule_name, control_zone_name, control_variable):
    """(spm, None) or (None, error). Explicit branches per type (rule 12)."""
    if spm_type == "SetpointManagerScheduled":
        sched, err = _schedule(model, "schedule_name", schedule_name, spm_type)
        if err:
            return None, err
        # Both constructor forms throw (SystemError) when the schedule's type limits do not
        # fit the control variable, or the variable is unknown — and the half-built SPM is
        # left in the model (probe_spm_ctor_orphan.py). Snapshot, then roll back on failure.
        before = {o.handle() for o in model.getSetpointManagerScheduleds()}
        try:
            if control_variable is None:
                spm = openstudio.model.SetpointManagerScheduled(model, sched)  # (model, schedule)
            else:
                spm = openstudio.model.SetpointManagerScheduled(model, control_variable, sched)
        except Exception:
            for o in model.getSetpointManagerScheduleds():
                if o.handle() not in before:
                    o.remove()
            cv = control_variable or "Temperature"
            return None, (f"Schedule '{schedule_name}' has type limits incompatible with control "
                          f"variable '{cv}' (or '{cv}' is not a valid control variable for {spm_type})")
        return spm, None
    if spm_type == "SetpointManagerScheduledDualSetpoint":
        high, err = _schedule(model, "cooling_schedule_name", cooling_schedule_name, spm_type)
        if err:
            return None, err
        low, err = _schedule(model, "heating_schedule_name", heating_schedule_name, spm_type)
        if err:
            return None, err
        spm = openstudio.model.SetpointManagerScheduledDualSetpoint(model)
        # Setters return False (and leave the slot empty) for non-temperature type limits
        if not spm.setHighSetpointSchedule(high):   # cooling side
            spm.remove()
            return None, f"Schedule '{cooling_schedule_name}' is not a temperature schedule (cooling_schedule_name)"
        if not spm.setLowSetpointSchedule(low):     # heating side
            spm.remove()
            return None, f"Schedule '{heating_schedule_name}' is not a temperature schedule (heating_schedule_name)"
        return spm, None
    if spm_type == "SetpointManagerSingleZoneReheat":
        if control_zone_name is None:
            return None, f"{spm_type} requires control_zone_name"
        zone = fetch_object(model, "ThermalZone", name=control_zone_name)
        if zone is None:
            return None, f"Thermal zone '{control_zone_name}' not found"
        if kind != "air" or not any(z.handle() == zone.handle() for z in loop.thermalZones()):
            return None, f"Zone '{control_zone_name}' is not served by air loop '{loop.nameString()}'"
        # The control zone is applied AFTER addToNode (see _apply_control_zone): attaching
        # resets it to the loop's first zone (probe_szr_control_zone.py)
        return openstudio.model.SetpointManagerSingleZoneReheat(model), None
    if control_variable is not None:
        return None, f"control_variable is only settable on SetpointManagerScheduled, not {spm_type}"
    if spm_type == "SetpointManagerWarmest":
        return openstudio.model.SetpointManagerWarmest(model), None
    if spm_type == "SetpointManagerColdest":
        return openstudio.model.SetpointManagerColdest(model), None
    if spm_type == "SetpointManagerFollowOutdoorAirTemperature":
        return openstudio.model.SetpointManagerFollowOutdoorAirTemperature(model), None
    if spm_type == "SetpointManagerOutdoorAirReset":
        return openstudio.model.SetpointManagerOutdoorAirReset(model), None
    return None, f"Unknown spm_type '{spm_type}'. Valid: {list(SPM_CONSTRUCTOR_TYPES)}"


def _apply_control_zone(spm, model, control_zone_name: str) -> tuple[str | None, str | None]:
    """(zone name, None) or (None, error) — set the SingleZoneReheat control zone post-attach.

    SetpointManagerSingleZoneReheat.addToNode overwrites the control zone with the
    loop's FIRST demand-side zone, so a zone set before attaching is silently lost
    on a multi-zone loop (probe_szr_control_zone.py). Set it afterwards and read back.
    """
    zone = fetch_object(model, "ThermalZone", name=control_zone_name)
    szr = spm.to_SetpointManagerSingleZoneReheat().get()
    got = szr.controlZone() if szr.setControlZone(zone) else None
    if got is None or not got.is_initialized() or got.get().handle() != zone.handle():
        return None, f"Could not set control zone '{control_zone_name}' on {spm.nameString()}"
    return got.get().nameString(), None


# ── tools ────────────────────────────────────────────────────────────────

def add_setpoint_manager(
    spm_type: str,
    name: str,
    air_loop_name: str | None = None,
    plant_loop_name: str | None = None,
    node: str = "supply_outlet",
    after_component: str | None = None,
    schedule_name: str | None = None,
    cooling_schedule_name: str | None = None,
    heating_schedule_name: str | None = None,
    control_zone_name: str | None = None,
    control_variable: str | None = None,
    replace_existing: bool = False,
) -> dict[str, Any]:
    """Create a setpoint manager and attach it to a loop node, refusing silent collisions."""
    try:
        model = get_model()
        if spm_type not in SPM_CONSTRUCTOR_TYPES:
            return {"ok": False, "error": f"Unknown spm_type '{spm_type}'. Valid: {list(SPM_CONSTRUCTOR_TYPES)}"}
        if _find_spm(model, name) is not None:
            return {"ok": False, "error": f"A setpoint manager named '{name}' already exists"}
        loop, kind, err = _resolve_loop(model, air_loop_name, plant_loop_name)
        if err:
            return {"ok": False, "error": err}
        if kind == "plant" and spm_type in AIR_LOOP_ONLY_TYPES:
            return {"ok": False, "error": f"{spm_type} is air-loop only; it cannot go on plant loop "
                                          f"'{loop.nameString()}'"}
        target, err = _resolve_node(loop, kind, node, after_component)
        if err:
            return {"ok": False, "error": err}

        spm, err = _construct_spm(
            model, spm_type, loop, kind, schedule_name=schedule_name,
            cooling_schedule_name=cooling_schedule_name, heating_schedule_name=heating_schedule_name,
            control_zone_name=control_zone_name, control_variable=control_variable,
        )
        if err:
            return {"ok": False, "error": err}
        spm.setName(name)
        cv = spm.controlVariable()

        # The SDK gives no signal for this: addToNode would delete `existing` silently.
        existing = [s for s in target.setpointManagers() if s.controlVariable() == cv]
        if existing and not replace_existing:
            spm.remove()
            desc = ", ".join(f"'{s.nameString()}' ({s.iddObjectType().valueName()})" for s in existing)
            return {"ok": False, "error": f"Node '{target.nameString()}' already has a {cv} setpoint "
                                          f"manager: {desc}. Pass replace_existing=True to replace it"}
        replaced = [s.nameString() for s in existing]
        if not spm.addToNode(target):
            spm.remove()
            hint = " (this type is air-loop only)" if kind == "plant" else ""
            return {"ok": False, "error": f"{spm_type} was refused on {kind} loop '{loop.nameString()}' "
                                          f"node '{target.nameString()}'{hint}"}
        control_zone = None
        if spm_type == "SetpointManagerSingleZoneReheat":
            control_zone, err = _apply_control_zone(spm, model, control_zone_name)
            if err:
                spm.remove()
                return {"ok": False, "error": err}
        return {
            "ok": True,
            "name": spm.nameString(),
            "spm_type": spm_type,
            "control_variable": cv,
            "control_zone": control_zone,
            "loop": loop.nameString(),
            "loop_type": kind,
            "node_name": target.nameString(),
            "replaced": replaced[0] if len(replaced) == 1 else (replaced or None),
            "setpoint_managers_on_node": [s.nameString() for s in target.setpointManagers()],
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add setpoint manager: {e}"}


def remove_setpoint_manager(name: str) -> dict[str, Any]:
    """Delete one setpoint manager; warn when a loop outlet is left without temperature control."""
    try:
        model = get_model()
        found = _find_spm(model, name)
        if found is None:
            return {"ok": False, "error": f"Setpoint manager '{name}' not found. Supported types: "
                                          f"{list(SPM_CONSTRUCTOR_TYPES)}"}
        spm, spm_type = found
        node_opt = spm.setpointNode()
        node = node_opt.get() if node_opt.is_initialized() else None
        node_name = node.nameString() if node is not None else None
        cv = spm.controlVariable()
        spm.remove()

        result: dict[str, Any] = {
            "ok": True,
            "removed": name,
            "spm_type": spm_type,
            "node_name": node_name,
            "remaining_on_node": [s.nameString() for s in node.setpointManagers()] if node is not None else [],
        }
        if node is not None and cv == "Temperature":
            loop_outlet = None
            air = node.airLoopHVAC()
            plant = node.plantLoop()
            if air.is_initialized() and air.get().supplyOutletNode().handle() == node.handle():
                loop_outlet = air.get().nameString()
            elif plant.is_initialized() and plant.get().supplyOutletNode().handle() == node.handle():
                loop_outlet = plant.get().nameString()
            if loop_outlet is not None and not any(
                s.controlVariable() == "Temperature" for s in node.setpointManagers()
            ):
                result["warnings"] = [
                    f"'{node_name}' is the supply outlet of '{loop_outlet}' and now has no Temperature "
                    "setpoint manager; EnergyPlus will not simulate the loop until one is added "
                    "(add_setpoint_manager)",
                ]
        return result
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to remove setpoint manager: {e}"}
