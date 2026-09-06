"""Add / remove / replace coils and fans on an AirLoopHVAC supply branch (issue #148).

Plant loops have add_supply_equipment / remove_supply_equipment
(parallel-branch semantics: addSupplyBranchForComponent). An air loop's supply
side is a single series branch, so these tools work in node terms instead:
addToNode(node) inserts immediately downstream of `node`, and
addToNode(supplyOutletNode) appends at the end.

SDK facts this module rests on (dev/issue149-probes/, OpenStudio 3.11.0):
- component.remove() deletes the component's OUTLET node (its INLET node when
  the component is last before supplyOutletNode) together with every
  SetpointManager on that node. The loop outlet node always survives.
- addToNode on a Node handle captured before remove() segfaults the process —
  Ruby and Python alike, no exception. Replace therefore inserts the new
  component FIRST and removes the old one SECOND. That order is load-bearing.
- SetpointManager.addToNode(node) silently deletes any SPM already on `node`
  with the same controlVariable(). Moves check the target first and never
  destroy an SPM the caller did not touch.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object

# Coils and fans that set_component_properties / get_component_properties
# already understand (component_properties/components.py COMPONENT_TYPES).
AIR_SUPPLY_COMPONENT_TYPES: tuple[str, ...] = (
    "FanConstantVolume",
    "FanVariableVolume",
    "FanOnOff",
    "CoilHeatingElectric",
    "CoilHeatingGas",
    "CoilHeatingWater",
    "CoilHeatingDXSingleSpeed",
    "CoilCoolingDXSingleSpeed",
    "CoilCoolingDXTwoSpeed",
    "CoilCoolingWater",
)
WATER_COIL_TYPES = frozenset({"CoilHeatingWater", "CoilCoolingWater"})


# ── helpers ──────────────────────────────────────────────────────────────

def _construct(model, component_type: str):
    """Build a bare component. Explicit branches: no getattr dispatch (CLAUDE.md rule 12)."""
    always_on = model.alwaysOnDiscreteSchedule()
    if component_type == "FanConstantVolume":
        return openstudio.model.FanConstantVolume(model, always_on)
    if component_type == "FanVariableVolume":
        return openstudio.model.FanVariableVolume(model, always_on)
    if component_type == "FanOnOff":
        return openstudio.model.FanOnOff(model, always_on)
    if component_type == "CoilHeatingElectric":
        return openstudio.model.CoilHeatingElectric(model, always_on)
    if component_type == "CoilHeatingGas":
        return openstudio.model.CoilHeatingGas(model, always_on)
    if component_type == "CoilHeatingWater":
        return openstudio.model.CoilHeatingWater(model, always_on)
    if component_type == "CoilHeatingDXSingleSpeed":
        return openstudio.model.CoilHeatingDXSingleSpeed(model)
    if component_type == "CoilCoolingDXSingleSpeed":
        return openstudio.model.CoilCoolingDXSingleSpeed(model)
    if component_type == "CoilCoolingDXTwoSpeed":
        return openstudio.model.CoilCoolingDXTwoSpeed(model)
    if component_type == "CoilCoolingWater":
        return openstudio.model.CoilCoolingWater(model, always_on)
    raise ValueError(f"Unknown component_type '{component_type}'")


def _ordered_supply(air_loop) -> list[dict[str, str]]:
    """Every non-Node supply component, in flow order, untruncated."""
    return [
        {"name": c.nameString(), "type": c.iddObjectType().valueName()}
        for c in air_loop.supplyComponents()
        if not c.to_Node().is_initialized()
    ]


def _find_on_supply(air_loop, name: str):
    """HVACComponent named `name` on THIS loop's supply side, else None."""
    for c in air_loop.supplyComponents():
        if c.to_Node().is_initialized():
            continue
        if c.nameString() == name:
            return c
    return None


def _hvac_name_taken(model, name: str) -> str | None:
    """IDD type of an HVACComponent anywhere in the model already named `name`, else None.

    The SDK keeps HVAC component names unique model-wide (case-insensitively) and setName
    on a collision silently appends ' 1' (probe_name_lookup.py); refusing keeps the reported
    component_name honest and name-only follow-ups (set_component_properties) unambiguous.
    """
    for obj in model.getModelObjectsByName(name, True):
        if obj.to_HVACComponent().is_initialized():
            return obj.iddObjectType().valueName()
    return None


