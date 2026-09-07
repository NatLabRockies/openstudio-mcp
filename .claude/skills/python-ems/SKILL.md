---
name: python-ems
description: Add custom EMS control or reporting logic (EnergyPlus Python Plugins) — setpoint resets, schedule overrides, supervisory control, custom metrics. Use when no packaged HVAC/schedule tool covers the control logic the user wants.
---

# Python EMS (EnergyPlus Python Plugins)

Custom control/reporting logic that runs inside EnergyPlus each timestep.
A plugin is a Python class attached to the model; it reads sensors
(output variables), sets actuators (schedule values, setpoints, flows), and
publishes custom output variables you can query like any other result.

**Always prefer the named templates** in `create_python_plugin` — they generate
correct, validated plugin code. Write `template="custom"` code only when no
template fits.

## Workflow

1. Model loaded (any create/load tool). The model must have a file path — save first if needed.
2. Discover what you can control:
   ```
   list_ems_actuators(component_type="Schedule")
   ```
   Returns (component_type, control_type, actuator_key) triples from a hidden
   sizing-only run (a few seconds). Names come back UPPERCASE — matching inside
   plugins is case-insensitive. Requires design days in the model.
3. Create the plugin from a template:
   ```
   create_python_plugin(name="Night Setback", template="schedule_override",
                        schedule_name="Htg Setpoint Sched", default_value=15.6,
                        rules=[{"days": "weekdays", "start_hour": 5, "end_hour": 19, "value": 21.0}])
   ```
4. `save_osm_model()` — the script lives in the model's companion `files/` dir and travels with it.
5. `run_simulation(...)`, then verify the plugin loaded: `extract_simulation_errors(run_id=<run_id>)`
   should show no severe messages; the .err file logs `PythonPlugin: Class X imported`.
6. Read the plugin's outputs:
   ```
   query_timeseries(run_id=<run_id>, variable_name="PythonPlugin:OutputVariable",
                    key_value="Night Setback Applied Value")
   ```

## Worked examples

**Average building temperature (custom metric, no actuation):**
```
create_python_plugin(name="Avg Building Temp", template="zone_metric_aggregate",
                     variable_name="Zone Mean Air Temperature",
                     aggregation="volume_weighted_average",
                     output_variable_name="Averaged Building Temperature", units="C")
```
Defaults to all zones; pass zone_names to restrict.

**Schedule/setpoint override by time-of-day rules:**
```
create_python_plugin(name="Night Setback", template="schedule_override",
                     schedule_name="Htg Setpoint Sched", default_value=15.6,
                     rules=[{"days": "weekdays", "start_hour": 5, "end_hour": 19, "value": 21.0},
                            {"days": "saturday", "start_hour": 6, "end_hour": 12, "value": 18.0}])
```
First matching rule wins, else default_value. Works on ScheduleConstant,
ScheduleRuleset (actuated as Schedule:Year), and ScheduleCompact schedules.

**Outdoor-air setpoint reset (overrides setpoint managers):**
```
create_python_plugin(name="SAT Reset", template="node_setpoint_reset",
                     air_loop_name="Packaged Rooftop Air Conditioner",
                     oat_low=-20, oat_high=10,
                     setpoint_at_oat_low=15.0, setpoint_at_oat_high=12.8)
```
Pass node_name directly, or air_loop_name to use its supply outlet node.

**Custom plugin (escape hatch):** provide full source. Contract:
```python
from pyenergyplus.plugin import EnergyPlusPlugin

class MyControl(EnergyPlusPlugin):
    def on_begin_timestep_before_predictor(self, state) -> int:
        if not self.api.exchange.api_data_fully_ready(state):
            return 0
        # get_*_handle returns -1 when not found — check it, issue_severe, return 1
        # return 0 = success; nonzero aborts the simulation
        return 0
```
Pass `code=...`, `class_name="MyControl"`, and `global_variables=[...]` for any
globals used via `get_global_handle`/`set_global_value`. Use `list_ems_actuators`
first for valid actuator triples.

## Rules of the plugin runtime

- Look up handles lazily, only after `self.api.exchange.api_data_fully_ready(state)` is True; cache them.
- Handle lookups return -1 (never raise). On -1: `self.api.runtime.issue_severe(state, msg); return 1`.
- Callback return 0 = success; nonzero is FATAL to the whole simulation.
- Globals must be declared (create_python_plugin does this) before `get_global_handle` finds them.
- A sensed variable needs an `Output:Variable` request to have a handle — the templates add it.
- `self.api.exchange.hour(state)` is 0-23; `self.api.exchange.day_of_week(state)` is 1=Sunday..7=Saturday.
- Plugins run inside EnergyPlus (embedded Python 3.12, stdlib by default).
  For third-party packages (numpy etc.): `install_plugin_packages(["numpy"])`
  first — wheels-only, quota-capped, wired in automatically. `pkg==version`
  pins allowed; URLs/paths are not.
- To revise a plugin: `edit_python_plugin(name=..., code=...)` (validated; the class
  name must stay unchanged). `delete_object` on the instance removes it.
- `trend_timesteps=N` on create logs the plugin global as a
  PythonPlugin:TrendVariable for `get_trend_average/min/max` history access.

## Common actuator triples

| Component type | Control type | Key |
|---|---|---|
| Schedule:Constant / Schedule:Year / Schedule:Compact | Schedule Value | schedule name |
| System Node Setpoint | Temperature Setpoint | node name |
| Zone Temperature Control | Heating (or Cooling) Setpoint | zone name |
| Weather Data | Outdoor Dry Bulb | Environment |

Confirm with `list_ems_actuators` — availability is model-dependent.
