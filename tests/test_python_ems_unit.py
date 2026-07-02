"""Unit tests for Python EMS codegen, validation, and .edd parsing.

Pure-Python targets (templates.py, edd_parser.py) — no openstudio import,
no MCP server, runnable outside Docker.
"""
from __future__ import annotations

import pytest

from mcp_server.skills.python_ems.edd_parser import parse_edd
from mcp_server.skills.python_ems.templates import (
    CALLING_POINTS,
    build_schedule_override_source,
    build_zone_metric_source,
    global_name_for,
    normalize_rules,
    safe_module_name,
    validate_plugin_source,
)

pytestmark = pytest.mark.unit

_EDD_SAMPLE = """! Program Version, EnergyPlus, Version 25.2.0-cf7368216c
! <EnergyManagementSystem:Actuator Available>, Component Unique Name, Component Type,  Control Type, Units
EnergyManagementSystem:Actuator Available,ALWAYS ON DISCRETE,Schedule:Constant,Schedule Value,[ ]
EnergyManagementSystem:Actuator Available,ZONE ONE,Zone,Outdoor Air Drybulb Temperature,[C]
! <EnergyManagementSystem:InternalVariable Available>, Unique Name, Internal Data Type, Units
EnergyManagementSystem:InternalVariable Available,SPACE 1 PEOPLE 1,People Count Design Level,[each]
"""


def test_parse_edd_exact_triples():
    # Validates: .edd actuator/internal-variable lines parse into exact field dicts,
    # comment lines skipped, [units] brackets stripped
    parsed = parse_edd(_EDD_SAMPLE)
    assert parsed["actuators"] == [
        {"actuator_key": "ALWAYS ON DISCRETE", "component_type": "Schedule:Constant",
         "control_type": "Schedule Value", "units": ""},
        {"actuator_key": "ZONE ONE", "component_type": "Zone",
         "control_type": "Outdoor Air Drybulb Temperature", "units": "C"},
    ]
    assert parsed["internal_variables"] == [
        {"key": "SPACE 1 PEOPLE 1", "type": "People Count Design Level", "units": "each"},
    ]


def test_calling_points_complete():
    # Validates: the callback whitelist matches the 18 EnergyPlusPlugin callbacks —
    # a typo'd or dropped name would silently reject valid plugins
    assert len(CALLING_POINTS) == 18
    assert "on_begin_timestep_before_predictor" in CALLING_POINTS
    assert "on_user_defined_component_model" in CALLING_POINTS


@pytest.mark.parametrize(("raw", "expected"), [
    ("Avg Zone Temp", "avg_zone_temp"),
    ("2nd metric!", "plugin_2nd_metric"),
    ("", "plugin"),
])
def test_safe_module_name(raw, expected):
    # Validates: plugin names become importable module stems (E+ imports by stem)
    assert safe_module_name(raw) == expected


def test_global_name_for_strips_specials():
    # Validates: output variable names map to global identifiers usable in code
    assert global_name_for("Average Zone Temperature") == "Average_Zone_Temperature"


def test_zone_metric_volume_weighted_source_valid():
    # Validates: volume-weighted codegen compiles, fetches Zone Air Volume handles,
    # and passes its own contract validation with the right callback
    source = build_zone_metric_source(
        "ZoneMetricAggregate", "Zone Mean Air Temperature", [],
        "volume_weighted_average", "Avg_Temp")
    compile(source, "<generated>", "exec")
    assert 'get_object_names(state, "Zone")' in source
    assert '"Zone Air Volume"' in source
    assert "sum(v * t for v, t in zip(self.volumes, values)) / sum(self.volumes)" in source
    result = validate_plugin_source(source, "ZoneMetricAggregate")
    assert result["ok"] is True, result["errors"]
    assert result["callbacks"] == ["on_end_of_zone_timestep_before_zone_reporting"]


def test_zone_metric_baked_zone_names():
    # Validates: explicit zone_names are baked as a literal (no dynamic discovery)
    # and non-volume aggregations skip the Zone Air Volume lookup entirely
    source = build_zone_metric_source(
        "ZoneMetricAggregate", "Zone Mean Air Temperature",
        ["Core Zone", "Perimeter Zone"], "max", "Max_Temp")
    compile(source, "<generated>", "exec")
    assert "zone_names = ['Core Zone', 'Perimeter Zone']" in source
    assert "Zone Air Volume" not in source
    assert "result = max(values)" in source


