"""Unit tests for the hvac_only post-check policy (pure Python, no openstudio).

The policy decides which objects an hvac_only swap may touch and diffs two
field snapshots. See plan-hvac-only-non-hvac-preservation.md section 4.4.
"""
import pytest

from mcp_server.skills.comstock.hvac_only_policy import (
    MAX_REPORTED_CHANGES,
    bound_changes,
    classify,
    diff_snapshots,
    is_port_field,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("type_name", [
    "OS:Coil:Cooling:Water",
    "OS:AirTerminal:SingleDuct:VAV:Reheat",
    "OS:AirLoopHVAC",
    "OS:AirLoopHVAC:OutdoorAirSystem",
    "OS:Pump:VariableSpeed",
    "OS:PlantLoop",
    "OS:Sizing:Zone",
    "OS:AvailabilityManager:NightCycle",
    "OS:Curve:Biquadratic",
    "OS:ThermalZone",
])
def test_classify_hvac_types(type_name):
    # Validates: the standards HVAC builder may create/delete/retune these without being reported
    assert classify(type_name) == "hvac"


@pytest.mark.parametrize("type_name", [
    "OS:SpaceInfiltration:DesignFlowRate",
    "OS:Construction:FfactorGroundFloor",
    "OS:ShadingControl",
    "OS:OutputControl:ReportingTolerances",
    "OS:SimulationControl",
    "OS:Surface",
    "OS:Lights",
    "OS:ThermostatSetpoint:DualSetpoint",
    "OS:Schedule:Ruleset",
])
def test_classify_non_hvac_types(type_name):
    # Regression: hvac_only on the SystemD model replaced infiltration, F-factor floors,
    # shading controls and reporting tolerances (session export 2026-11-04); these must be reported
    assert classify(type_name) == "non_hvac"


def test_classify_swh_equipment():
    # Validates: water heaters and pumps on SWH loops are restored, not merely reported
    assert classify("OS:WaterHeater:Mixed") == "swh"
    assert classify("OS:WaterHeater:Stratified") == "swh"
    assert classify("OS:Pump:VariableSpeed", swh_handle=True) == "swh"
    assert classify("OS:Pump:VariableSpeed", swh_handle=False) == "hvac"


@pytest.mark.parametrize(("field_name", "expected"), [
    ("Inlet Port", True),
    ("Outlet Port", True),
    ("Supply Inlet Node Name", True),
    ("Heater Thermal Efficiency", False),
    ("Motor Efficiency", False),
])
def test_is_port_field(field_name, expected):
    # Validates: the SWH restore skips loop-connection fields (new nodes after a swap) and copies the rest
    assert is_port_field(field_name) is expected


def _obj(type_name, name, fields, field_names=None):
    return {
        "type": type_name, "name": name, "fields": list(fields),
        "field_names": list(field_names or [f"F{i}" for i in range(len(fields))]),
    }


def test_diff_reports_removed_changed_added_non_hvac_and_ignores_hvac_churn():
    # Validates: removed/changed/added non-HVAC objects are reported with before/after values,
    # HVAC churn (old loop gone, new coil added) is ignored, new schedules are allowed
    pre = {
        "h-inf": _obj("OS:SpaceInfiltration:DesignFlowRate", "Office Infiltration",
                      ["Office Infiltration", "", "Office", "0.000254"],
                      ["Name", "Schedule Name", "Space or SpaceType Name", "Flow per Exterior Surface Area"]),
        "h-tol": _obj("OS:OutputControl:ReportingTolerances", "", ["", ""],
                      ["Tolerance for Time Heating Setpoint Not Met",
                       "Tolerance for Time Cooling Setpoint Not Met"]),
        "h-loop": _obj("OS:AirLoopHVAC", "DOAS 1", ["DOAS 1", "x"]),
        "h-sch": _obj("OS:Schedule:Ruleset", "Occ", ["Occ", "a"]),
    }
    post = {
        "h-tol": _obj("OS:OutputControl:ReportingTolerances", "", ["0.5556", "0.5556"],
                      ["Tolerance for Time Heating Setpoint Not Met",
                       "Tolerance for Time Cooling Setpoint Not Met"]),
        "h-coil": _obj("OS:Coil:Heating:Water", "VAV HW Coil", ["VAV HW Coil"]),
        "h-ffac": _obj("OS:Construction:FfactorGroundFloor", "Slab F 1.26", ["Slab F 1.26", "1.26"]),
        "h-sch": _obj("OS:Schedule:Ruleset", "Occ", ["Occ", "a"]),
        "h-sch2": _obj("OS:Schedule:Ruleset", "VAV Occ Sch", ["VAV Occ Sch", "b"]),
    }
    changes = diff_snapshots(pre, post)
    kinds = [(c["change"], c["type"], c["name"]) for c in changes]
    assert kinds == [
        ("removed", "OS:SpaceInfiltration:DesignFlowRate", "Office Infiltration"),
        ("changed", "OS:OutputControl:ReportingTolerances", ""),
        ("changed", "OS:OutputControl:ReportingTolerances", ""),
        ("added", "OS:Construction:FfactorGroundFloor", "Slab F 1.26"),
    ], f"diff must report infiltration removal, tolerance edits and F-factor addition only, got {kinds}"
    tol = changes[1]
    assert tol["field_name"] == "Tolerance for Time Heating Setpoint Not Met"
    assert tol["before"] == ""
    assert tol["after"] == "0.5556"


def test_diff_reports_swh_objects_when_restore_did_not_fix_them():
    # Validates: a water heater whose fields still differ after the SWH restore is surfaced
    pre = {"h-wh": _obj("OS:WaterHeater:Mixed", "WH", ["WH", "0.8010961390725"],
                        ["Name", "Heater Thermal Efficiency"])}
    post = {"h-wh": _obj("OS:WaterHeater:Mixed", "WH", ["WH", "0.8013022"],
                         ["Name", "Heater Thermal Efficiency"])}
    changes = diff_snapshots(pre, post)
    assert len(changes) == 1
    assert changes[0]["field_name"] == "Heater Thermal Efficiency"
    assert changes[0]["before"] == "0.8010961390725"
    assert changes[0]["after"] == "0.8013022"


def test_diff_handles_extensible_length_change():
    # Validates: a surface that lost or gained vertex fields is reported as changed, not crashed on
    pre = {"h-s": _obj("OS:Surface", "Wall", ["Wall", "0", "0", "0"], ["Name", "X", "Y", "Z"])}
    post = {"h-s": _obj("OS:Surface", "Wall", ["Wall", "0"], ["Name", "X"])}
    changes = diff_snapshots(pre, post)
    assert [c["field_index"] for c in changes] == [2, 3]
    assert changes[0]["after"] == ""


def test_bound_changes_caps_report():
    # Validates: the response stays bounded (rule 16 spirit) while the total is still reported
    changes = [{"change": "added", "type": "OS:Lights", "name": f"L{i}", "handle": f"h{i}"}
               for i in range(MAX_REPORTED_CHANGES + 7)]
    shown, total = bound_changes(changes)
    assert len(shown) == MAX_REPORTED_CHANGES
    assert total == MAX_REPORTED_CHANGES + 7
