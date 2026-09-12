"""Unit tests for mcp_server.skills.weather.zone_heating_setpoints.

Pure Python — no `openstudio`, no Docker. The module only calls a handful of methods on
thermal zones, thermostats and schedules, so lightweight fakes exercise the real branching.
Same tier and same rationale as tests/test_gbxml_zone_checks.py.

The fakes mirror OpenStudio 3.11.0 behaviour observed in a probe: a ScheduleRuleset with a
21.1 C occupied default and a 15.6 C setback rule reads back as
defaultDaySchedule().values() == [21.1] and scheduleRules()[0].daySchedule().values() == [15.6].
"""
from __future__ import annotations

import pytest

from mcp_server.skills.weather.zone_heating_setpoints import zone_heating_setpoints

pytestmark = pytest.mark.unit


class _FakeOptional:
    def __init__(self, value=None):
        self._value = value

    def is_initialized(self) -> bool:
        return self._value is not None

    def get(self):
        return self._value


class _FakeDaySchedule:
    def __init__(self, values):
        self._values = values

    def values(self):
        return self._values


class _FakeRule:
    def __init__(self, values):
        self._day = _FakeDaySchedule(values)

    def daySchedule(self):
        return self._day


class _FakeScheduleRuleset:
    """A ScheduleRuleset-shaped object. `rules` are the setback day values."""

    def __init__(self, default_values, rules=()):
        self._default = _FakeDaySchedule(list(default_values))
        self._rules = [_FakeRule(list(v)) for v in rules]

    def defaultDaySchedule(self):
        return self._default

    def scheduleRules(self):
        return self._rules

    def to_ScheduleRuleset(self):
        return _FakeOptional(self)

    def to_ScheduleConstant(self):
        return _FakeOptional(None)


class _FakeScheduleConstant:
    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def to_ScheduleRuleset(self):
        return _FakeOptional(None)

    def to_ScheduleConstant(self):
        return _FakeOptional(self)


class _FakeScheduleCompact:
    """Neither castable type — the ScheduleCompact / ScheduleYear case."""

    def to_ScheduleRuleset(self):
        return _FakeOptional(None)

    def to_ScheduleConstant(self):
        return _FakeOptional(None)


class _FakeThermostat:
    def __init__(self, heating_schedule=None):
        self._schedule = _FakeOptional(heating_schedule)

    def heatingSetpointTemperatureSchedule(self):
        return self._schedule


class _FakeThermalZone:
    def __init__(self, name, thermostat=None):
        self._name = name
        self._thermostat = _FakeOptional(thermostat)

    def nameString(self):
        return self._name

    def thermostatSetpointDualSetpoint(self):
        return self._thermostat


class _FakeModel:
    def __init__(self, zones):
        self._zones = zones

    def getThermalZones(self):
        return self._zones


def _zone(name, value=None, rules=(), schedule=None):
    if schedule is None and value is not None:
        schedule = _FakeScheduleRuleset([value], rules)
    return _FakeThermalZone(name, _FakeThermostat(schedule) if schedule else None)


def test_mean_across_zones_with_constant_schedules():
    # Validates: the unweighted mean, and that min/max travel with it so a caller can judge
    zones = [
        _FakeThermalZone("A", _FakeThermostat(_FakeScheduleConstant(20.0))),
        _FakeThermalZone("B", _FakeThermostat(_FakeScheduleConstant(21.0))),
        _FakeThermalZone("C", _FakeThermostat(_FakeScheduleConstant(22.0))),
    ]

    result = zone_heating_setpoints(_FakeModel(zones))

    assert result["mean_c"] == 21.0
    assert result["min_c"] == 20.0
    assert result["max_c"] == 22.0
    assert result["zone_count"] == 3
    assert result["zones_skipped"] == []
    assert result["skip_reason"] is None
    assert result["method"] == "schedule_max_per_zone"


def test_ruleset_uses_the_occupied_maximum_not_the_setback():
    # Regression: a 21.1/15.6 setback schedule must yield 21.1. Averaging the two gives
    # 18.35, which would push every derived ground temperature ~3 K too low on every real
    # model — the single most likely silent error in this feature.
    zones = [_zone("Office", 21.1, rules=([15.6],))]

    result = zone_heating_setpoints(_FakeModel(zones))

    assert result["mean_c"] == 21.1
    assert result["setpoints_c"] == [("Office", 21.1)]


def test_setback_higher_than_default_still_takes_the_maximum():
    # Validates: the rule is "max over every day schedule", not "the default day"
    zones = [_zone("Odd", 18.0, rules=([22.5],))]

    assert zone_heating_setpoints(_FakeModel(zones))["mean_c"] == 22.5


