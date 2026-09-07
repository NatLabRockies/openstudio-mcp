## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Give me a full energy report" | extract_summary_metrics, extract_end_use_breakdown, extract_envelope_summary, extract_hvac_sizing, extract_zone_summary | run_id |
| "Detailed analysis of results" | extract_summary_metrics, extract_end_use_breakdown, extract_envelope_summary, extract_hvac_sizing, extract_zone_summary | run_id |
| "What are the full simulation results?" | extract_summary_metrics, extract_end_use_breakdown, extract_envelope_summary, extract_hvac_sizing, extract_zone_summary | run_id |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "What's the EUI?" | extract_end_use_breakdown, extract_envelope_summary, extract_hvac_sizing, extract_zone_summary | extract_summary_metrics |
| "Run the simulation" | generate_results_report | run_simulation, save_osm_model |
| "Show me monthly electricity" | extract_end_use_breakdown, generate_results_report | query_timeseries, list_output_variables |
