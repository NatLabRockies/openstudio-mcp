# Example 11: Simulation Results Deep Dive

Extract structured results from a completed simulation — energy breakdown,
envelope performance, HVAC sizing, and hourly data — without reading raw HTML.

## Scenario

An engineer ran an annual simulation and wants to analyze results: end-use
energy breakdown, envelope U-values, HVAC sizing adequacy, and January
electricity profile.

## Prompt

> Show me the end-use energy breakdown, envelope summary, HVAC sizing,
> and hourly electricity for January from my last simulation run.

## Tool Call Sequence

```
1. extract_end_use_breakdown(run_id=<id>, units="IP")
2. extract_envelope_summary(run_id=<id>)
3. extract_hvac_sizing(run_id=<id>)
4. extract_zone_summary(run_id=<id>)
5. extract_component_sizing(run_id=<id>, component_type="Coil")
6. query_timeseries(run_id=<id>, variable_name="Electricity:Facility",
     frequency="Daily", start_month=1, end_month=1)
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `extract_end_use_breakdown` | Energy by fuel type (heating, cooling, lighting, etc.) |
| `extract_envelope_summary` | Wall/window U-values and areas |
| `extract_hvac_sizing` | Zone/system autosized capacities |
| `extract_zone_summary` | Per-zone areas and conditions |
| `extract_component_sizing` | Individual equipment autosized values |
| `query_timeseries` | Time-series data with date range filter |

## Tips

- Use `units="SI"` for GJ, `"IP"` (default) for kBtu
- `component_type` filter: "Coil", "Fan", "Pump", "Chiller", "Boiler"
- `query_timeseries` requires output variables added before simulation
- Default 10K point cap; raise via `max_points` for full-year hourly

## Integration Test

See `tests/test_results_extraction.py::TestExampleWorkflow`
