"""Integration tests for add / remove / replace of AirLoopHVAC supply-branch components (#148).

Two styles on purpose:
- stdio through the MCP server for the tool contract (response shape, errors, ordering).
- in-process calls for the setpoint-manager topology cases, which need an SPM placed on a
  mid-branch node — nothing creates one there through MCP today (see
  docs/plans/plan-followup-add-setpoint-manager.md).

SDK facts these rest on (dev/issue149-probes/, OpenStudio 3.11.0): remove() deletes the
component's OUTLET node (its INLET node when it is last before supplyOutletNode) and any
SetpointManager on it; addToNode on a node handle captured before remove() segfaults the
process; SetpointManager.addToNode silently deletes an existing same-control-variable SPM
on the target node.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from conftest import create_baseline_and_load, integration_enabled, server_params, setup_example, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not integration_enabled(), reason="integration disabled"),
]

SYS3_ORDER = [
    "OS_Coil_Cooling_DX_SingleSpeed",
    "OS_Coil_Heating_Gas",
    "OS_Fan_ConstantVolume",
    "OS_AirLoopHVAC_OutdoorAirSystem",
]


def _unique(prefix: str = "als") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _sys3(s, name: str, loop_name: str) -> None:
    """Example model + one PSZ-AC (System 3) loop: clg → htg → fan → OA system."""
    await setup_example(s, name)
    zones = unwrap(await s.call_tool("list_thermal_zones", {"max_results": 1}))
    res = unwrap(await s.call_tool("add_baseline_system", {
        "system_type": 3, "thermal_zone_names": [zones["thermal_zones"][0]["name"]],
        "system_name": loop_name,
    }))
    assert res["ok"] is True, res


def _types(order: list[dict]) -> list[str]:
    return [c["type"] for c in order]


async def _loop_details(s, loop_name: str) -> dict:
    res = unwrap(await s.call_tool("get_air_loop_details", {"air_loop_name": loop_name}))
    assert res["ok"] is True, res
    return res["air_loop"]


# ── add ──────────────────────────────────────────────────────────────────

def test_add_appends_at_supply_outlet_by_default():
    # Validates: with no insert flag the new component lands last on the branch, the
    # response carries the FULL ordered supply list (get_air_loop_details truncates at 10)
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys3(s, _unique(), "PSZ Add")
                res = unwrap(await s.call_tool("add_air_loop_supply_component", {
                    "air_loop_name": "PSZ Add", "component_type": "CoilHeatingElectric",
                    "component_name": "Reheat Booster",
                }))
                assert res["ok"] is True, res
                assert res["component_name"] == "Reheat Booster"
                assert res["component_type"] == "CoilHeatingElectric"
                assert res["plant_loop"] is None
                assert _types(res["supply_order"]) == [*SYS3_ORDER, "OS_Coil_Heating_Electric"]
                assert res["supply_order"][-1]["name"] == "Reheat Booster"
                # Independent read-back
                details = await _loop_details(s, "PSZ Add")
                assert details["num_supply_components"] == 2 * 5 + 1, "5 components + 6 nodes"
    asyncio.run(_run())


@pytest.mark.parametrize(("flag", "expected"), [
    ("insert_before", ["OS_Coil_Cooling_DX_SingleSpeed", "OS_Coil_Heating_Electric", "OS_Coil_Heating_Gas",
                       "OS_Fan_ConstantVolume", "OS_AirLoopHVAC_OutdoorAirSystem"]),
    ("insert_after", ["OS_Coil_Cooling_DX_SingleSpeed", "OS_Coil_Heating_Gas", "OS_Coil_Heating_Electric",
                      "OS_Fan_ConstantVolume", "OS_AirLoopHVAC_OutdoorAirSystem"]),
])
def test_add_insert_relative_to_named_component(flag, expected):
    # Validates: insert_before targets the anchor's inlet node, insert_after its outlet node,
    # giving exact positions rather than "somewhere on the loop"
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys3(s, _unique(), "PSZ Ins")
                res = unwrap(await s.call_tool("add_air_loop_supply_component", {
                    "air_loop_name": "PSZ Ins", "component_type": "CoilHeatingElectric",
                    "component_name": "Booster Coil", flag: "PSZ Ins Gas Heating Coil",
                }))
                assert res["ok"] is True, res
                assert _types(res["supply_order"]) == expected
    asyncio.run(_run())


def test_add_water_coil_joins_plant_demand_side():
    # Validates: a water coil is wired to the named plant loop's demand side before it goes
    # on the air branch, so the model forward-translates (unconnected water coils are fatal)
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                zones = await create_baseline_and_load(s, _unique("sys7"))
                sys7 = unwrap(await s.call_tool("add_baseline_system", {
                    "system_type": 7, "thermal_zone_names": zones, "system_name": "VAV7",
                }))
                assert sys7["ok"] is True, sys7
                loops = unwrap(await s.call_tool("list_plant_loops", {}))["plant_loops"]
                hw = next(pl["name"] for pl in loops if "hot" in pl["name"].lower() or "hw" in pl["name"].lower())
                res = unwrap(await s.call_tool("add_air_loop_supply_component", {
                    "air_loop_name": "VAV7", "component_type": "CoilHeatingWater",
                    "component_name": "Preheat Coil", "plant_loop_name": hw,
                }))
                assert res["ok"] is True, res
                assert res["plant_loop"] == hw
                assert res["supply_order"][-1] == {"name": "Preheat Coil", "type": "OS_Coil_Heating_Water"}
                # Independent proof it is on the HW demand side: the plant-side remover finds it
                # (a coil never wired there is refused), and a second removal is refused
                off = unwrap(await s.call_tool("remove_demand_component", {
                    "component_name": "Preheat Coil", "plant_loop_name": hw,
                }))
                assert off["ok"] is True, off
                again = unwrap(await s.call_tool("remove_demand_component", {
                    "component_name": "Preheat Coil", "plant_loop_name": hw,
                }))
                assert again["ok"] is False, again
    asyncio.run(_run())


@pytest.mark.parametrize(("args", "needle"), [
    ({"component_type": "CoilCoolingWater", "component_name": "Orphan CHW"}, "plant_loop_name"),
    ({"component_type": "CoilCoolingFourPipeBeam", "component_name": "X"}, "Unknown component_type"),
    ({"component_type": "FanOnOff", "component_name": "X",
      "insert_before": "PSZ Err Gas Heating Coil", "insert_after": "PSZ Err Gas Heating Coil"},
     "either insert_before or insert_after"),
    ({"component_type": "FanOnOff", "component_name": "X", "insert_after": "No Such Coil"},
     "not found on the supply side"),
    ({"component_type": "FanOnOff", "component_name": "PSZ Err Supply Fan"}, "already on"),
    ({"component_type": "FanOnOff", "component_name": "Second Fan"}, "already has a fan"),
    ({"component_type": "FanOnOff", "component_name": "X", "air_loop_name": "Nope"}, "Air loop 'Nope' not found"),
])
def test_add_rejects_bad_input(args, needle):
    # Validates: every refusal names the problem — a water coil without a plant loop, an
    # unsupported type, contradictory anchors, a missing anchor, a duplicate name, a second
    # fan (the SDK allows one per supply branch and addToNode just returns false), no loop
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys3(s, _unique(), "PSZ Err")
                call = {"air_loop_name": "PSZ Err", **args}
                res = unwrap(await s.call_tool("add_air_loop_supply_component", call))
                assert res["ok"] is False, res
                assert needle in res["error"], res["error"]
                details = await _loop_details(s, "PSZ Err")
                assert details["num_supply_components"] == 2 * 4 + 1, "refusal must not touch the loop"
    asyncio.run(_run())


# ── remove ───────────────────────────────────────────────────────────────

def test_remove_mid_branch_component():
    # Regression: #148 — delete_object could remove() a coil blindly with no loop check; the
    # dedicated tool verifies the component is on THIS loop, removes it and returns the order
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys3(s, _unique(), "PSZ Rm")
                res = unwrap(await s.call_tool("remove_air_loop_supply_component", {
                    "air_loop_name": "PSZ Rm", "component_name": "PSZ Rm DX Cooling Coil",
                }))
                assert res["ok"] is True, res
                assert res["removed"] == {"name": "PSZ Rm DX Cooling Coil", "type": "OS_Coil_Cooling_DX_SingleSpeed"}
                assert res["moved_setpoint_managers"] == []
                assert res["dropped_setpoint_managers"] == []
                assert _types(res["supply_order"]) == SYS3_ORDER[1:]
                objs = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "CoilCoolingDXSingleSpeed", "max_results": 0,
                }))
                assert [o["name"] for o in objs["objects"]] == []
    asyncio.run(_run())


def test_remove_last_straight_component_keeps_outlet_setpoint_manager():
    # Validates: removing the fan (last straight component; System 3 keeps the OA system
    # between it and the outlet) drops exactly one component + one node and leaves the
    # OA system and the SPM on supplyOutletNode untouched
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys3(s, _unique(), "PSZ RmFan")
                before = await _loop_details(s, "PSZ RmFan")
                assert len(before["setpoint_managers"]) == 1
                res = unwrap(await s.call_tool("remove_air_loop_supply_component", {
                    "air_loop_name": "PSZ RmFan", "component_name": "PSZ RmFan Supply Fan",
                }))
                assert res["ok"] is True, res
                assert _types(res["supply_order"]) == [
                    "OS_Coil_Cooling_DX_SingleSpeed", "OS_Coil_Heating_Gas", "OS_AirLoopHVAC_OutdoorAirSystem",
                ]
                after = await _loop_details(s, "PSZ RmFan")
                assert after["setpoint_managers"] == before["setpoint_managers"]
                assert after["num_supply_components"] == before["num_supply_components"] - 2
    asyncio.run(_run())


@pytest.mark.parametrize(("component", "needle"), [
    ("PSZ RmErr OA System", "not a straight component"),
    ("PSZ RmErr Terminal", "not found on the supply side"),
    ("Nope", "not found on the supply side"),
])
def test_remove_rejects_non_straight_or_missing(component, needle):
    # Validates: OA systems, demand-side terminals and unknown names are refused by name
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys3(s, _unique(), "PSZ RmErr")
                details = await _loop_details(s, "PSZ RmErr")
                oa_name = next(c["name"] for c in details["supply_components"]
                               if c["type"] == "OS_AirLoopHVAC_OutdoorAirSystem")
                name = oa_name if component == "PSZ RmErr OA System" else component
                res = unwrap(await s.call_tool("remove_air_loop_supply_component", {
                    "air_loop_name": "PSZ RmErr", "component_name": name,
                }))
                assert res["ok"] is False, res
                assert needle in res["error"], res["error"]
    asyncio.run(_run())


# ── replace ──────────────────────────────────────────────────────────────

def test_replace_dx_coil_in_place_reuses_name_and_order():
    # Regression: #148/#149 — the only way to swap a coil was a hand-written measure whose
    # natural ordering (remove, then addToNode) segfaults; the tool does add-first in code
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys3(s, _unique(), "PSZ Rep")
                res = unwrap(await s.call_tool("replace_air_loop_supply_component", {
                    "air_loop_name": "PSZ Rep", "component_name": "PSZ Rep DX Cooling Coil",
                    "new_component_type": "CoilCoolingDXTwoSpeed",
                }))
                assert res["ok"] is True, res
                assert res["removed"] == {"name": "PSZ Rep DX Cooling Coil", "type": "OS_Coil_Cooling_DX_SingleSpeed"}
                assert res["added"] == {"name": "PSZ Rep DX Cooling Coil", "type": "OS_Coil_Cooling_DX_TwoSpeed"}
                assert res["plant_loop"] is None
                assert _types(res["supply_order"]) == ["OS_Coil_Cooling_DX_TwoSpeed", *SYS3_ORDER[1:]]
                props = unwrap(await s.call_tool("get_component_properties", {
                    "component_name": "PSZ Rep DX Cooling Coil",
                }))
                assert props["ok"] is True, props
                assert props["component_type"] == "CoilCoolingDXTwoSpeed"
                old = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "CoilCoolingDXSingleSpeed", "max_results": 0,
                }))
                assert old["objects"] == []
    asyncio.run(_run())


def test_replace_fan_keeps_order_node_count_and_outlet_setpoint_manager():
    # Validates: swapping the constant-volume fan for a VAV fan (the issue's headline ask)
    # keeps the branch order and node count and leaves the outlet SPM alone; the true
    # last-before-outlet edge case is pinned in-process below (System 3 has the OA system last)
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys3(s, _unique(), "PSZ RepFan")
                before = await _loop_details(s, "PSZ RepFan")
                res = unwrap(await s.call_tool("replace_air_loop_supply_component", {
                    "air_loop_name": "PSZ RepFan", "component_name": "PSZ RepFan Supply Fan",
                    "new_component_type": "FanVariableVolume", "new_component_name": "VAV Fan",
                }))
                assert res["ok"] is True, res
                assert res["added"] == {"name": "VAV Fan", "type": "OS_Fan_VariableVolume"}
                assert _types(res["supply_order"]) == [
                    "OS_Coil_Cooling_DX_SingleSpeed", "OS_Coil_Heating_Gas",
                    "OS_Fan_VariableVolume", "OS_AirLoopHVAC_OutdoorAirSystem",
                ]
                after = await _loop_details(s, "PSZ RepFan")
                assert after["setpoint_managers"] == before["setpoint_managers"]
                assert after["num_supply_components"] == before["num_supply_components"]
    asyncio.run(_run())


def test_replace_water_coil_reuses_existing_plant_loop():
    # Validates: swapping a water coil for another water coil keeps the old coil's plant
    # loop without the caller re-stating it
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                zones = await create_baseline_and_load(s, _unique("sys7r"))
                sys7 = unwrap(await s.call_tool("add_baseline_system", {
                    "system_type": 7, "thermal_zone_names": zones, "system_name": "VAV7R",
                }))
                assert sys7["ok"] is True, sys7
                details = await _loop_details(s, "VAV7R")
                clg = details["detailed_components"]["cooling_coils"]
                assert [c["type"] for c in clg] == ["OS_Coil_Cooling_Water"], clg
                res = unwrap(await s.call_tool("replace_air_loop_supply_component", {
                    "air_loop_name": "VAV7R", "component_name": clg[0]["name"],
                    "new_component_type": "CoilCoolingWater", "new_component_name": "CHW Coil v2",
                }))
                assert res["ok"] is True, res
                assert res["plant_loop"], "must report the reused chilled-water loop"
                assert res["added"] == {"name": "CHW Coil v2", "type": "OS_Coil_Cooling_Water"}
                kept = [c["type"] for c in details["supply_components"] if c["type"] != "OS_Node"]
                assert [c["type"] for c in res["supply_order"]] == kept
                # Independent proof the new coil sits on the CHW demand side and the old one is gone
                off = unwrap(await s.call_tool("remove_demand_component", {
                    "component_name": "CHW Coil v2", "plant_loop_name": res["plant_loop"],
                }))
                assert off["ok"] is True, off
                gone = unwrap(await s.call_tool("remove_demand_component", {
                    "component_name": clg[0]["name"], "plant_loop_name": res["plant_loop"],
                }))
                assert gone["ok"] is False, gone
    asyncio.run(_run())


def test_replace_dx_with_water_coil_requires_plant_loop():
    # Validates: a DX → water swap has no plant loop to inherit; the tool refuses before
    # touching the branch instead of leaving an unconnected coil
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys3(s, _unique(), "PSZ RepW")
                res = unwrap(await s.call_tool("replace_air_loop_supply_component", {
                    "air_loop_name": "PSZ RepW", "component_name": "PSZ RepW DX Cooling Coil",
                    "new_component_type": "CoilCoolingWater",
                }))
                assert res["ok"] is False, res
                assert "plant_loop_name" in res["error"]
                details = await _loop_details(s, "PSZ RepW")
                assert [c["type"] for c in details["detailed_components"]["cooling_coils"]] == \
                    ["OS_Coil_Cooling_DX_SingleSpeed"]
    asyncio.run(_run())


# ── in-process: setpoint managers on mid-branch nodes ────────────────────

@pytest.fixture
def inproc_loop(tmp_path: Path):
    """Empty model in model_manager + one air loop  clg → htg → fan  (fan last)."""
    if not os.environ.get("RUN_OPENSTUDIO_INTEGRATION"):
        pytest.skip("requires OpenStudio")
    import openstudio

    from mcp_server.model_manager import clear_model, load_model

    osm = tmp_path / "als.osm"
    openstudio.model.Model().save(openstudio.toPath(str(osm)), True)
    model = load_model(osm)
    loop = openstudio.model.AirLoopHVAC(model)
    loop.setName("Loop")
    always_on = model.alwaysOnDiscreteSchedule()
    clg = openstudio.model.CoilCoolingDXSingleSpeed(model)
    clg.setName("Clg")
    htg = openstudio.model.CoilHeatingElectric(model, always_on)
    htg.setName("Htg")
    fan = openstudio.model.FanVariableVolume(model, always_on)
    fan.setName("Fan")
    for comp in (clg, htg, fan):
        assert comp.addToNode(loop.supplyOutletNode())
    yield model, loop
    clear_model()


def _spm_on(model, node, name: str, control_variable: str = "Temperature"):
    import openstudio
    sch = openstudio.model.ScheduleConstant(model)
    sch.setValue(12.8)
    spm = openstudio.model.SetpointManagerScheduled(model, sch)
    spm.setName(name)
    assert spm.setControlVariable(control_variable)
    assert spm.addToNode(node)
    return spm


def _node(opt):
    return opt.get().to_Node().get()


def test_remove_moves_setpoint_manager_from_doomed_outlet_node(inproc_loop):
    # Regression: #148 — remove() deletes the coil's outlet node and silently takes the
    # SPM with it; the tool moves the SPM to the surviving inlet node and reports it
    from mcp_server.skills.loop_operations.air_loop_supply import remove_air_loop_supply_component
    model, _loop = inproc_loop
    clg = model.getCoilCoolingDXSingleSpeedByName("Clg").get()
    inlet = _node(clg.inletModelObject())
    spm = _spm_on(model, _node(clg.outletModelObject()), "Clg Leaving SPM")

    res = remove_air_loop_supply_component("Loop", "Clg")

    assert res["ok"] is True, res
    assert res["moved_setpoint_managers"] == ["Clg Leaving SPM"]
    assert res["dropped_setpoint_managers"] == []
    assert model.getObject(spm.handle()).is_initialized(), "SPM must survive the node deletion"
    assert [s.nameString() for s in inlet.setpointManagers()] == ["Clg Leaving SPM"]
    assert [c["name"] for c in res["supply_order"]] == ["Htg", "Fan"]


def test_remove_reports_dropped_setpoint_manager_on_control_variable_collision(inproc_loop):
    # Regression: SetpointManager.addToNode silently DELETES a same-control-variable SPM
    # already on the target node (probe_spm_collision.py); the tool must never let a move
    # destroy an SPM the user did not touch — it leaves the doomed one and says so
    from mcp_server.skills.loop_operations.air_loop_supply import remove_air_loop_supply_component
    model, _loop = inproc_loop
    clg = model.getCoilCoolingDXSingleSpeedByName("Clg").get()
    keep = _spm_on(model, _node(clg.inletModelObject()), "Inlet Temp SPM")
    doomed = _spm_on(model, _node(clg.outletModelObject()), "Outlet Temp SPM")

    res = remove_air_loop_supply_component("Loop", "Clg")

    assert res["ok"] is True, res
    assert res["moved_setpoint_managers"] == []
    assert res["dropped_setpoint_managers"] == ["Outlet Temp SPM"]
    assert "Inlet Temp SPM" in res["warnings"][0]
    assert model.getObject(keep.handle()).is_initialized(), "untouched SPM must survive"
    assert not model.getObject(doomed.handle()).is_initialized(), "doomed SPM died with its node"


def test_replace_moves_setpoint_manager_to_new_outlet_node(inproc_loop):
    # Validates: an SPM on the old coil's outlet lands on the NEW coil's outlet, i.e. the
    # same position on the branch, not upstream of the replacement
    from mcp_server.skills.loop_operations.air_loop_supply import replace_air_loop_supply_component
    model, _loop = inproc_loop
    clg = model.getCoilCoolingDXSingleSpeedByName("Clg").get()
    spm = _spm_on(model, _node(clg.outletModelObject()), "Clg Leaving SPM")

    res = replace_air_loop_supply_component("Loop", "Clg", "CoilCoolingDXTwoSpeed")

    assert res["ok"] is True, res
    assert res["moved_setpoint_managers"] == ["Clg Leaving SPM"]
    new = model.getCoilCoolingDXTwoSpeedByName("Clg").get()
    assert [s.nameString() for s in _node(new.outletModelObject()).setpointManagers()] == ["Clg Leaving SPM"]
    assert model.getObject(spm.handle()).is_initialized()
    assert [c["name"] for c in res["supply_order"]] == ["Clg", "Htg", "Fan"]
    assert not model.getCoilCoolingDXSingleSpeedByName("Clg").is_initialized(), "old coil gone"


def test_replace_last_component_in_process_keeps_outlet_spm(inproc_loop):
    # Validates: fan is last (its outlet IS supplyOutletNode); replacing it keeps the outlet
    # SPM and the node count, and the new fan's outlet is the loop outlet
    from mcp_server.skills.loop_operations.air_loop_supply import replace_air_loop_supply_component
    model, loop = inproc_loop
    outlet_spm = _spm_on(model, loop.supplyOutletNode(), "Deck SPM")
    nodes_before = sum(1 for c in loop.supplyComponents() if c.to_Node().is_initialized())

    res = replace_air_loop_supply_component("Loop", "Fan", "FanConstantVolume")

    assert res["ok"] is True, res
    assert res["moved_setpoint_managers"] == []
    assert model.getObject(outlet_spm.handle()).is_initialized()
    assert [s.nameString() for s in loop.supplyOutletNode().setpointManagers()] == ["Deck SPM"]
    new_fan = model.getFanConstantVolumeByName("Fan").get()
    assert new_fan.outletModelObject().get().handle() == loop.supplyOutletNode().handle()
    assert sum(1 for c in loop.supplyComponents() if c.to_Node().is_initialized()) == nodes_before


# ── in-process: water coils and the plant demand branch ──────────────────

def _chw_with_coil(model, loop):
    """A CHW plant loop with one CoilCoolingWater on the air loop; returns (plant, coil, base_count)."""
    import openstudio
    plant = openstudio.model.PlantLoop(model)
    plant.setName("CHW")
    base = len(list(plant.demandComponents()))
    coil = openstudio.model.CoilCoolingWater(model, model.alwaysOnDiscreteSchedule())
    coil.setName("CHW Coil")
    assert plant.addDemandBranchForComponent(coil)
    assert coil.addToNode(loop.supplyOutletNode())
    return plant, coil, base


def test_remove_water_coil_also_removes_its_plant_demand_branch(inproc_loop):
    # Validates: remove() on a WaterToAirComponent takes its plant demand branch (nodes +
    # branch) with it — the plant is back to its pre-coil topology, no stale nodes (review
    # claim on #148 checked by dev/issue149-probes/probe_water_coil_remove.py)
    from mcp_server.skills.loop_operations.air_loop_supply import remove_air_loop_supply_component
    model, loop = inproc_loop
    plant, coil, base = _chw_with_coil(model, loop)
    assert len(list(plant.demandComponents())) == base + 2, "coil + its branch node"

    res = remove_air_loop_supply_component("Loop", "CHW Coil")

    assert res["ok"] is True, res
    assert res["removed"] == {"name": "CHW Coil", "type": "OS_Coil_Cooling_Water"}
    assert len(list(plant.demandComponents())) == base
    assert not model.getObject(coil.handle()).is_initialized()
    assert [c["name"] for c in res["supply_order"]] == ["Clg", "Htg", "Fan"]


def test_replace_water_coil_keeps_plant_demand_topology(inproc_loop):
    # Validates: a water-for-water swap inherits the plant loop and ends with exactly one
    # demand branch — the old coil's branch is gone, the new coil's is present
    from mcp_server.skills.loop_operations.air_loop_supply import replace_air_loop_supply_component
    model, loop = inproc_loop
    plant, coil, _base = _chw_with_coil(model, loop)
    one_coil = len(list(plant.demandComponents()))

    res = replace_air_loop_supply_component("Loop", "CHW Coil", "CoilHeatingWater",
                                            new_component_name="HW-on-CHW Coil")

    assert res["ok"] is True, res
    assert res["plant_loop"] == "CHW"
    assert res["added"] == {"name": "HW-on-CHW Coil", "type": "OS_Coil_Heating_Water"}
    assert len(list(plant.demandComponents())) == one_coil, "old branch removed, new branch added"
    demand = [c.nameString() for c in plant.demandComponents() if not c.to_Node().is_initialized()]
    assert "HW-on-CHW Coil" in demand and "CHW Coil" not in demand, demand
    assert [c["name"] for c in res["supply_order"]] == ["Clg", "Htg", "Fan", "HW-on-CHW Coil"]
    assert not model.getObject(coil.handle()).is_initialized()
