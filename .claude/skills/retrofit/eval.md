## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Compare before and after adding insulation" | save_osm_model, run_simulation, extract_summary_metrics (x2) | — |
| "What energy savings from better windows?" | replace_window_constructions, run_simulation | — |
| "Evaluate an ECM" | save baseline, apply measure, run, compare | — |
| "Do a retrofit analysis" | save_osm_model, run_simulation x2, extract_summary_metrics x2 | — |

## Should NOT trigger
| Query | Why |
|---|---|
| "Change wall insulation" | Single modification — use tool-workflows |
| "Run a simulation" | Simulation only — use simulate skill |
| "Create a new building" | Creation — use new-building skill |