def _name_taken_error(name: str, taken_by: str) -> str:
    return (f"'{name}' is already used by an existing {taken_by} in this model; HVAC component names "
            "must be unique model-wide (the SDK would silently rename the new one)")


def _air_ports(comp):
    """(component, air inlet Node, air outlet Node) for a coil or fan, else None.

    Fans and DX/electric/gas coils are StraightComponents; water coils are
    WaterToAirComponents whose air-side ports have different getters. Outdoor
    air systems are neither and are refused.
    """
    straight = comp.to_StraightComponent()
    if straight.is_initialized():
        s = straight.get()
        return s, _node_of(s.inletModelObject()), _node_of(s.outletModelObject())
    water_to_air = comp.to_WaterToAirComponent()
    if water_to_air.is_initialized():
        w = water_to_air.get()
        return w, _node_of(w.airInletModelObject()), _node_of(w.airOutletModelObject())
    return None


def _has_fan(air_loop) -> str | None:
    """Name of a fan already on the supply branch, else None (the SDK allows one)."""
    for c in air_loop.supplyComponents():
        if c.iddObjectType().valueName().startswith("OS_Fan_"):
            return c.nameString()
    return None


def _node_of(opt_model_object):
    """Node behind an inlet/outlet ModelObject optional, or None."""
    if not opt_model_object.is_initialized():
        return None
    node = opt_model_object.get().to_Node()
    return node.get() if node.is_initialized() else None


def _spm_names(node) -> list[str]:
    return [s.nameString() for s in node.setpointManagers()]


def _move_spms(from_node, to_node) -> tuple[list[str], list[str]]:
    """Move the SPMs on `from_node` to `to_node`; returns (moved, dropped) names.

    Never lets SetpointManager.addToNode delete an SPM already on `to_node`:
    when the target has one with the same control variable, the SPM stays on
    `from_node` (it dies with that node) and is reported as dropped.
    """
    moved: list[str] = []
    dropped: list[str] = []
    for spm in list(from_node.setpointManagers()):
        cv = spm.controlVariable()
        collides = any(s.controlVariable() == cv for s in to_node.setpointManagers())
        if collides or not spm.addToNode(to_node):
            dropped.append(spm.nameString())
        else:
            moved.append(spm.nameString())
    return moved, dropped


def _resolve_plant_loop(model, component_type: str, plant_loop_name: str | None,
                        inherit_from=None):
    """(plant_loop or None, error or None) for a water coil; (None, None) otherwise."""
    if component_type not in WATER_COIL_TYPES:
        return None, None
    if plant_loop_name is None and inherit_from is not None:
        opt = inherit_from.plantLoop()
        if opt.is_initialized():
            return opt.get(), None
    if plant_loop_name is None:
        return None, (f"{component_type} is a water coil: pass plant_loop_name so it can "
                      "join a plant loop's demand side")
    plant_loop = fetch_object(model, "PlantLoop", name=plant_loop_name)
    if plant_loop is None:
        return None, f"Plant loop '{plant_loop_name}' not found"
    return plant_loop, None


def _build_and_attach(model, component_type: str, name: str, target_node, plant_loop):
    """Construct, join the plant loop (water coils), insert downstream of `target_node`.

    Returns (component, error). On any failure the half-built component is
    removed so a refusal leaves the model exactly as it was.
    """
    comp = _construct(model, component_type)
    comp.setName(name)
    if plant_loop is not None and not plant_loop.addDemandBranchForComponent(comp):
        comp.remove()
        return None, f"Plant loop '{plant_loop.nameString()}' refused {component_type} on its demand side"
    if not comp.addToNode(target_node):
        comp.remove()
        return None, f"addToNode refused {component_type} at '{target_node.nameString()}'"
    return comp, None


def _spm_warning(dropped: list[str], survivor_node) -> str:
    return (f"Setpoint manager(s) {dropped} were on the deleted node and could not move: "
            f"'{survivor_node.nameString()}' already has a setpoint manager with the same "
            f"control variable ({_spm_names(survivor_node)}). They were removed with the node.")


# ── tools ────────────────────────────────────────────────────────────────

