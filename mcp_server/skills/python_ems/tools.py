"""MCP tool definitions for Python EMS (EnergyPlus Python Plugins)."""
from __future__ import annotations

from typing import Any

from mcp_server.skills.python_ems.actuators import list_ems_actuators_op
from mcp_server.skills.python_ems.manage import (
    edit_python_plugin_op,
    get_python_plugin_op,
)
from mcp_server.skills.python_ems.operations import create_python_plugin_op
from mcp_server.skills.python_ems.packages import install_plugin_packages_op


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
        node_name: str | None = None,
        air_loop_name: str | None = None,
        oat_low: float | None = None,
        oat_high: float | None = None,
        setpoint_at_oat_low: float | None = None,
        setpoint_at_oat_high: float | None = None,
        class_name: str | None = None,
        code: str | None = None,
        global_variables: list[str] | str | None = None,
        trend_timesteps: int | None = None,
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
        - "node_setpoint_reset": linear outdoor-air reset of a node temperature setpoint
          (overrides setpoint managers). Uses node_name OR air_loop_name (its supply
          outlet node), plus oat_low/oat_high/setpoint_at_oat_low/setpoint_at_oat_high.
        - "custom": full plugin source via code + class_name (+ optional global_variables,
          output_variable_name). Class must inherit EnergyPlusPlugin and override an on_*
          callback; source is syntax- and contract-checked. Use list_ems_actuators first
          to find valid actuator triples.

        Outputs are read after run_simulation with
        query_timeseries(variable_name="PythonPlugin:OutputVariable", key_value=<output name>).
        Save the model (save_osm_model) before running. Third-party imports need
        install_plugin_packages first.

        Args:
            name: Plugin instance name (also the script module name)
            template: zone_metric_aggregate | schedule_override | node_setpoint_reset | custom
            variable_name: [zone_metric_aggregate] per-zone variable to aggregate
            zone_names: [zone_metric_aggregate] zones to include (default: all zones)
            aggregation: [zone_metric_aggregate] volume_weighted_average/average/sum/min/max
            output_variable_name: reported output variable name (default derived from name)
            units: units label for the reported output (default "C")
            schedule_name: [schedule_override] schedule to actuate (Constant/Ruleset/Year/Compact)
            rules: [schedule_override] list of {days, start_hour, end_hour, value}
            default_value: [schedule_override] value when no rule matches
            node_name: [node_setpoint_reset] node whose Temperature Setpoint is actuated
            air_loop_name: [node_setpoint_reset] alternative — use this loop's supply outlet node
            oat_low: [node_setpoint_reset] OAT (C) at/below which setpoint_at_oat_low applies
            oat_high: [node_setpoint_reset] OAT (C) at/above which setpoint_at_oat_high applies
            setpoint_at_oat_low: [node_setpoint_reset] setpoint (C) at low OAT
            setpoint_at_oat_high: [node_setpoint_reset] setpoint (C) at high OAT
            class_name: [custom] plugin class name in the code
            code: [custom] full plugin script source
            global_variables: [custom] PythonPlugin:Variables globals the code uses
            trend_timesteps: log the first global as a PythonPlugin:TrendVariable (N timesteps)
            run_during_warmup: also run callbacks during warmup days (default False)
        """
        return create_python_plugin_op(
            name=name, template=template, variable_name=variable_name,
            zone_names=zone_names, aggregation=aggregation,
            output_variable_name=output_variable_name, units=units,
            schedule_name=schedule_name, rules=rules, default_value=default_value,
            node_name=node_name, air_loop_name=air_loop_name,
            oat_low=oat_low, oat_high=oat_high,
            setpoint_at_oat_low=setpoint_at_oat_low,
            setpoint_at_oat_high=setpoint_at_oat_high,
            class_name=class_name, code=code, global_variables=global_variables,
            trend_timesteps=trend_timesteps, run_during_warmup=run_during_warmup,
        )

    @mcp.tool(tags={"hvac", "simulation"}, name="get_python_plugin")
    def get_python_plugin_tool(name: str | None = None):
        """List the model's Python EMS plugins (no args) or inspect one by name,
        including its script source, declared globals, reported output variables,
        trend variables, and package search paths.

        Args:
            name: Plugin instance name (omit to list all)
        """
        return get_python_plugin_op(name=name)

    @mcp.tool(tags={"hvac", "simulation"}, name="edit_python_plugin")
    def edit_python_plugin_tool(name: str, code: str):
        """Replace an existing Python EMS plugin's script source. The new source is
        validated first (syntax, EnergyPlusPlugin contract, class name unchanged);
        a rejected edit leaves the script untouched.

        Args:
            name: Plugin instance name (see get_python_plugin)
            code: Full replacement plugin script source
        """
        return edit_python_plugin_op(name=name, code=code)

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

    @mcp.tool(tags={"simulation"}, name="install_plugin_packages")
    def install_plugin_packages_tool(packages: list[str] | str):
        """Install Python packages (e.g. numpy) for use inside EnergyPlus Python plugins.
        Wheels-only pip install into your private package dir; plugins import them at
        simulation time via PythonPlugin:SearchPaths. Quota-capped. Specs may be
        'name' or 'name==version' only — no URLs, paths, or flags.

        Args:
            packages: package specs, e.g. ["numpy"] or ["numpy==2.1.0", "pandas"]
        """
        return install_plugin_packages_op(packages=packages)
