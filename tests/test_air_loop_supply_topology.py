"""In-process topology tests for the air-loop supply-branch tools (#148).

Split from test_air_loop_supply.py (stdio contract tests) to stay under the file-size
limit. These call the operations directly because they need an SPM placed on a mid-branch
node, a plant demand branch to count, or a second HVAC component to collide with — none
of which the stdio fixtures set up.

SDK facts these rest on (dev/issue149-probes/, OpenStudio 3.11.0): remove() deletes the
component's OUTLET node (its INLET node when it is last before supplyOutletNode) and any
SetpointManager on it; SetpointManager.addToNode silently deletes an existing
same-control-variable SPM on the target node; remove() on a water coil also removes its
plant demand branch; setName on a name held by ANY other HVAC component silently appends
' 1' (probe_name_lookup.py).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import integration_enabled

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not integration_enabled(), reason="integration disabled"),
]


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


# ── model-wide name collisions (review finding on #148) ───────────────────

def _supply_names(loop) -> list[str]:
    return [c.nameString() for c in loop.supplyComponents() if not c.to_Node().is_initialized()]


def test_add_refuses_name_held_by_component_elsewhere_in_model(inproc_loop):
    # Regression: the SDK keeps HVAC component names unique model-wide and silently renames a
    # collision ('Shared Name' -> 'Shared Name 1'), so a coil named after a boiler on another
    # loop came back under a name the caller never asked for while a name-only
    # set_component_properties kept resolving the boiler. The tool must refuse and build nothing
    import openstudio

    from mcp_server.skills.loop_operations.air_loop_supply import add_air_loop_supply_component
    model, loop = inproc_loop
    boiler = openstudio.model.BoilerHotWater(model)
    boiler.setName("Shared Name")

    res = add_air_loop_supply_component("Loop", "CoilHeatingElectric", "Shared Name")

    assert res["ok"] is False, res
    assert "'Shared Name' is already used by an existing OS_Boiler_HotWater" in res["error"], res["error"]
    assert _supply_names(loop) == ["Clg", "Htg", "Fan"], "refusal must not touch the branch"
    assert len(model.getCoilHeatingElectrics()) == 1, "only the fixture's Htg coil may exist"
    assert len(model.getModelObjectsByName("Shared Name 1", True)) == 0, "no silently renamed coil"


def test_replace_refuses_taken_new_name_but_keeps_old_name_legal(inproc_loop):
    # Regression: same guard on replace — a new_component_name held by any other HVAC component
    # is refused before anything is built, while reusing the OLD component's own name stays
    # legal because the rename happens only after the old one is removed
    import openstudio

    from mcp_server.skills.loop_operations.air_loop_supply import replace_air_loop_supply_component
    model, loop = inproc_loop
    other = openstudio.model.FanOnOff(model, model.alwaysOnDiscreteSchedule())
    other.setName("Other Fan")

    refused = replace_air_loop_supply_component("Loop", "Clg", "CoilCoolingDXTwoSpeed",
                                                new_component_name="Other Fan")

    assert refused["ok"] is False, refused
    assert "'Other Fan' is already used by an existing OS_Fan_OnOff" in refused["error"], refused["error"]
    assert _supply_names(loop) == ["Clg", "Htg", "Fan"], "refusal must not touch the branch"
    assert len(model.getCoilCoolingDXTwoSpeeds()) == 0, "refusal must not build the new coil"

    ok = replace_air_loop_supply_component("Loop", "Clg", "CoilCoolingDXTwoSpeed", new_component_name="Clg")

    assert ok["ok"] is True, ok
    assert ok["added"] == {"name": "Clg", "type": "OS_Coil_Cooling_DX_TwoSpeed"}
    assert _supply_names(loop) == ["Clg", "Htg", "Fan"]
    assert len(model.getCoilCoolingDXSingleSpeeds()) == 0, "old coil removed"