def add_air_loop_supply_component(
    air_loop_name: str,
    component_type: str,
    component_name: str,
    insert_before: str | None = None,
    insert_after: str | None = None,
    plant_loop_name: str | None = None,
) -> dict[str, Any]:
    """Create a coil or fan and put it on the air loop's supply branch."""
    try:
        model = get_model()
        if component_type not in AIR_SUPPLY_COMPONENT_TYPES:
            return {"ok": False, "error": f"Unknown component_type '{component_type}'. "
                                          f"Valid: {list(AIR_SUPPLY_COMPONENT_TYPES)}"}
        if insert_before is not None and insert_after is not None:
            return {"ok": False, "error": "Pass either insert_before or insert_after, not both"}
        air_loop = fetch_object(model, "AirLoopHVAC", name=air_loop_name)
        if air_loop is None:
            return {"ok": False, "error": f"Air loop '{air_loop_name}' not found"}
        taken_by = _hvac_name_taken(model, component_name)
        if taken_by is not None:
            return {"ok": False, "error": _name_taken_error(component_name, taken_by)}

        target_node = air_loop.supplyOutletNode()
        anchor_name = insert_before or insert_after
        if anchor_name is not None:
            anchor = _find_on_supply(air_loop, anchor_name)
            if anchor is None:
                return {"ok": False, "error": f"'{anchor_name}' not found on the supply side of "
                                              f"'{air_loop_name}'"}
            ports = _air_ports(anchor)
            if ports is None:
                return {"ok": False, "error": f"'{anchor_name}' is not a coil or fan (not a straight "
                                              "component); anchor on a coil or fan instead"}
            _anchor, a_inlet, a_outlet = ports
            target_node = a_inlet if insert_before else a_outlet
            if target_node is None:
                return {"ok": False, "error": f"'{anchor_name}' has no node to insert at"}
        if component_type.startswith("Fan"):
            existing_fan = _has_fan(air_loop)
            if existing_fan is not None:
                return {"ok": False, "error": f"'{air_loop_name}' already has a fan "
                                              f"('{existing_fan}'); the SDK allows one per supply "
                                              "branch — use replace_air_loop_supply_component"}

        plant_loop, err = _resolve_plant_loop(model, component_type, plant_loop_name)
        if err:
            return {"ok": False, "error": err}
        comp, err = _build_and_attach(model, component_type, component_name, target_node, plant_loop)
        if err:
            return {"ok": False, "error": err}

        return {
            "ok": True,
            "air_loop": air_loop_name,
            "component_name": comp.nameString(),
            "component_type": component_type,
            "plant_loop": plant_loop.nameString() if plant_loop is not None else None,
            "supply_order": _ordered_supply(air_loop),
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add air loop supply component: {e}"}


def remove_air_loop_supply_component(air_loop_name: str, component_name: str) -> dict[str, Any]:
    """Remove a coil or fan from the air loop's supply branch, keeping its setpoint managers."""
    try:
        model = get_model()
        air_loop = fetch_object(model, "AirLoopHVAC", name=air_loop_name)
        if air_loop is None:
            return {"ok": False, "error": f"Air loop '{air_loop_name}' not found"}
        comp = _find_on_supply(air_loop, component_name)
        if comp is None:
            return {"ok": False, "error": f"'{component_name}' not found on the supply side of "
                                          f"'{air_loop_name}'"}
        ports = _air_ports(comp)
        if ports is None:
            return {"ok": False, "error": f"'{component_name}' is not a coil or fan (not a straight "
                                          "component); outdoor air systems cannot be removed this way"}
        straight, inlet, outlet = ports
        if inlet is None or outlet is None:
            return {"ok": False, "error": f"'{component_name}' is not connected on both sides"}

        # remove() deletes the outlet node, or the inlet node when the outlet IS the loop
        # outlet. Rescue the doomed node's SPMs onto the neighbour that survives.
        is_last = outlet.handle() == air_loop.supplyOutletNode().handle()
        doomed, survivor = (inlet, outlet) if is_last else (outlet, inlet)
        moved, dropped = _move_spms(doomed, survivor)
        removed = {"name": straight.nameString(), "type": straight.iddObjectType().valueName()}
        straight.remove()

        result: dict[str, Any] = {
            "ok": True,
            "air_loop": air_loop_name,
            "removed": removed,
            "moved_setpoint_managers": moved,
            "dropped_setpoint_managers": dropped,
            "supply_order": _ordered_supply(air_loop),
        }
        if dropped:
            result["warnings"] = [_spm_warning(dropped, survivor)]
        return result
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to remove air loop supply component: {e}"}


def replace_air_loop_supply_component(
    air_loop_name: str,
    component_name: str,
    new_component_type: str,
    new_component_name: str | None = None,
    plant_loop_name: str | None = None,
) -> dict[str, Any]:
    """Swap a coil or fan in place: new one in first, old one out second."""
    try:
        model = get_model()
        if new_component_type not in AIR_SUPPLY_COMPONENT_TYPES:
            return {"ok": False, "error": f"Unknown new_component_type '{new_component_type}'. "
                                          f"Valid: {list(AIR_SUPPLY_COMPONENT_TYPES)}"}
        air_loop = fetch_object(model, "AirLoopHVAC", name=air_loop_name)
        if air_loop is None:
            return {"ok": False, "error": f"Air loop '{air_loop_name}' not found"}
        old = _find_on_supply(air_loop, component_name)
        if old is None:
            return {"ok": False, "error": f"'{component_name}' not found on the supply side of "
                                          f"'{air_loop_name}'"}
        old_ports = _air_ports(old)
        if old_ports is None:
            return {"ok": False, "error": f"'{component_name}' is not a coil or fan (not a straight "
                                          "component); outdoor air systems cannot be replaced this way"}
        old_straight, inlet, old_outlet = old_ports
        if new_component_name is not None and new_component_name != component_name:
            # The old component still exists when the new one is built (add-first), so a
            # name equal to the old one is fine; anything else must be free model-wide
            taken_by = _hvac_name_taken(model, new_component_name)
            if taken_by is not None:
                return {"ok": False, "error": _name_taken_error(new_component_name, taken_by)}
        if inlet is None or old_outlet is None:
            return {"ok": False, "error": f"'{component_name}' is not connected on both sides"}

        plant_loop, err = _resolve_plant_loop(model, new_component_type, plant_loop_name,
                                              inherit_from=old_straight)
        if err:
            return {"ok": False, "error": err}

        # ORDER IS LOAD-BEARING (issue #149): insert the new component upstream of the old
        # one on the old one's INLET node, and only then remove the old one. Reversed, the
        # captured node handle dangles and addToNode segfaults the server process.
        old_name = old_straight.nameString()
        old_type = old_straight.iddObjectType().valueName()
        # Build under a placeholder: the old component still holds old_name, and the SDK
        # would silently rename a same-named new one ('Clg' -> 'Clg 1'). Final name after remove
        new, err = _build_and_attach(model, new_component_type, f"{old_name} (replacement)", inlet, plant_loop)
        if err:
            return {"ok": False, "error": err}

        # Mid-branch: old.remove() deletes old's outlet node — its SPMs move to the new
        # component's outlet node, the same position on the branch. Last-before-outlet:
        # old.remove() deletes old's inlet node (= new's fresh outlet node, no SPMs) and the
        # SDK splices new to supplyOutletNode, whose SPMs are untouched.
        is_last = old_outlet.handle() == air_loop.supplyOutletNode().handle()
        moved: list[str] = []
        dropped: list[str] = []
        survivor = None
        if not is_last:
            _new, _new_inlet, survivor = _air_ports(new)
            moved, dropped = _move_spms(old_outlet, survivor)
        old_straight.remove()
        new.setName(new_component_name or old_name)

        result: dict[str, Any] = {
            "ok": True,
            "air_loop": air_loop_name,
            "removed": {"name": old_name, "type": old_type},
            "added": {"name": new.nameString(), "type": new.iddObjectType().valueName()},
            "plant_loop": plant_loop.nameString() if plant_loop is not None else None,
            "moved_setpoint_managers": moved,
            "dropped_setpoint_managers": dropped,
            "supply_order": _ordered_supply(air_loop),
        }
        if dropped and survivor is not None:
            result["warnings"] = [_spm_warning(dropped, survivor)]
        return result
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to replace air loop supply component: {e}"}
