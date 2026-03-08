## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Check the model for issues" | run_qaqc_checks, inspect_osm_summary | — |
| "Validate before simulation" | run_qaqc_checks | — |
| "QA/QC the model" | run_qaqc_checks | template |
| "Is my model ready to simulate?" | inspect_osm_summary, run_qaqc_checks | — |

## Should NOT trigger
| Query | Why |
|---|---|
| "Run the simulation" | Simulation — use simulate skill |
| "What's wrong with my results?" | Post-sim — use troubleshoot skill |
| "List the spaces" | Query — use list_spaces |
