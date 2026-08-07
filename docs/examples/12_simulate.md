# Example 12: One-Command Simulation (`/simulate`)

Run a simulation and extract results in one step using the `/simulate` Claude Code skill.

## Scenario

An engineer has finished building their model and wants to run a simulation without manually orchestrating save, run, poll, and extract steps. The `/simulate` skill handles the entire workflow as a fire-and-forget operation.

## Prompt

> /simulate

## Tool Call Sequence

```
1. save_osm_model(save_path="/runs/model.osm")
2. run_simulation(osm_path="/runs/model.osm", epw_path="/inputs/weather.epw")
3. get_run_status(run_id=...)          # polls until terminal state
4. extract_summary_metrics(run_id=...) # EUI, total energy, unmet hours
5. extract_end_use_breakdown(run_id=...)
6. Presents formatted results summary
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `save_osm_model` | Persist current in-memory model to disk |
| `run_simulation` | Launch EnergyPlus via OpenStudio CLI |
| `get_run_status` | Poll simulation progress until complete |
| `extract_summary_metrics` | EUI, total site/source energy, unmet hours |
| `extract_end_use_breakdown` | Energy by fuel type and end use category |

## Notes

- The skill runs in a forked context (`context: fork`) so it doesn't consume the main conversation window
- Weather file and design days must already be set on the model before invoking
- The skill does NOT auto-save — it saves to a temporary path to avoid overwriting user work

## Integration Test

No dedicated integration test covers the `/simulate` skill workflow as a unit yet — this is a
documentation/test gap. The individual tools it chains are covered elsewhere: `run_simulation` in
`tests/test_hvac_supply_sim.py`, `extract_summary_metrics`/`extract_end_use_breakdown` in
`tests/test_results_extraction.py`.
