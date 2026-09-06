"""Manual SDK-behaviour probes — NOT run in CI.

Run by hand inside the Docker image when bumping OPENSTUDIO_VERSION
(docker/Dockerfile, tests/test_versions.py):

    pytest -m sdk_probe tests/test_sdk_probes.py -v

These pin behaviour the served docs and wiring recipes describe as fact. If a
probe stops behaving as asserted after a bump, update the text it guards, not
the probe: `replace_supply_branch_component` in
mcp_server/skills/api_reference/wiring_recipes.py (+ its HAZARDS entry),
.claude/skills/measure-authoring/SKILL.md and
.claude/skills/openstudio-patterns/SKILL.md (issue #149).

Why not CI: the crash case is undefined behaviour (use-after-delete inside the
SDK). It reproduced 2/2 on 3.11.0 but a flaky CI test is worse than none. The
`integration` marker keeps it out of the unit job; no ci.yml shard lists it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.sdk_probe]

# Wrong order: capture the outlet node, remove() the coil (which deletes that
# node), then addToNode on the dangling handle. From dev/issue149-probes/probe_crash.rb.
CRASH_RB = """\
require 'openstudio'
m = OpenStudio::Model::Model.new
loop = OpenStudio::Model::AirLoopHVAC.new(m)
s = m.alwaysOnDiscreteSchedule
fan = OpenStudio::Model::FanVariableVolume.new(m, s); fan.addToNode(loop.supplyInletNode)
clg = OpenStudio::Model::CoilCoolingDXSingleSpeed.new(m); clg.setName('Clg'); clg.addToNode(loop.supplyInletNode)
outlet = clg.outletModelObject.get.to_Node.get
clg.remove
newc = OpenStudio::Model::CoilCoolingDXTwoSpeed.new(m)
puts "MARK: calling addToNode on node captured before remove"
$stdout.flush
r = newc.addToNode(outlet)
puts "MARK: survived, result=#{r}"
"""

# Safe order: the recipe body from wiring_recipes.py wrapped in a minimal loop.
# `{seq}` is the append order, so the last name in it is last before
# supplyOutletNode — the position where remove() deletes the INLET node instead.
SAFE_RB_PREFIX = """\
require 'openstudio'
model = OpenStudio::Model::Model.new
loop = OpenStudio::Model::AirLoopHVAC.new(model)
loop.setName('Loop')
s = model.alwaysOnDiscreteSchedule
fan = OpenStudio::Model::FanVariableVolume.new(model, s); fan.setName('Fan')
clg = OpenStudio::Model::CoilCoolingDXSingleSpeed.new(model); clg.setName('Main Cooling Coil')
htg = OpenStudio::Model::CoilHeatingElectric.new(model, s); htg.setName('Htg')
[{seq}].each { |c| c.addToNode(loop.supplyOutletNode) }
sch = OpenStudio::Model::ScheduleConstant.new(model); sch.setValue(12.8)
spm = OpenStudio::Model::SetpointManagerScheduled.new(model, sch); spm.addToNode(loop.supplyOutletNode)
order = ->{ loop.supplyComponents.reject{|c| c.to_Node.is_initialized}.map{|c| c.nameString} }
before = order.call
"""
SAFE_RB_SUFFIX = """
after = order.call
raise "order changed: #{before} -> #{after}" unless before == after
raise "new coil not on loop" unless new_coil.airLoopHVAC.is_initialized
raise "name not reused" unless new_coil.nameString == 'Main Cooling Coil'
raise "inlet node lost" unless model.getObject(inlet_node.handle).is_initialized
raise "new coil inlet moved" unless new_coil.inletModelObject.get.handle == inlet_node.handle
raise "SPM on outlet lost" unless loop.supplyOutletNode.setpointManagers.size == 1
ft = OpenStudio::EnergyPlus::ForwardTranslator.new
ft.translateModel(model)
raise "forward translate errors: #{ft.errors.map(&:logMessage)}" unless ft.errors.empty?
puts "SAFE_OK"
"""


def _run_ruby(script: str) -> subprocess.CompletedProcess:
    if shutil.which("openstudio") is None:
        pytest.skip("openstudio CLI not on PATH — run inside the Docker image")
    tmp = Path(tempfile.mkdtemp(prefix="sdk_probe_"))
    try:
        rb = tmp / "probe.rb"
        rb.write_text(script, encoding="utf-8")
        cmd = ["openstudio", "execute_ruby_script", str(rb)]  # CLI from the image's PATH
        return subprocess.run(  # noqa: S603 - fixed argv
            cmd,
            capture_output=True, text=True, timeout=120, check=False,
            cwd=str(tmp), env=os.environ.copy(),
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_addToNode_after_remove_crashes_ruby():
    # Validates: the #149 hazard text ("[BUG] Segmentation fault ... exit 134, no exception")
    # still describes what the SDK does; if this passes with exit 0 the warning is stale
    proc = _run_ruby(CRASH_RB)
    out = proc.stdout + proc.stderr
    assert "MARK: calling addToNode" in out, out[-2000:]
    assert "MARK: survived" not in out, "SDK no longer crashes — soften the #149 warnings"
    # Ruby's crash handler abort()s: a shell reports 134, Python's subprocess reports the
    # raw signal (-6). Both are SIGABRT.
    assert proc.returncode in (-6, 134), f"expected SIGABRT from Ruby's crash handler, got {proc.returncode}"
    assert "[BUG] Segmentation fault" in out
    assert "addToNode" in out, "crash report should name addToNode in the control frames"


@pytest.mark.parametrize("seq", ["fan, clg, htg", "fan, htg, clg"], ids=["coil_mid_branch", "coil_last"])
def test_replace_recipe_safe_order_runs_clean(seq):
    # Validates: the recipe body shipped in wiring_recipes.py runs verbatim with exit 0 in
    # both branch positions — mid-branch (remove() deletes the old OUTLET node) and last
    # before supplyOutletNode (remove() deletes the old INLET node, i.e. the new component's
    # outlet; the SDK splices it to the loop outlet) — keeping order, name, the captured inlet
    # node, the outlet-node SPM, and a clean forward translation
    from mcp_server.skills.api_reference.wiring_recipes import RECIPES
    body = RECIPES["replace_supply_branch_component"]["ruby"]
    proc = _run_ruby(SAFE_RB_PREFIX.replace("{seq}", seq) + body + SAFE_RB_SUFFIX)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
    assert "SAFE_OK" in proc.stdout
