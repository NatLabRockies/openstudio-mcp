# Example 13: Comprehensive Energy Report (`/energy-report`)

Extract all result categories from a completed simulation into a structured report.

## Scenario

After a simulation completes, an engineer wants a full breakdown — not just EUI, but envelope performance, HVAC sizing, zone-level loads, and component sizing. The `/energy-report` skill extracts all 6 result categories and presents them together.

## Prompt

> /energy-report

## Tool Call Sequence

```
1. extract_summary_metrics(run_id=...)       # EUI, total energy, unmet hours
2. extract_end_use_breakdown(run_id=...)     # by fuel type + end use
3. extract_envelope_summary(run_id=...)      # U-values, SHGC, areas
4. extract_hvac_sizing(run_id=...)           # zone/system design capacities
5. extract_zone_summary(run_id=...)          # per-zone heating/cooling loads
6. extract_component_sizing(run_id=...)      # autosized equipment values
7. Presents structured report with all sections
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `extract_summary_metrics` | Overall EUI and energy totals |
| `extract_end_use_breakdown` | Heating, cooling, lighting, etc. by fuel |
| `extract_envelope_summary` | Wall/roof/window thermal properties |
| `extract_hvac_sizing` | Design load capacities |
| `extract_zone_summary` | Per-zone load breakdown |
| `extract_component_sizing` | Autosized equipment parameters |

## Notes

- Requires a completed simulation (run with `status == "success"`)
- Runs in a forked context to avoid context bloat from large result tables
- All 6 extractors are called sequentially — each reads from the same `run_id`

## Integration Test

See `tests/test_skill_energy_report.py::test_skill_energy_report_workflow`
