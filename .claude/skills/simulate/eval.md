## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Run a simulation" | save_osm_model, run_simulation, get_run_status | epw_path |
| "Simulate the model" | save_osm_model, run_simulation | — |
| "Run EnergyPlus" | run_simulation | — |

## Should NOT trigger
| Query | Why |
|---|---|
| "Create a new building" | Creation — use new-building skill |
| "Show me the results" | Results — use energy-report skill |
| "What's the EUI?" | Query — use extract_summary_metrics directly |
