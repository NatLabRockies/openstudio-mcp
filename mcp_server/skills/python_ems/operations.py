"""Python EMS operations — create and inspect EnergyPlus Python Plugin objects.

A plugin's script lives in the model's companion files/ dir: ExternalFile copies
it there (we point the model's workflow at the OSM's dir first), save_osm_model
carries the dir on save-as, and run_simulation stages it next to the seed so
workflow-time forward translation resolves the bare file name. The script then
executes inside EnergyPlus under the simulation sandbox.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import openstudio

from mcp_server import model_manager
from mcp_server.config import is_path_allowed, user_pkgs_root
from mcp_server.osm_helpers import parse_str_list
from mcp_server.skills.python_ems import templates

_MAX_SOURCE_CHARS = 24_000


class _EmsError(Exception):
    """Internal: converted to {"ok": False, "error": ...} at the op boundary."""


def _files_context() -> tuple[Any, Path, Path]:
    """Resolve (model, osm_dir, files_dir) for the loaded model.

    Points the model's workflow at the OSM's own dir so ExternalFile copies
    land in <osm_dir>/files/ (ExternalFile copies into <oswDir>/files).
    """
    model = model_manager.get_model_if_loaded()
    if model is None:
        raise _EmsError("No model loaded. Call load_osm_model first.")
    osm_path = model_manager.get_model_path()
    if osm_path is None:
        raise _EmsError("Loaded model has no file path. Call save_osm_model first.")
    osm_dir = osm_path.resolve().parent
    files_dir = osm_dir / "files"
    if not is_path_allowed(files_dir, write=True):
        raise _EmsError(
            f"Model directory is not writable for this session: {osm_dir}. "
            "save_osm_model into your own run area first, then retry.")
    model.workflowJSON().setOswDir(openstudio.path(str(osm_dir)))
    return model, osm_dir, files_dir


def _schedule_component_type(model, schedule_name: str) -> str:
    """Map an OpenStudio schedule to its EnergyPlus actuator component type."""
    if model.getScheduleConstantByName(schedule_name).is_initialized():
        return "Schedule:Constant"
    if model.getScheduleRulesetByName(schedule_name).is_initialized():
        return "Schedule:Year"
    if model.getScheduleYearByName(schedule_name).is_initialized():
        return "Schedule:Year"
    if model.getScheduleCompactByName(schedule_name).is_initialized():
        return "Schedule:Compact"
    raise _EmsError(
        f"Schedule '{schedule_name}' not found as a ScheduleConstant/Ruleset/"
        "Year/Compact. Use get_schedule_details or list_model_objects to find one.")


def _ensure_output_variable(model, variable_name: str, key_value: str,
                            frequency: str) -> bool:
    """Add an Output:Variable request unless the same (name, key) already exists."""
    for existing in model.getOutputVariables():
        if (existing.variableName() == variable_name
                and existing.keyValue() == key_value):
            return False
    output_variable = openstudio.model.OutputVariable(variable_name, model)
    output_variable.setKeyValue(key_value)
    output_variable.setReportingFrequency(frequency)
    return True


def _ensure_plugin_global(model, global_name: str) -> bool:
    """Declare a PythonPlugin:Variables global unless already declared."""
    for existing in model.getPythonPluginVariables():
        if existing.nameString() == global_name:
            return False
    variable = openstudio.model.PythonPluginVariable(model)
    variable.setName(global_name)
    return True


def _plugin_global_by_name(model, global_name: str):
    for variable in model.getPythonPluginVariables():
        if variable.nameString() == global_name:
            return variable
    raise _EmsError(f"Plugin global '{global_name}' not found in model.")


def ensure_pkgs_search_path(model) -> bool:
    """Add the caller's python_packages dir to PythonPlugin:SearchPaths.

    No-op unless the dir exists and is non-empty (install_plugin_packages
    creates it). Forward translation merges these entries with the
    auto-generated ExternalFile search path into the one unique-object.
    """
    pkgs_dir = user_pkgs_root()
    if not pkgs_dir.is_dir() or not any(pkgs_dir.iterdir()):
        return False
    search_paths = model.getPythonPluginSearchPaths()
    existing = {openstudio.toString(p) for p in search_paths.searchPaths()}
    if str(pkgs_dir) in existing:
        return False
    search_paths.addSearchPath(str(pkgs_dir))
    return True


def create_python_plugin_op(
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
) -> dict[str, Any]:
    """Scaffold a plugin script from a template and wire all model objects."""
    try:
        model, _osm_dir, files_dir = _files_context()

        if template not in templates.TEMPLATES:
            raise _EmsError(f"Unknown template '{template}'. Available: {templates.TEMPLATES}")
        name = (name or "").strip()
        if not name:
            raise _EmsError("name is required")
        module = templates.safe_module_name(name)

        for instance in model.getPythonPluginInstances():
            if instance.nameString().lower() == name.lower():
                raise _EmsError(
                    f"Python plugin '{instance.nameString()}' already exists. "
                    "delete_object it first, or pick another name.")

        sensor_requests: list[tuple[str, str]] = []
        output_specs: list[dict[str, str]] = []

        if template == "zone_metric_aggregate":
            zones = parse_str_list(zone_names) or []
            for zone in zones:
                if not model.getThermalZoneByName(zone).is_initialized():
                    raise _EmsError(f"Thermal zone '{zone}' not found. See list_thermal_zones.")
            out_name = output_variable_name or f"{name} Value"
            global_name = templates.global_name_for(out_name)
            plugin_class = "ZoneMetricAggregate"
            source = templates.build_zone_metric_source(
                plugin_class, variable_name, zones, aggregation, global_name)
            # The plugin needs the variable tracked to get handles, and the test
            # of record needs per-zone series — one Output:Variable serves both.
            sensor_requests = [(variable_name, "*")]
            globals_needed = [global_name]
            output_specs = [{"name": out_name, "global": global_name, "units": units or ""}]

        elif template == "schedule_override":
            if not schedule_name:
                raise _EmsError("schedule_name is required for the schedule_override template")
            if default_value is None:
                raise _EmsError("default_value is required for the schedule_override template")
            component_type = _schedule_component_type(model, schedule_name)
            try:
                normalized_rules = templates.normalize_rules(rules)
            except ValueError as e:
                raise _EmsError(str(e)) from e
            out_name = output_variable_name or f"{name} Applied Value"
            global_name = templates.global_name_for(out_name)
            plugin_class = "ScheduleOverride"
            source = templates.build_schedule_override_source(
                plugin_class, schedule_name, component_type,
                normalized_rules, float(default_value), global_name)
            sensor_requests = [("Schedule Value", schedule_name)]
            globals_needed = [global_name]
            output_specs = [{"name": out_name, "global": global_name, "units": ""}]

        elif template == "node_setpoint_reset":
            if air_loop_name and not node_name:
                loop = model.getAirLoopHVACByName(air_loop_name)
                if not loop.is_initialized():
                    raise _EmsError(
                        f"Air loop '{air_loop_name}' not found. See list_air_loops.")
                node_name = loop.get().supplyOutletNode().nameString()
            if not node_name:
                raise _EmsError(
                    "node_name (or air_loop_name for its supply outlet node) is "
                    "required for the node_setpoint_reset template")
            if not model.getNodeByName(node_name).is_initialized():
                raise _EmsError(f"Node '{node_name}' not found in model.")
            if None in (oat_low, oat_high, setpoint_at_oat_low, setpoint_at_oat_high):
                raise _EmsError(
                    "oat_low, oat_high, setpoint_at_oat_low, and "
                    "setpoint_at_oat_high are required for node_setpoint_reset")
            out_name = output_variable_name or f"{name} Setpoint"
            global_name = templates.global_name_for(out_name)
            plugin_class = "NodeSetpointReset"
            try:
                source = templates.build_node_setpoint_reset_source(
                    plugin_class, node_name, float(oat_low), float(oat_high),
                    float(setpoint_at_oat_low), float(setpoint_at_oat_high),
                    global_name)
            except ValueError as e:
                raise _EmsError(str(e)) from e
            sensor_requests = [
                ("Site Outdoor Air Drybulb Temperature", "Environment"),
                ("System Node Setpoint Temperature", node_name),
            ]
            globals_needed = [global_name]
            output_specs = [{"name": out_name, "global": global_name, "units": "C"}]

        else:  # custom
            if not code:
                raise _EmsError("code is required for the custom template")
            if not class_name:
                raise _EmsError("class_name is required for the custom template")
            source = code
            plugin_class = class_name
            globals_needed = parse_str_list(global_variables) or []
            if output_variable_name:
                if not globals_needed:
                    raise _EmsError(
                        "output_variable_name needs a plugin global to report — "
                        "pass global_variables too (the first one is reported).")
                output_specs = [{"name": output_variable_name,
                                 "global": globals_needed[0], "units": units or ""}]

        validation = templates.validate_plugin_source(source, plugin_class)
        if not validation["ok"]:
            return {"ok": False, "error": "Plugin source failed validation",
                    "details": validation["errors"]}

        # Recreate-after-delete: clear a stale ExternalFile/copy for this module,
        # but never one still referenced by another plugin instance.
        script_path = files_dir / f"{module}.py"
        for external_file in model.getExternalFiles():
            if external_file.fileName() != f"{module}.py":
                continue
            for instance in model.getPythonPluginInstances():
                if instance.externalFile().handle() == external_file.handle():
                    raise _EmsError(
                        f"Module '{module}.py' is used by plugin "
                        f"'{instance.nameString()}'. Pick another name.")
            external_file.remove()
        if script_path.exists():
            script_path.unlink()

        staging = Path(tempfile.mkdtemp(prefix="osmcp_ems_"))
        try:
            staged_script = staging / f"{module}.py"
            staged_script.write_text(source, encoding="utf-8")
            external_opt = openstudio.model.ExternalFile.getExternalFile(
                model, str(staged_script))
            if not external_opt.is_initialized():
                raise _EmsError("ExternalFile creation failed for the plugin script.")
            external_file = external_opt.get()
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if not script_path.exists():
            external_file.remove()
            raise _EmsError(f"Plugin script was not copied to {script_path}.")

        try:
            # Constructor re-validates that the class exists in the file.
            instance = openstudio.model.PythonPluginInstance(external_file, plugin_class)
        except Exception as e:
            external_file.remove()
            raise _EmsError(f"PythonPlugin:Instance rejected the script: {e}") from e
        instance.setName(name)
        instance.setRunDuringWarmupDays(bool(run_during_warmup))

        objects_created = [f"PythonPlugin:Instance '{name}' ({module}.py::{plugin_class})"]
        for global_name in globals_needed:
            if _ensure_plugin_global(model, global_name):
                objects_created.append(f"PythonPlugin:Variables global '{global_name}'")
        for spec in output_specs:
            plugin_variable = _plugin_global_by_name(model, spec["global"])
            plugin_output = openstudio.model.PythonPluginOutputVariable(plugin_variable)
            plugin_output.setName(spec["name"])
            plugin_output.setTypeofDatainVariable("Averaged")
            plugin_output.setUpdateFrequency("ZoneTimestep")
            if spec["units"]:
                plugin_output.setUnits(spec["units"])
            objects_created.append(f"PythonPlugin:OutputVariable '{spec['name']}'")
            if _ensure_output_variable(model, "PythonPlugin:OutputVariable",
                                       spec["name"], "Timestep"):
                objects_created.append(
                    f"Output:Variable (PythonPlugin:OutputVariable, key '{spec['name']}')")
        for sensor_name, sensor_key in sensor_requests:
            if _ensure_output_variable(model, sensor_name, sensor_key, "Timestep"):
                objects_created.append(
                    f"Output:Variable ({sensor_name}, key '{sensor_key}')")

        if trend_timesteps is not None:
            if int(trend_timesteps) < 1:
                raise _EmsError("trend_timesteps must be >= 1")
            if not globals_needed:
                raise _EmsError(
                    "trend_timesteps needs a plugin global to log — pass "
                    "global_variables for the custom template.")
            trend_global = globals_needed[0]
            trend = openstudio.model.PythonPluginTrendVariable(
                _plugin_global_by_name(model, trend_global))
            trend.setName(f"{trend_global} Trend")
            trend.setNumberofTimestepstobeLogged(int(trend_timesteps))
            objects_created.append(
                f"PythonPlugin:TrendVariable '{trend_global} Trend' "
                f"({int(trend_timesteps)} timesteps)")

        search_path_added = ensure_pkgs_search_path(model)

        return {
            "ok": True,
            "plugin_instance": name,
            "template": template,
            "module_name": module,
            "class_name": plugin_class,
            "script_path": str(script_path),
            "callbacks": validation["callbacks"],
            "global_variables": globals_needed,
            "output_variables": [{"name": s["name"], "units": s["units"]} for s in output_specs],
            "packages_search_path_added": search_path_added,
            "objects_created": objects_created,
            "message": (
                "Plugin attached. Run a simulation, then read its outputs with "
                'query_timeseries(variable_name="PythonPlugin:OutputVariable", '
                'key_value="<output variable name>"). Remember to save_osm_model '
                "before run_simulation."),
        }
    except _EmsError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"create_python_plugin failed: {e}"}


# get_python_plugin_op / edit_python_plugin_op live in manage.py (same skill).
