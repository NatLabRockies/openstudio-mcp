## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Run a simulation with the Boston weather file" | save_osm_model, run_simulation, get_run_status | epw_path |
| "Simulate the model" | save_osm_model, run_simulation | — |
| "Run EnergyPlus" | run_simulation | — |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "Create a new building" | run_simulation | create_new_building, create_bar_building, create_baseline_osm |
| "A simulation already completed. Show me the results" | run_simulation | extract_summary_metrics, extract_end_use_breakdown, generate_results_report, list_files |
| "A simulation already completed. What's the EUI?" | run_simulation | extract_summary_metrics, list_files |
