## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "My simulation failed" | get_run_status, get_run_logs | run_id |
| "EUI looks way too high" | extract_summary_metrics, list_model_objects | run_id |
| "Too many unmet hours" | extract_summary_metrics, extract_component_sizing | run_id |
| "Why did EnergyPlus crash? Check the EnergyPlus error log" | get_run_logs | run_id, stream=energyplus |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "Run the simulation" | get_run_logs, extract_simulation_errors | run_simulation, save_osm_model |
| "Check the model before simulating" | get_run_logs | validate_model, run_qaqc_checks, inspect_osm_summary, get_model_summary |
| "Create a new building" | get_run_logs, extract_simulation_errors | create_new_building, create_bar_building, create_baseline_osm |
