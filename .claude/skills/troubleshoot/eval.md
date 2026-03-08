## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "My simulation failed" | get_run_status, get_run_logs | run_id |
| "EUI looks way too high" | extract_summary_metrics, list_infiltration | run_id |
| "Too many unmet hours" | extract_summary_metrics, extract_component_sizing | run_id |
| "Why did EnergyPlus crash?" | get_run_logs | run_id, log_type="stderr" |

## Should NOT trigger
| Query | Why |
|---|---|
| "Run the simulation" | Simulation — use simulate skill |
| "Check the model before simulating" | Pre-sim QA — use qaqc skill |
| "Create a new building" | Creation — use new-building skill |
