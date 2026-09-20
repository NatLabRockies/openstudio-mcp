"""Read a representative heating setpoint off the model's thermostats.

Exists to feed the `setpoint_offset` derivation in ground_temperatures.py: the EPW's
undisturbed soil temperatures must not go into Site:GroundTemperature:BuildingSurface, and
the documented substitute is a value a couple of degrees below the indoor temperature. That
needs a number, and OpenStudio stores setpoints as *schedules*.

Kept free of `import openstudio` on purpose (CLAUDE.md rule 4). Everything here is a plain
method call on a duck-typed object, so the part most likely to be wrong — which number in a
setback schedule is "the" setpoint — gets unit coverage with fakes and no container. Same
trade gbxml_import/zone_checks.py makes; like that module, this one therefore does NOT
import osm_helpers.is_conditioned_zone (importing it would drag openstudio into the test's
collection).

**The rule: per zone, the MAXIMUM value the heating schedule ever takes.** A real thermostat
is a ScheduleRuleset with a setback — probed on OpenStudio 3.11.0, a 21.1 occupied / 15.6
setback ruleset reads back as defaultDaySchedule().values() == [21.1] and
scheduleRules()[0].daySchedule().values() == [15.6]. Averaging those gives ~18 C for reasons
that have nothing to do with ground physics; the occupied setpoint is the one that
characterises the space above the slab.

Floor-area weighting is deliberately not applied: floor areas are unreliable on exactly the
broken-enclosure models this feature targets (see zero_volume_zone_count in zone_checks.py).
"""
from __future__ import annotations

from typing import Any

# A "setpoint" outside this band is a unit error or a placeholder, not a building.
MIN_PLAUSIBLE_SETPOINT_C = 5.0
MAX_PLAUSIBLE_SETPOINT_C = 35.0

# Above this spread the unweighted mean stops describing any real space; reported, not fatal.
WIDE_SPREAD_K = 8.0


def _schedule_max_value(schedule) -> tuple[float | None, str]:
    """The largest value a heating setpoint schedule ever takes.

    Returns (value, reason). `value` is None when the concrete schedule type is not one we
    can read cheaply, and `reason` then names the shortfall — never a guess.
    """
    ruleset = schedule.to_ScheduleRuleset()
    if ruleset.is_initialized():
        rs = ruleset.get()
        values: list[float] = list(rs.defaultDaySchedule().values())
        for rule in rs.scheduleRules():
            values.extend(rule.daySchedule().values())
        if not values:
            return None, "schedule ruleset carries no values"
        return max(values), "schedule_ruleset_max"

    constant = schedule.to_ScheduleConstant()
    if constant.is_initialized():
        return constant.get().value(), "schedule_constant"

    return None, "unsupported schedule type (not a ScheduleRuleset or ScheduleConstant)"


def _zone_heating_setpoint(zone) -> tuple[float | None, str]:
    """(setpoint, reason) for one thermal zone. None when nothing usable is attached."""
    thermostat = zone.thermostatSetpointDualSetpoint()
    if not thermostat.is_initialized():
        return None, "no dual-setpoint thermostat"

    schedule = thermostat.get().heatingSetpointTemperatureSchedule()
    if not schedule.is_initialized():
        return None, "thermostat has no heating setpoint schedule"

    value, reason = _schedule_max_value(schedule.get())
    if value is None:
        return None, reason
    if not MIN_PLAUSIBLE_SETPOINT_C <= value <= MAX_PLAUSIBLE_SETPOINT_C:
        return None, f"implausible heating setpoint {value} C"
    return value, reason


def zone_heating_setpoints(model) -> dict[str, Any]:
    """Per-zone design heating setpoints and their unweighted mean.

    `mean_c` is None when no zone yielded a usable setpoint; `skip_reason` then says why in
    one line, so a caller can report it rather than inventing a temperature.
    """
    setpoints: list[tuple[str, float]] = []
    skipped: list[dict[str, str]] = []
    zones_with_thermostat = 0

    for zone in model.getThermalZones():
        name = zone.nameString()
        if zone.thermostatSetpointDualSetpoint().is_initialized():
            zones_with_thermostat += 1
        value, reason = _zone_heating_setpoint(zone)
        if value is None:
            skipped.append({"zone": name, "reason": reason})
            continue
        setpoints.append((name, value))

    result: dict[str, Any] = {
        "setpoints_c": setpoints,
        "zone_count": len(setpoints),
        "zones_with_thermostat": zones_with_thermostat,
        "zones_skipped": skipped,
        "method": "schedule_max_per_zone",
    }

    if not setpoints:
        result.update({
            "mean_c": None,
            "min_c": None,
            "max_c": None,
            "spread_warning": None,
            "skip_reason": (
                "no thermostat in the model"
                if zones_with_thermostat == 0
                else "no zone has a readable heating setpoint schedule"
            ),
        })
        return result

    values = [v for _, v in setpoints]
    spread = max(values) - min(values)
    result.update({
        "mean_c": sum(values) / len(values),
        "min_c": min(values),
        "max_c": max(values),
        "skip_reason": None,
        "spread_warning": (
            f"Heating setpoints span {spread:.1f} K across {len(values)} zones "
            f"({min(values):.1f}-{max(values):.1f} C); their mean describes no single space."
            if spread > WIDE_SPREAD_K
            else None
        ),
    })
    return result
