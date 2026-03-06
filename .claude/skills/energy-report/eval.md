## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Give me a full energy report" | extract_summary_metrics, extract_end_use_breakdown, extract_envelope_summary, extract_hvac_sizing, extract_zone_summary | run_id |
| "Detailed analysis of results" | extract_* tools | run_id |
| "What are the full simulation results?" | extract_* tools | run_id |

## Should NOT trigger
| Query | Why |
|---|---|
| "What's the EUI?" | Single metric — use extract_summary_metrics directly |
| "Run the simulation" | Simulation — use simulate skill |
| "Show me monthly electricity" | Timeseries — use query_timeseries |
