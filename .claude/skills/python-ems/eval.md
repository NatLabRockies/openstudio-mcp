## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Add a Python EMS plugin that reports the volume-weighted average zone temperature" | create_python_plugin | name present, template=zone_metric_aggregate |
| "Create a Python EMS night-setback controller for the heating setpoint schedule" | create_python_plugin | name present, template=schedule_override, schedule_name present |
| "Add an outdoor-air reset Python plugin for the supply-air temperature" | create_python_plugin | name present, template=node_setpoint_reset |
| "Replace the source code of the existing llm-test-sched-override Python plugin" | edit_python_plugin | name=llm-test-sched-override, code present |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "List the Python EMS plugins already in this model" | create_python_plugin, edit_python_plugin | get_python_plugin |
| "Show me the source code for the llm-test-sched-override Python plugin" | create_python_plugin, edit_python_plugin | get_python_plugin |
| "Run the loaded model with EnergyPlus" | create_python_plugin, edit_python_plugin | run_simulation, save_osm_model |