def test_zone_metric_rejects_unknown_aggregation():
    # Validates: aggregation typos fail fast instead of generating broken code
    with pytest.raises(ValueError, match="aggregation"):
        build_zone_metric_source("C", "Zone Mean Air Temperature", [], "median", "G")


def test_schedule_override_source_valid():
    # Validates: rule codegen produces a first-match-wins if/elif chain with the
    # EnergyPlus day-of-week convention (1=Sunday) and passes contract validation
    rules = normalize_rules([
        {"days": "weekdays", "start_hour": 5, "end_hour": 19, "value": 21.0},
        {"days": ["saturday"], "start_hour": 6, "end_hour": 12, "value": 18.0},
    ])
    source = build_schedule_override_source(
        "ScheduleOverride", "Htg Sched", "Schedule:Constant", rules, 15.6, "Applied")
    compile(source, "<generated>", "exec")
    assert "if day_of_week in (2, 3, 4, 5, 6) and 5 <= hour < 19:" in source
    assert "elif day_of_week == 7 and 6 <= hour < 12:" in source
    assert "value = 15.6" in source
    assert "state, 'Schedule:Constant', \"Schedule Value\", 'Htg Sched')" in source
    result = validate_plugin_source(source, "ScheduleOverride")
    assert result["ok"] is True, result["errors"]
    assert result["callbacks"] == ["on_begin_timestep_before_predictor"]


def test_normalize_rules_accepts_json_string():
    # Regression-proofing for CLAUDE.md rule 13: MCP clients may send lists as JSON strings
    rules = normalize_rules('[{"days": "weekends", "start_hour": 8, "end_hour": 20, "value": 24}]')
    assert rules == [{"days": (1, 7), "start_hour": 8, "end_hour": 20, "value": 24.0}]


@pytest.mark.parametrize(("bad", "match"), [
    ([], "non-empty"),
    ([{"days": "all", "start_hour": 0, "end_hour": 24, "value": 1}], "default_value"),
    ([{"days": "tuesdays", "start_hour": 1, "end_hour": 2, "value": 1}], "unknown"),
    ([{"days": "all", "start_hour": 9, "end_hour": 9, "value": 1}], "start_hour < end_hour"),
    ([{"days": "all", "start_hour": 1, "end_hour": 2}], "missing 'value'"),
    ("not json", "not valid JSON"),
])
def test_normalize_rules_rejects_bad_input(bad, match):
    # Validates: malformed rules fail with actionable messages instead of
    # generating a plugin that silently misbehaves
    with pytest.raises(ValueError, match=match):
        normalize_rules(bad)


def test_validate_plugin_source_syntax_error_line():
    # Validates: syntax errors report the line number for quick agent repair
    result = validate_plugin_source("class Broken(EnergyPlusPlugin)\n    pass\n", "Broken")
    assert result["ok"] is False
    assert "syntax error at line 1" in result["errors"][0]


def test_validate_plugin_source_missing_class():
    # Validates: a class_name not present in the source is rejected with the
    # classes that WERE found (typo diagnosis)
    result = validate_plugin_source(
        "from pyenergyplus.plugin import EnergyPlusPlugin\n"
        "class Actual(EnergyPlusPlugin):\n"
        "    def on_begin_timestep_before_predictor(self, state):\n"
        "        return 0\n",
        "Wrong")
    assert result["ok"] is False
    assert "'Wrong' not found" in result["errors"][0]
    assert "Actual" in result["errors"][0]


def test_validate_plugin_source_wrong_base_and_typo_callback():
    # Validates: missing EnergyPlusPlugin base and a typo'd on_* callback are both
    # caught — EnergyPlus would otherwise fail at runtime or silently never call it
    result = validate_plugin_source(
        "class Rogue:\n"
        "    def on_begin_timestep(self, state):\n"
        "        return 0\n",
        "Rogue")
    assert result["ok"] is False
    joined = "\n".join(result["errors"])
    assert "must inherit EnergyPlusPlugin" in joined
    assert "'on_begin_timestep' is not an EnergyPlusPlugin callback" in joined


def test_validate_plugin_source_no_callback():
    # Validates: a plugin class overriding nothing is rejected (it would never run)
    result = validate_plugin_source(
        "from pyenergyplus.plugin import EnergyPlusPlugin\n"
        "class Idle(EnergyPlusPlugin):\n"
        "    pass\n",
        "Idle")
    assert result["ok"] is False
    assert "overrides no plugin callback" in result["errors"][0]
