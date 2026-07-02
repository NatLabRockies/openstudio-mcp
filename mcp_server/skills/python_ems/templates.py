"""Pure code generation + validation for EnergyPlus Python Plugin scripts.

No openstudio imports — everything here is unit-testable without the SDK.
Generated scripts follow the pyenergyplus plugin contract: subclass
EnergyPlusPlugin, override on_* callbacks, return 0 on success / nonzero to
abort the simulation, look up handles lazily after api_data_fully_ready.
"""
from __future__ import annotations

import ast
import json
import re
from typing import Any

TEMPLATES = ("zone_metric_aggregate", "schedule_override", "custom")

AGGREGATIONS = ("volume_weighted_average", "average", "sum", "min", "max")

# The 18 EnergyPlusPlugin callback methods (EnergyPlus 25.2 pyenergyplus/plugin.py)
CALLING_POINTS = frozenset({
    "on_begin_new_environment",
    "on_after_new_environment_warmup_is_complete",
    "on_begin_zone_timestep_before_init_heat_balance",
    "on_begin_zone_timestep_after_init_heat_balance",
    "on_begin_timestep_before_predictor",
    "on_begin_zone_timestep_before_set_current_weather",
    "on_after_predictor_before_hvac_managers",
    "on_after_predictor_after_hvac_managers",
    "on_inside_hvac_system_iteration_loop",
    "on_end_of_zone_timestep_before_zone_reporting",
    "on_end_of_zone_timestep_after_zone_reporting",
    "on_end_of_system_timestep_before_hvac_reporting",
    "on_end_of_system_timestep_after_hvac_reporting",
    "on_end_of_zone_sizing",
    "on_end_of_system_sizing",
    "on_end_of_component_input_read_in",
    "on_user_defined_component_model",
    "on_unitary_system_sizing",
})

# EnergyPlus day_of_week: 1 = Sunday ... 7 = Saturday
_DAY_NAMES = {
    "sunday": 1, "monday": 2, "tuesday": 3, "wednesday": 4,
    "thursday": 5, "friday": 6, "saturday": 7,
}
_DAY_SETS = {
    "all": (1, 2, 3, 4, 5, 6, 7),
    "weekdays": (2, 3, 4, 5, 6),
    "weekends": (1, 7),
}


def safe_module_name(name: str) -> str:
    """A valid Python module stem derived from a plugin name."""
    stem = re.sub(r"[^0-9a-zA-Z_]", "_", name or "").strip("_").lower()
    if not stem:
        stem = "plugin"
    if stem[0].isdigit():
        stem = f"plugin_{stem}"
    return stem


def global_name_for(name: str) -> str:
    """A PythonPlugin:Variables global name derived from an output variable name."""
    g = re.sub(r"[^0-9a-zA-Z_]", "_", name or "").strip("_")
    return g or "PluginGlobal"


def normalize_rules(rules: Any) -> list[dict[str, Any]]:
    """Validate/normalize schedule_override rules. Raises ValueError on bad input.

    Each rule: {"days": "all"|"weekdays"|"weekends"|[day names], "start_hour": 0-24,
    "end_hour": 0-24, "value": float}. First matching rule wins; a rule must
    constrain days or hours (an unconditional value belongs in default_value).
    """
    if isinstance(rules, str):
        try:
            rules = json.loads(rules)
        except json.JSONDecodeError as e:
            raise ValueError(f"rules is not valid JSON: {e}") from e
    if not isinstance(rules, list) or not rules:
        raise ValueError("rules must be a non-empty list of rule objects")

    out: list[dict[str, Any]] = []
    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"rules[{i}] must be an object")
        days_in = rule.get("days", "all")
        if isinstance(days_in, str):
            key = days_in.strip().lower()
            if key in _DAY_SETS:
                days = _DAY_SETS[key]
            elif key in _DAY_NAMES:
                days = (_DAY_NAMES[key],)
            else:
                raise ValueError(
                    f"rules[{i}].days: unknown '{days_in}' "
                    f"(use all/weekdays/weekends or day names)")
        else:
            try:
                days = tuple(sorted({_DAY_NAMES[str(d).strip().lower()] for d in days_in}))
            except KeyError as e:
                raise ValueError(f"rules[{i}].days: unknown day name {e}") from e
            if not days:
                raise ValueError(f"rules[{i}].days is empty")
        start = int(rule.get("start_hour", 0))
        end = int(rule.get("end_hour", 24))
        if not (0 <= start < end <= 24):
            raise ValueError(
                f"rules[{i}]: need 0 <= start_hour < end_hour <= 24, got {start}..{end}")
        if "value" not in rule:
            raise ValueError(f"rules[{i}] missing 'value'")
        value = float(rule["value"])
        if days == _DAY_SETS["all"] and start == 0 and end == 24:
            raise ValueError(
                f"rules[{i}] matches always — put that value in default_value instead")
        out.append({"days": days, "start_hour": start, "end_hour": end, "value": value})
    return out


