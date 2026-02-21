"""Schedules operations — schedule rulesets and details.

Extraction patterns adapted from openstudio-toolkit osm_objects/schedules.py
— using direct openstudio bindings.
"""

from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model
from mcp_server.osm_helpers import fetch_object, list_all_as_dicts, optional_name


def _extract_schedule_ruleset(model, schedule) -> dict[str, Any]:
    """Extract schedule ruleset attributes to dict."""
    # Get schedule type limits
    schedule_type_limits = optional_name(schedule.scheduleTypeLimits())

    # Get default day schedule
    default_day_schedule = schedule.defaultDaySchedule().nameString()

    # Get summer and winter design day schedules
    summer_design_day = schedule.summerDesignDaySchedule().nameString()
    winter_design_day = schedule.winterDesignDaySchedule().nameString()

    # Count schedule rules
    num_rules = len(schedule.scheduleRules())

    return {
        "handle": str(schedule.handle()),
        "name": schedule.nameString(),
        "schedule_type_limits": schedule_type_limits,
        "default_day_schedule": default_day_schedule,
        "summer_design_day_schedule": summer_design_day,
        "winter_design_day_schedule": winter_design_day,
        "num_rules": num_rules,
    }


def list_schedule_rulesets() -> dict[str, Any]:
    """List all schedule rulesets in the model."""
    try:
        model = get_model()
        schedules = list_all_as_dicts(model, "getScheduleRulesets", _extract_schedule_ruleset)
        return {
            "ok": True,
            "count": len(schedules),
            "schedule_rulesets": schedules,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list schedule rulesets: {e}"}


def get_schedule_details(schedule_name: str) -> dict[str, Any]:
    """Get detailed information about a specific schedule ruleset."""
    try:
        model = get_model()
        schedule = fetch_object(model, "ScheduleRuleset", name=schedule_name)

        if schedule is None:
            return {"ok": False, "error": f"Schedule ruleset '{schedule_name}' not found"}

        # Get basic info
        result = _extract_schedule_ruleset(model, schedule)

        # Add detailed rule information
        rules = []
        for rule in schedule.scheduleRules():
            rule_info = {
                "name": rule.nameString() if hasattr(rule, "nameString") else "Unnamed Rule",
                "day_schedule": rule.daySchedule().nameString(),
                "apply_sunday": rule.applySunday(),
                "apply_monday": rule.applyMonday(),
                "apply_tuesday": rule.applyTuesday(),
                "apply_wednesday": rule.applyWednesday(),
                "apply_thursday": rule.applyThursday(),
                "apply_friday": rule.applyFriday(),
                "apply_saturday": rule.applySaturday(),
            }

            # Add date range if specified
            if rule.startDate().is_initialized():
                start_date = rule.startDate().get()
                rule_info["start_date"] = f"{start_date.monthOfYear().value()}/{start_date.dayOfMonth()}"

            if rule.endDate().is_initialized():
                end_date = rule.endDate().get()
                rule_info["end_date"] = f"{end_date.monthOfYear().value()}/{end_date.dayOfMonth()}"

            rules.append(rule_info)

        result["rules"] = rules

        return {
            "ok": True,
            "schedule": result,
        }
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to get schedule details: {e}"}


def create_schedule_ruleset(name: str, schedule_type: str = "Fractional", default_value: float = 1.0) -> dict[str, Any]:
    """Create a new schedule ruleset with a constant default day schedule.

    Args:
        name: Name for the new schedule
        schedule_type: Type of schedule - "Fractional", "Temperature", "OnOff" (default: "Fractional")
        default_value: Constant value for all hours (default: 1.0)

    Returns:
        dict with ok=True and schedule details, or ok=False and error message
    """
    try:
        model = get_model()

        # Create schedule ruleset
        schedule = openstudio.model.ScheduleRuleset(model)
        schedule.setName(name)

        # Set schedule type limits based on schedule_type
        if schedule_type == "Fractional":
            # Fractional (0-1)
            type_limits = openstudio.model.ScheduleTypeLimits(model)
            type_limits.setName(f"{name} Type Limits")
            type_limits.setLowerLimitValue(0.0)
            type_limits.setUpperLimitValue(1.0)
            type_limits.setNumericType("Continuous")
            schedule.setScheduleTypeLimits(type_limits)
        elif schedule_type == "Temperature":
            # Temperature (no limits)
            type_limits = openstudio.model.ScheduleTypeLimits(model)
            type_limits.setName(f"{name} Type Limits")
            type_limits.setNumericType("Continuous")
            type_limits.setUnitType("Temperature")
            schedule.setScheduleTypeLimits(type_limits)
        elif schedule_type == "OnOff":
            # On/Off (0 or 1)
            type_limits = openstudio.model.ScheduleTypeLimits(model)
            type_limits.setName(f"{name} Type Limits")
            type_limits.setLowerLimitValue(0.0)
            type_limits.setUpperLimitValue(1.0)
            type_limits.setNumericType("Discrete")
            schedule.setScheduleTypeLimits(type_limits)

        # Set default day schedule to constant value
        default_day = schedule.defaultDaySchedule()
        default_day.setName(f"{name} Default")
        default_day.addValue(openstudio.Time(0, 24, 0, 0), default_value)

        # Set design day schedules to same value
        summer_design = schedule.summerDesignDaySchedule()
        summer_design.setName(f"{name} Summer Design Day")
        summer_design.addValue(openstudio.Time(0, 24, 0, 0), default_value)

        winter_design = schedule.winterDesignDaySchedule()
        winter_design.setName(f"{name} Winter Design Day")
        winter_design.addValue(openstudio.Time(0, 24, 0, 0), default_value)

        # Extract and return
        result = _extract_schedule_ruleset(model, schedule)
        return {"ok": True, "schedule": result}

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to create schedule ruleset: {e}"}
