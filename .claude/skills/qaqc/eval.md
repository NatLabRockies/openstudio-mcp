## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Check the model for issues" | run_qaqc_checks, inspect_osm_summary, validate_model | — |
| "Validate before simulation" | validate_model OR run_qaqc_checks | — |
| "QA/QC the model against ASHRAE 90.1-2019" | run_qaqc_checks | template=90.1-2019 |
| "Is my model ready to simulate?" | validate_model, inspect_osm_summary, run_qaqc_checks | — |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "Run the simulation" | run_qaqc_checks, validate_osw | run_simulation, save_osm_model |
| "What's wrong with my results?" | inspect_osm_summary | extract_summary_metrics, get_run_logs, extract_simulation_errors |
| "List the spaces" | run_qaqc_checks, inspect_osm_summary | list_spaces |
