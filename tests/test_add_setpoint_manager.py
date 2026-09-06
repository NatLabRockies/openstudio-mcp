"""Integration tests for add_setpoint_manager / remove_setpoint_manager (follow-up to #148).

stdio through the MCP server for the tool contract; in-process for node-placement
assertions that need the SPM's setpointNode() handle.

SDK facts (dev/issue149-probes/probe_spm_collision.py, OpenStudio 3.11.0):
SetpointManager.addToNode silently deletes a same-control-variable SPM already on the
node; different control variables coexist; air-loop-only types return False on a
plant node and attach nothing; spm.remove() leaves the node's other SPMs alone.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from conftest import create_baseline_and_load, integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not integration_enabled(), reason="integration disabled"),
]


def _unique(prefix: str = "spm") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _sys7(s, name: str) -> tuple[list[str], str, str]:
    """Baseline 10-zone model + System 7 (VAV, CHW + HW + condenser). Returns (zones, hw, chw)."""
    zones = await create_baseline_and_load(s, name)
    res = unwrap(await s.call_tool("add_baseline_system", {
        "system_type": 7, "thermal_zone_names": zones, "system_name": "VAV7",
    }))
    assert res["ok"] is True, res
    loops = unwrap(await s.call_tool("list_plant_loops", {}))["plant_loops"]
    names = [pl["name"] for pl in loops]
    hw = next(n for n in names if "hot" in n.lower() or "hw" in n.lower())
    chw = next(n for n in names if "chilled" in n.lower() or "chw" in n.lower())
    return zones, hw, chw


async def _schedule(s, name: str, value: float, schedule_type: str = "Temperature") -> str:
    res = unwrap(await s.call_tool("create_schedule_ruleset", {
        "name": name, "schedule_type": schedule_type, "default_value": value,
    }))
    assert res["ok"] is True, res
    return name


async def _outlet_spms(s, loop_name: str) -> list[dict]:
    res = unwrap(await s.call_tool("get_air_loop_details", {"air_loop_name": loop_name}))
    assert res["ok"] is True, res
    return res["air_loop"]["setpoint_managers"]


# ── add: every supported type ────────────────────────────────────────────

AIR_TYPES = [
    ("SetpointManagerScheduled", {"schedule_name": "SAT Sched"}),
    ("SetpointManagerScheduledDualSetpoint",
     {"cooling_schedule_name": "SAT Sched", "heating_schedule_name": "SAT Sched"}),
    ("SetpointManagerSingleZoneReheat", {"control_zone_name": "<zone0>"}),
    ("SetpointManagerWarmest", {}),
    ("SetpointManagerColdest", {}),
    ("SetpointManagerFollowOutdoorAirTemperature", {}),
    ("SetpointManagerOutdoorAirReset", {}),
]


@pytest.mark.parametrize(("spm_type", "extra"), AIR_TYPES, ids=[t for t, _ in AIR_TYPES])
def test_add_each_type_on_air_loop_supply_inlet(spm_type, extra):
    # Validates: all 7 types construct with their required args, land on the requested node,
    # and are readable back through get_setpoint_manager_properties as that type
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                zones, _hw, _chw = await _sys7(s, _unique())
                await _schedule(s, "SAT Sched", 12.8)
                args = {k: (zones[0] if v == "<zone0>" else v) for k, v in extra.items()}
                res = unwrap(await s.call_tool("add_setpoint_manager", {
                    "spm_type": spm_type, "name": "New SPM", "air_loop_name": "VAV7",
                    "node": "supply_inlet", **args,
                }))
                assert res["ok"] is True, res
                assert res["spm_type"] == spm_type
                assert res["loop"] == "VAV7" and res["loop_type"] == "air"
                assert res["control_variable"] == "Temperature"
                assert res["replaced"] is None
                assert res["setpoint_managers_on_node"] == ["New SPM"]
                props = unwrap(await s.call_tool("get_setpoint_manager_properties", {"setpoint_name": "New SPM"}))
                assert props["ok"] is True, props
                assert props["type"] == spm_type
                # The builder's outlet SPM is untouched
                assert len(await _outlet_spms(s, "VAV7")) == 1
    asyncio.run(_run())


def test_add_scheduled_on_plant_loop_inlet():
    # Validates: plant loops accept Scheduled SPMs on any of their nodes and the response
    # names the plant loop; loop_type distinguishes it from air loops
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                _zones, hw, _chw = await _sys7(s, _unique())
                await _schedule(s, "HW Sched", 60.0)
                res = unwrap(await s.call_tool("add_setpoint_manager", {
                    "spm_type": "SetpointManagerScheduled", "name": "HW Inlet SPM",
                    "plant_loop_name": hw, "node": "supply_inlet", "schedule_name": "HW Sched",
                }))
                assert res["ok"] is True, res
                assert res["loop"] == hw and res["loop_type"] == "plant"
                assert res["setpoint_managers_on_node"] == ["HW Inlet SPM"]
    asyncio.run(_run())


def test_add_on_mixed_air_node():
    # Validates: node="mixed_air" resolves the OA system's mixed-air node. The baseline
    # builders put the OA system LAST on the branch, so on System 7 that node is the supply
    # outlet itself and already carries the builder's Temperature SPM: a Temperature SPM is
    # refused by name, while a HumidityRatio SPM lands beside it without a flag
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys7(s, _unique())
                await _schedule(s, "Hum Sched", 0.008, "Fractional")
                outlet_spm = (await _outlet_spms(s, "VAV7"))[0]["name"]
                refused = unwrap(await s.call_tool("add_setpoint_manager", {
                    "spm_type": "SetpointManagerOutdoorAirReset", "name": "Mixed Air SPM",
                    "air_loop_name": "VAV7", "node": "mixed_air",
                }))
                assert refused["ok"] is False, refused
                assert outlet_spm in refused["error"], refused["error"]

                res = unwrap(await s.call_tool("add_setpoint_manager", {
                    "spm_type": "SetpointManagerScheduled", "name": "Mixed Air Hum SPM",
                    "air_loop_name": "VAV7", "node": "mixed_air", "schedule_name": "Hum Sched",
                    "control_variable": "HumidityRatio",
                }))
                assert res["ok"] is True, res
                assert res["control_variable"] == "HumidityRatio" and res["replaced"] is None
                assert "Mixed Air Hum SPM" in res["setpoint_managers_on_node"]
                assert len(res["setpoint_managers_on_node"]) == 2, res["setpoint_managers_on_node"]
    asyncio.run(_run())


# ── collision guard ──────────────────────────────────────────────────────

def test_collision_refused_by_default_then_replaced_with_flag():
    # Regression: SDK addToNode silently deletes a same-control-variable SPM on the target
    # node — the tool must refuse first (nothing deleted, nothing created), then replace
    # only when asked and report what it replaced
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys7(s, _unique())
                before = await _outlet_spms(s, "VAV7")
                assert len(before) == 1, before
                old_name = before[0]["name"]

                refused = unwrap(await s.call_tool("add_setpoint_manager", {
                    "spm_type": "SetpointManagerOutdoorAirReset", "name": "SAT Reset",
                    "air_loop_name": "VAV7",
                }))
                assert refused["ok"] is False, refused
                assert old_name in refused["error"] and "replace_existing=True" in refused["error"]
                assert await _outlet_spms(s, "VAV7") == before, "refusal must not touch the node"
                orphan = unwrap(await s.call_tool("list_model_objects", {
                    "object_type": "SetpointManagerOutdoorAirReset", "max_results": 0,
                }))
                assert orphan["objects"] == [], "refusal must not leave a detached SPM behind"

                replaced = unwrap(await s.call_tool("add_setpoint_manager", {
                    "spm_type": "SetpointManagerOutdoorAirReset", "name": "SAT Reset",
                    "air_loop_name": "VAV7", "replace_existing": True,
                }))
                assert replaced["ok"] is True, replaced
                assert replaced["replaced"] == old_name
                after = await _outlet_spms(s, "VAV7")
                assert after == [{"type": "OS_SetpointManager_OutdoorAirReset", "name": "SAT Reset"}]
                gone = unwrap(await s.call_tool("get_setpoint_manager_properties", {"setpoint_name": old_name}))
                assert gone["ok"] is False and "not found" in gone["error"]
    asyncio.run(_run())


def test_different_control_variables_coexist_without_flag():
    # Validates: a HumidityRatio SPM next to the Temperature SPM needs no replace_existing —
    # only same-control-variable pairs collide
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys7(s, _unique())
                await _schedule(s, "Hum Sched", 0.008, "Fractional")
                before = await _outlet_spms(s, "VAV7")
                res = unwrap(await s.call_tool("add_setpoint_manager", {
                    "spm_type": "SetpointManagerScheduled", "name": "Hum SPM",
                    "air_loop_name": "VAV7", "schedule_name": "Hum Sched",
                    "control_variable": "HumidityRatio",
                }))
                assert res["ok"] is True, res
                assert res["control_variable"] == "HumidityRatio"
                assert res["replaced"] is None
                assert sorted(res["setpoint_managers_on_node"]) == sorted([before[0]["name"], "Hum SPM"])
    asyncio.run(_run())


# ── refusals ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("args", "needle"), [
    ({"spm_type": "SetpointManagerScheduled", "air_loop_name": "VAV7", "node": "supply_inlet"},
     "requires schedule_name"),
    ({"spm_type": "SetpointManagerScheduledDualSetpoint", "air_loop_name": "VAV7", "node": "supply_inlet",
      "cooling_schedule_name": "SAT Sched"}, "requires heating_schedule_name"),
    ({"spm_type": "SetpointManagerSingleZoneReheat", "air_loop_name": "VAV7", "node": "supply_inlet"},
     "requires control_zone_name"),
    ({"spm_type": "SetpointManagerWarmest", "plant_loop_name": "<hw>"}, "air-loop only"),
    ({"spm_type": "SetpointManagerScheduled", "schedule_name": "SAT Sched"}, "exactly one of"),
    ({"spm_type": "SetpointManagerScheduled", "schedule_name": "SAT Sched", "air_loop_name": "VAV7",
      "plant_loop_name": "<hw>"}, "exactly one of"),
    ({"spm_type": "SetpointManagerScheduled", "schedule_name": "Nope", "air_loop_name": "VAV7",
      "node": "supply_inlet"}, "Schedule 'Nope' not found"),
    ({"spm_type": "SetpointManagerOutdoorAirReset", "plant_loop_name": "<hw>", "node": "mixed_air"},
     "only exists on an air loop"),
    ({"spm_type": "SetpointManagerOutdoorAirReset", "air_loop_name": "VAV7", "after_component": "Nope"},
     "not found on the supply side"),
    ({"spm_type": "SetpointManagerBogus", "air_loop_name": "VAV7"}, "Unknown spm_type"),
    ({"spm_type": "SetpointManagerWarmest", "air_loop_name": "VAV7", "node": "supply_inlet",
      "control_variable": "HumidityRatio"}, "only settable on SetpointManagerScheduled"),
])
def test_add_refusals_name_the_problem(args, needle):
    # Validates: every refusal names the missing arg / bad target, and creates nothing
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                _zones, hw, _chw = await _sys7(s, _unique())
                await _schedule(s, "SAT Sched", 12.8)
                call = {"name": "Bad SPM", **{k: (hw if v == "<hw>" else v) for k, v in args.items()}}
                res = unwrap(await s.call_tool("add_setpoint_manager", call))
                assert res["ok"] is False, res
                assert needle in res["error"], res["error"]
                gone = unwrap(await s.call_tool("get_setpoint_manager_properties", {"setpoint_name": "Bad SPM"}))
                assert gone["ok"] is False, "refusal must not create the SPM"
    asyncio.run(_run())


# ── remove ───────────────────────────────────────────────────────────────

def test_remove_leaves_other_spms_on_node():
    # Validates: removing one SPM reports the node and the exact survivors; no warning when a
    # Temperature SPM still controls the outlet
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys7(s, _unique())
                await _schedule(s, "Hum Sched", 0.008, "Fractional")
                keep = (await _outlet_spms(s, "VAV7"))[0]["name"]
                unwrap(await s.call_tool("add_setpoint_manager", {
                    "spm_type": "SetpointManagerScheduled", "name": "Hum SPM", "air_loop_name": "VAV7",
                    "schedule_name": "Hum Sched", "control_variable": "HumidityRatio",
                }))
                res = unwrap(await s.call_tool("remove_setpoint_manager", {"name": "Hum SPM"}))
                assert res["ok"] is True, res
                assert res["removed"] == "Hum SPM" and res["spm_type"] == "SetpointManagerScheduled"
                assert res["remaining_on_node"] == [keep]
                assert "warnings" not in res
                assert [m["name"] for m in await _outlet_spms(s, "VAV7")] == [keep]
    asyncio.run(_run())


def test_remove_only_temperature_spm_on_outlet_warns():
    # Validates: deleting the last Temperature SPM on a loop supply outlet succeeds but warns —
    # EnergyPlus refuses to simulate a loop without one
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys7(s, _unique())
                only = (await _outlet_spms(s, "VAV7"))[0]["name"]
                res = unwrap(await s.call_tool("remove_setpoint_manager", {"name": only}))
                assert res["ok"] is True, res
                assert res["remaining_on_node"] == []
                assert "no Temperature setpoint manager" in res["warnings"][0]
                assert "VAV7" in res["warnings"][0]
                assert await _outlet_spms(s, "VAV7") == []
                missing = unwrap(await s.call_tool("remove_setpoint_manager", {"name": only}))
                assert missing["ok"] is False and "not found" in missing["error"]
    asyncio.run(_run())


# ── in-process: node placement ───────────────────────────────────────────

@pytest.fixture
def inproc_loop(tmp_path: Path):
    """Empty model in model_manager + air loop  Clg → Htg → Fan  with a coil to anchor on."""
    if not os.environ.get("RUN_OPENSTUDIO_INTEGRATION"):
        pytest.skip("requires OpenStudio")
    import openstudio

    from mcp_server.model_manager import clear_model, load_model

    osm = tmp_path / "spm.osm"
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


def test_after_component_places_spm_on_that_outlet_node(inproc_loop):
    # Validates: after_component=<coil> resolves the coil's OUTLET node (the node between it
    # and the next component), not the loop outlet
    from mcp_server.skills.loop_operations.setpoint_managers import add_setpoint_manager
    model, loop = inproc_loop
    clg = model.getCoilCoolingDXSingleSpeedByName("Clg").get()
    clg_outlet = clg.outletModelObject().get().to_Node().get()

    res = add_setpoint_manager("SetpointManagerOutdoorAirReset", "Coil Leaving SPM",
                               air_loop_name="Loop", after_component="Clg")

    assert res["ok"] is True, res
    assert res["node_name"] == clg_outlet.nameString()
    spm = model.getSetpointManagerOutdoorAirResetByName("Coil Leaving SPM").get()
    assert spm.setpointNode().get().handle() == clg_outlet.handle()
    assert loop.supplyOutletNode().setpointManagers().__len__() == 0, "loop outlet untouched"


def test_replace_existing_deletes_exactly_the_colliding_spm(inproc_loop):
    # Regression: the SDK deletes the colliding SPM from the MODEL, not just the node; the
    # tool must report it and leave a different-control-variable neighbour alone
    import openstudio

    from mcp_server.skills.loop_operations.setpoint_managers import add_setpoint_manager
    model, loop = inproc_loop
    outlet = loop.supplyOutletNode()
    sch = openstudio.model.ScheduleConstant(model)
    sch.setValue(12.8)
    temp = openstudio.model.SetpointManagerScheduled(model, sch)
    temp.setName("Old Temp")
    assert temp.addToNode(outlet)
    hum = openstudio.model.SetpointManagerScheduled(model, sch)
    hum.setName("Hum")
    assert hum.setControlVariable("HumidityRatio") and hum.addToNode(outlet)

    res = add_setpoint_manager("SetpointManagerWarmest", "Warmest", air_loop_name="Loop",
                               replace_existing=True)

    assert res["ok"] is True, res
    assert res["replaced"] == "Old Temp"
    assert sorted(res["setpoint_managers_on_node"]) == ["Hum", "Warmest"]
    assert not model.getObject(temp.handle()).is_initialized(), "old Temperature SPM is gone"
    assert model.getObject(hum.handle()).is_initialized(), "HumidityRatio neighbour survives"


# ── refusals must not leave orphans (review finding) ─────────────────────

@pytest.mark.parametrize(("call", "needle", "obj_type"), [
    ({"spm_type": "SetpointManagerScheduled", "schedule_name": "Frac Sched"},
     "type limits incompatible with control variable 'Temperature'", "SetpointManagerScheduled"),
    ({"spm_type": "SetpointManagerScheduled", "schedule_name": "SAT Sched", "control_variable": "Bogus"},
     "not a valid control variable", "SetpointManagerScheduled"),
    ({"spm_type": "SetpointManagerScheduledDualSetpoint", "cooling_schedule_name": "Frac Sched",
      "heating_schedule_name": "SAT Sched"},
     "'Frac Sched' is not a temperature schedule (cooling_schedule_name)", "SetpointManagerScheduledDualSetpoint"),
    ({"spm_type": "SetpointManagerScheduledDualSetpoint", "cooling_schedule_name": "SAT Sched",
      "heating_schedule_name": "Frac Sched"},
     "'Frac Sched' is not a temperature schedule (heating_schedule_name)", "SetpointManagerScheduledDualSetpoint"),
])
def test_schedule_type_refusals_leave_no_orphan_spm(call, needle, obj_type):
    # Regression: SetpointManagerScheduled's constructor throws on a schedule whose type limits
    # do not fit the control variable and leaves the half-built SPM in the model; the dual
    # setpoint setters return False and leave the slot empty (probe_spm_ctor_orphan.py). The
    # tool must roll back so a refusal leaves the SPM count unchanged
    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await _sys7(s, _unique())
                await _schedule(s, "SAT Sched", 12.8)
                await _schedule(s, "Frac Sched", 0.5, "Fractional")
                before = unwrap(await s.call_tool("list_model_objects", {"object_type": obj_type, "max_results": 0}))
                res = unwrap(await s.call_tool("add_setpoint_manager", {
                    "name": "Orphan?", "air_loop_name": "VAV7", "node": "supply_inlet", **call,
                }))
                assert res["ok"] is False, res
                assert needle in res["error"], res["error"]
                after = unwrap(await s.call_tool("list_model_objects", {"object_type": obj_type, "max_results": 0}))
                assert after["count"] == before["count"], (
                    f"refusal left {after['count'] - before['count']} orphan {obj_type}(s)"
                )
    asyncio.run(_run())