def test_zone_without_a_thermostat_is_skipped_and_named():
    # Validates: an unconditioned zone (no dual-setpoint thermostat) is excluded from the mean
    # and counts, and named in zones_skipped with its reason rather than dropped silently
    zones = [
        _FakeThermalZone("Conditioned", _FakeThermostat(_FakeScheduleConstant(21.0))),
        _FakeThermalZone("Corridor", None),
    ]

    result = zone_heating_setpoints(_FakeModel(zones))

    assert result["mean_c"] == 21.0
    assert result["zone_count"] == 1
    assert result["zones_with_thermostat"] == 1
    assert result["zones_skipped"] == [{"zone": "Corridor", "reason": "no dual-setpoint thermostat"}]


def test_thermostat_without_a_heating_schedule_is_skipped():
    # Validates: a cooling-only thermostat is counted as present but yields no setpoint
    zones = [_FakeThermalZone("CoolOnly", _FakeThermostat(None))]

    result = zone_heating_setpoints(_FakeModel(zones))

    assert result["mean_c"] is None
    assert result["zones_with_thermostat"] == 1
    assert result["zones_skipped"] == [
        {"zone": "CoolOnly", "reason": "thermostat has no heating setpoint schedule"},
    ]
    assert result["skip_reason"] == "no zone has a readable heating setpoint schedule"


def test_unsupported_schedule_type_is_skipped_not_guessed():
    # Validates: ScheduleCompact / ScheduleYear are reported, never approximated
    zones = [_FakeThermalZone("Compact", _FakeThermostat(_FakeScheduleCompact()))]

    result = zone_heating_setpoints(_FakeModel(zones))

    assert result["mean_c"] is None
    assert "unsupported schedule type" in result["zones_skipped"][0]["reason"]


def test_empty_ruleset_is_skipped():
    # Validates: a ScheduleRuleset whose day schedules carry no values is skipped with a
    # specific reason — max() over an empty list must not raise or yield a bogus setpoint
    zones = [_FakeThermalZone("Empty", _FakeThermostat(_FakeScheduleRuleset([])))]

    result = zone_heating_setpoints(_FakeModel(zones))

    assert result["mean_c"] is None
    assert result["zones_skipped"][0]["reason"] == "schedule ruleset carries no values"


def test_model_with_no_thermostats_reports_that_specific_reason():
    # Validates: the caller must be able to distinguish "no thermostats" from "unreadable
    # schedules" — they lead to different advice
    zones = [_FakeThermalZone("A", None), _FakeThermalZone("B", None)]

    result = zone_heating_setpoints(_FakeModel(zones))

    assert result["mean_c"] is None
    assert result["zones_with_thermostat"] == 0
    assert result["skip_reason"] == "no thermostat in the model"


def test_model_with_no_zones_at_all():
    # Validates: a zone-less model (fresh or geometry-only) returns mean_c=None, zone_count=0
    # and the "no thermostat" skip reason instead of a division-by-zero or a crash
    result =zone_heating_setpoints(_FakeModel([]))

    assert result["mean_c"] is None
    assert result["zone_count"] == 0
    assert result["skip_reason"] == "no thermostat in the model"


def test_implausible_setpoint_is_skipped_with_the_value_named():
    # Validates: a 60 C "setpoint" is a unit bug; it must not drag the mean
    zones = [
        _FakeThermalZone("Sane", _FakeThermostat(_FakeScheduleConstant(21.0))),
        _FakeThermalZone("Broken", _FakeThermostat(_FakeScheduleConstant(60.0))),
    ]

    result = zone_heating_setpoints(_FakeModel(zones))

    assert result["mean_c"] == 21.0
    assert result["zones_skipped"] == [
        {"zone": "Broken", "reason": "implausible heating setpoint 60.0 C"},
    ]


def test_wide_setpoint_spread_is_warned_but_still_averaged():
    # Validates: a warehouse-plus-cleanroom model still returns a number, with the spread
    # surfaced so nobody mistakes the mean for a description of the building
    zones = [
        _FakeThermalZone("Warehouse", _FakeThermostat(_FakeScheduleConstant(10.0))),
        _FakeThermalZone("Lab", _FakeThermostat(_FakeScheduleConstant(24.0))),
    ]

    result = zone_heating_setpoints(_FakeModel(zones))

    assert result["mean_c"] == 17.0
    assert "span 14.0 K" in result["spread_warning"]


def test_narrow_spread_produces_no_warning():
    # Validates: the spread warning has a threshold — a 2 K span between zones is ordinary and
    # must not produce noise that trains callers to ignore spread_warning
    zones = [
        _FakeThermalZone("A", _FakeThermostat(_FakeScheduleConstant(20.0))),
        _FakeThermalZone("B", _FakeThermostat(_FakeScheduleConstant(22.0))),
    ]

    assert zone_heating_setpoints(_FakeModel(zones))["spread_warning"] is None
