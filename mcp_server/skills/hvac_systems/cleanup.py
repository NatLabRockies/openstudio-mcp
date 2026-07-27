"""Repair side effects of moving thermal zones onto a new air system (#83).

OpenStudio's ``AirLoopHVAC.addBranchForZone`` silently removes the zone from
the air loop that previously served it. Two kinds of wreckage can remain on
the old loop, and both are EnergyPlus input-processing fatals:

- a ``SetpointManager:SingleZone:*`` whose control zone is now empty
  ("Missing required property 'control_zone_name'"), and
- an air loop left serving zero zones
  ("An outlet node in AirLoopHVAC=... is not connected to any zone").

Deleting only the orphaned setpoint manager is NOT enough — the empty loop
itself still fatals — so a loop that lost all its zones is removed outright.
Both repairs were validated empirically against EnergyPlus 25.2.
"""
from __future__ import annotations

from typing import Any

import openstudio  # noqa: F401 — SDK objects arrive via the model argument


def snapshot_loop_zones(model) -> dict[str, int]:
    """Record zone counts per air loop before a tool rewires zones.

    Keyed by handle string so repairs only touch loops that existed before
    the tool call — never the loop the tool itself just created.
    """
    return {
        str(loop.handle()): len(loop.thermalZones())
        for loop in model.getAirLoopHVACs()
    }


def _single_zone_spms(model) -> list:
    """All setpoint managers with a control-zone field, explicit per type."""
    spms: list = []
    spms.extend(model.getSetpointManagerSingleZoneReheats())
    spms.extend(model.getSetpointManagerSingleZoneCoolings())
    spms.extend(model.getSetpointManagerSingleZoneHeatings())
    return spms


def repair_orphaned_air_loops(model, before: dict[str, int]) -> list[dict[str, Any]]:
    """Repair pre-existing air loops broken by zone reassignment.

    Args:
        model: OpenStudio model, after the new system was wired
        before: snapshot_loop_zones() taken before wiring

    Returns:
        List of repair-action dicts (empty when nothing was broken):
        {"action": "removed_empty_air_loop", "air_loop": name, "reason": ...} or
        {"action": "retargeted_setpoint_manager", "setpoint_manager": name,
         "air_loop": name, "new_control_zone": name, "reason": ...}
    """
    actions: list[dict[str, Any]] = []

    # Loops that served zones before this call and serve none now cannot
    # simulate; removing the loop also removes its setpoint managers.
    for loop in list(model.getAirLoopHVACs()):
        handle = str(loop.handle())
        if before.get(handle, 0) > 0 and len(loop.thermalZones()) == 0:
            actions.append({
                "action": "removed_empty_air_loop",
                "air_loop": loop.nameString(),
                "reason": (
                    "lost all its thermal zones to the new system; an air "
                    "loop serving zero zones fails EnergyPlus input processing"
                ),
            })
            loop.remove()

    # A surviving loop can still hold a SingleZone SPM whose control zone
    # moved away; retarget it to a zone the loop still serves.
    for spm in _single_zone_spms(model):
        if spm.controlZone().is_initialized():
            continue
        node = spm.setpointNode()
        if not node.is_initialized():
            continue
        loop = node.get().airLoopHVAC()
        if not loop.is_initialized():
            continue
        served = loop.get().thermalZones()
        if not served:
            continue  # loop removal above already handles the zero-zone case
        spm.setControlZone(served[0])
        actions.append({
            "action": "retargeted_setpoint_manager",
            "setpoint_manager": spm.nameString(),
            "air_loop": loop.get().nameString(),
            "new_control_zone": served[0].nameString(),
            "reason": (
                "its control zone was moved to another system; EnergyPlus "
                "rejects a SetpointManager:SingleZone:* without a control zone"
            ),
        })

    return actions