def _rule_condition(rule: dict[str, Any]) -> str:
    parts: list[str] = []
    if rule["days"] != _DAY_SETS["all"]:
        days = rule["days"]
        parts.append(f"day_of_week in {days!r}" if len(days) > 1 else f"day_of_week == {days[0]}")
    if not (rule["start_hour"] == 0 and rule["end_hour"] == 24):
        parts.append(f"{rule['start_hour']} <= hour < {rule['end_hour']}")
    return " and ".join(parts)


def build_zone_metric_source(
    class_name: str,
    variable_name: str,
    zone_names: list[str],
    aggregation: str,
    global_name: str,
) -> str:
    """Generate a plugin that aggregates a per-zone output variable into a global."""
    if aggregation not in AGGREGATIONS:
        raise ValueError(f"aggregation must be one of {AGGREGATIONS}, got '{aggregation}'")

    if zone_names:
        zones_line = f"zone_names = {list(zone_names)!r}"
    else:
        zones_line = 'zone_names = self.api.exchange.get_object_names(state, "Zone")'

    volume_weighted = aggregation == "volume_weighted_average"
    volumes_block = ""
    if volume_weighted:
        volumes_block = """
                vol_handle = self.api.exchange.get_internal_variable_handle(
                    state, "Zone Air Volume", zone_name)
                if vol_handle == -1:
                    self.api.runtime.issue_severe(
                        state, "python_ems: internal variable (Zone Air Volume, "
                        + zone_name + ") not found")
                    return 1
                self.volumes.append(
                    self.api.exchange.get_internal_variable_value(state, vol_handle))"""

    agg_lines = {
        "volume_weighted_average": (
            "result = sum(v * t for v, t in zip(self.volumes, values)) / sum(self.volumes)"
        ),
        "average": "result = sum(values) / len(values)",
        "sum": "result = sum(values)",
        "min": "result = min(values)",
        "max": "result = max(values)",
    }[aggregation]

    return f'''"""Auto-generated by openstudio-mcp create_python_plugin (template: zone_metric_aggregate).

Computes the {aggregation} of "{variable_name}" across zones each zone
timestep and publishes it via the plugin global "{global_name}".
"""
from pyenergyplus.plugin import EnergyPlusPlugin


class {class_name}(EnergyPlusPlugin):

    def __init__(self):
        super().__init__()
        self.handles = None
        self.volumes = []
        self.global_handle = None

    def on_end_of_zone_timestep_before_zone_reporting(self, state) -> int:
        if not self.api.exchange.api_data_fully_ready(state):
            return 0
        if self.handles is None:
            {zones_line}
            self.handles = []
            for zone_name in zone_names:
                handle = self.api.exchange.get_variable_handle(
                    state, {variable_name!r}, zone_name)
                if handle == -1:
                    self.api.runtime.issue_severe(
                        state, "python_ems: variable ({variable_name}, "
                        + zone_name + ") not found")
                    return 1
                self.handles.append(handle){volumes_block}
            self.global_handle = self.api.exchange.get_global_handle(state, {global_name!r})
            if self.global_handle == -1:
                self.api.runtime.issue_severe(
                    state, "python_ems: plugin global {global_name} not declared")
                return 1
        values = [self.api.exchange.get_variable_value(state, h) for h in self.handles]
        {agg_lines}
        self.api.exchange.set_global_value(state, self.global_handle, result)
        return 0
'''


