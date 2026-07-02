"""MCP tool definitions for Python EMS (EnergyPlus Python Plugins)."""
from __future__ import annotations

from typing import Any

from mcp_server.skills.python_ems.actuators import list_ems_actuators_op
from mcp_server.skills.python_ems.operations import (
    create_python_plugin_op,
    get_python_plugin_op,
)


def register(mcp):
    @mcp.tool(tags={"hvac", "simulation"}, name="create_python_plugin")
    def create_python_plugin_tool(
        name: str,
        template: str = "zone_metric_aggregate",
        variable_name: str = "Zone Mean Air Temperature",
        zone_names: list[str] | str | None = None,
        aggregation: str = "volume_weighted_average",
        output_variable_name: str | None = None,
        units: str = "C",
        schedule_name: str | None = None,
        rules: list[dict[str, Any]] | str | None = None,
        default_value: float | None = None,
        class_name: str | None = None,
        code: str | None = None,
        global_variables: list[str] | str | None = None,
        run_during_warmup: bool = False,
    ):
        """Add custom EMS control/reporting logic (EnergyPlus Python Plugin) to the model.
        Use for supervisory control, setpoint resets, schedule overrides, or custom metrics
        no packaged HVAC object covers. PREFER the named templates — they generate correct,
        validated plugin code; only use template="custom" when no template fits.

        Templates:
        - "zone_metric_aggregate": aggregate a per-zone variable into one reported value.
          Uses variable_name, zone_names (default: all zones), aggregation
          (volume_weighted_average/average/sum/min/max), output_variable_name, units.
        - "schedule_override": drive a schedule's value by hour/day rules via EMS actuator
          (e.g. setpoint setback). Uses schedule_name, rules, default_value.
          rules example: [{"days": "weekdays", "start_hour": 5, "end_hour": 19, "value": 21.0}]
          (days: all/weekdays/weekends or day names; first matching rule wins,
          otherwise default_value applies).
        - "custom": full plugin source via code + class_name (+ optional global_variables,
          output_variable_name). Class must inherit EnergyPlusPlugin and override an on_*
          callback; source is syntax- and contract-checked. Use list_ems_actuators first
          to find valid actuator triples.

        Outputs are read after run_simulation with
        query_timeseries(variable_name="PythonPlugin:OutputVariable", key_value=<output name>).
        Save the model (save_osm_model) before running.

        Args:
            name: Plugin instance name (also the script module name)
            template: "zone_metric_aggregate", "schedule_override", or "custom"
            variable_name: [zone_metric_aggregate] per-zone variable to aggregate
            zone_names: [zone_metric_aggregate] zones to include (default: all zones)
            aggregation: [zone_metric_aggregate] volume_weighted_average/average/sum/min/max
            output_variable_name: reported output variable name (default derived from name)
            units: units label for the reported output (default "C")
            schedule_name: [schedule_override] schedule to actuate (Constant/Ruleset/Year/Compact)
            rules: [schedule_override] list of {days, start_hour, end_hour, value}
            default_value: [schedule_override] value when no rule matches
            class_name: [custom] plugin class name in the code
            code: [custom] full plugin script source
            global_variables: [custom] PythonPlugin:Variables globals the code uses
            run_during_warmup: also run callbacks during warmup days (default False)
        """
        return create_python_plugin_op(
            name=name, template=template, variable_name=variable_name,
            zone_names=zone_names, aggregation=aggregation,
            output_variable_name=output_variable_name, units=units,
            schedule_name=schedule_name, rules=rules, default_value=default_value,
            class_name=class_name, code=code, global_variables=global_variables,
            run_during_warmup=run_during_warmup,
        )

    @mcp.tool(tags={"hvac", "simulation"}, name="get_python_plugin")
    def get_python_plugin_tool(name: str | None = None):
        """List the model's Python EMS plugins (no args) or inspect one by name,
        including its script source, declared globals, and reported output variables.

        Args:
            name: Plugin instance name (omit to list all)
        """
        return get_python_plugin_op(name=name)

    @mcp.tool(tags={"simulation"}, name="list_ems_actuators")
    def list_ems_actuators_tool(
        component_type: str | None = None,
        control_type: str | None = None,
        key: str | None = None,
        include_internal_variables: bool = False,
        max_results: int = 50,
    ):
        """Discover valid EMS actuators (component type, control type, key) for the loaded
        model — what a Python plugin can control. Runs a hidden sizing-only simulation
        (a few seconds) and parses the EnergyPlus actuator dictionary (.edd).
        Filters are case-insensitive substrings. Requires design days in the model.

        Args:
            component_type: filter, e.g. "Schedule:Constant", "System Node Setpoint"
            control_type: filter, e.g. "Schedule Value", "Temperature Setpoint"
            key: filter on the actuated object name, e.g. a schedule or zone name
            include_internal_variables: also return EMS internal variables (design data)
            max_results: cap returned actuators (default 50, 0 = all)
        """
        return list_ems_actuators_op(
            component_type=component_type, control_type=control_type, key=key,
            include_internal_variables=include_internal_variables,
            max_results=max_results,
        )
