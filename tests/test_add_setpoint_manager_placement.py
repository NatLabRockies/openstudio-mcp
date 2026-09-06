"""In-process node-placement tests for add_setpoint_manager (follow-up to #148).

Split from test_add_setpoint_manager.py (stdio contract tests) to stay under the
file-size limit. These call the operation directly because they assert on the
SPM's setpointNode() handle and on object handles the SDK deletes.
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