def build_schedule_override_source(
    class_name: str,
    schedule_name: str,
    component_type: str,
    rules: list[dict[str, Any]],
    default_value: float,
    global_name: str,
) -> str:
    """Generate a plugin that actuates a schedule's value from hour/day rules."""
    lines: list[str] = []
    for i, rule in enumerate(rules):
        keyword = "if" if i == 0 else "elif"
        lines.append(f"        {keyword} {_rule_condition(rule)}:")
        lines.append(f"            value = {rule['value']!r}")
    rule_block = "\n".join(lines)

    return f'''"""Auto-generated by openstudio-mcp create_python_plugin (template: schedule_override).

Actuates "{schedule_name}" ({component_type} / Schedule Value) from hour/day
rules each timestep; mirrors the applied value to plugin global "{global_name}".
EnergyPlus day_of_week: 1 = Sunday ... 7 = Saturday.
"""
from pyenergyplus.plugin import EnergyPlusPlugin


class {class_name}(EnergyPlusPlugin):

    def __init__(self):
        super().__init__()
        self.actuator_handle = None
        self.global_handle = None

    def on_begin_timestep_before_predictor(self, state) -> int:
        if not self.api.exchange.api_data_fully_ready(state):
            return 0
        if self.actuator_handle is None:
            self.actuator_handle = self.api.exchange.get_actuator_handle(
                state, {component_type!r}, "Schedule Value", {schedule_name!r})
            if self.actuator_handle == -1:
                self.api.runtime.issue_severe(
                    state, "python_ems: actuator ({component_type}, Schedule Value, "
                           "{schedule_name}) not found")
                return 1
            self.global_handle = self.api.exchange.get_global_handle(state, {global_name!r})
        hour = self.api.exchange.hour(state)
        day_of_week = self.api.exchange.day_of_week(state)
        value = {default_value!r}
{rule_block}
        self.api.exchange.set_actuator_value(state, self.actuator_handle, value)
        if self.global_handle != -1:
            self.api.exchange.set_global_value(state, self.global_handle, value)
        return 0
'''


def validate_plugin_source(source: str, class_name: str) -> dict[str, Any]:
    """Syntax + contract check for a plugin script (used for all templates).

    Returns {"ok": bool, "errors": [..], "callbacks": [..]}. Contract: the
    named class exists, inherits EnergyPlusPlugin, and overrides at least one
    known on_* callback (unknown on_* names are typos — rejected).
    """
    errors: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {
            "ok": False,
            "errors": [f"Python syntax error at line {e.lineno}: {e.msg}"],
            "callbacks": [],
        }

    target: ast.ClassDef | None = None
    class_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            class_names.append(node.name)
            if node.name == class_name:
                target = node

    if target is None:
        return {
            "ok": False,
            "errors": [f"Class '{class_name}' not found (classes defined: {class_names or 'none'})"],
            "callbacks": [],
        }

    bases = [
        b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
        for b in target.bases
    ]
    if "EnergyPlusPlugin" not in bases:
        errors.append(
            f"Class '{class_name}' must inherit EnergyPlusPlugin "
            f"(from pyenergyplus.plugin import EnergyPlusPlugin); bases: {bases}")

    callbacks: list[str] = []
    for item in target.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("on_"):
            if item.name in CALLING_POINTS:
                callbacks.append(item.name)
            else:
                errors.append(
                    f"'{item.name}' is not an EnergyPlusPlugin callback — "
                    f"did you mean one of: {sorted(CALLING_POINTS)}")
    if not callbacks and not errors:
        errors.append(
            f"Class '{class_name}' overrides no plugin callback (on_* method); "
            "it would never run")

    return {"ok": not errors, "errors": errors, "callbacks": callbacks}
