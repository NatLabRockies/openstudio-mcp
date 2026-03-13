# Example 1: Custom Measure — Reduce Lighting Power

Write a custom measure to reduce lighting, apply it, and compare before/after energy use.

## Scenario

An energy modeler wants to evaluate the impact of reducing lighting power density to 8 W/m2 across all spaces. Instead of manually editing each LightsDefinition, they ask the AI to write a custom measure, test it, and run a before/after simulation comparison.

## Prompt

> Load the HVAC model. Run a baseline simulation and extract the EUI. Then write a Ruby measure that sets all LightsDefinition objects to 8 W/m2, test it, apply it, re-simulate, and compare the results.

## Tool Call Sequence

### Baseline Simulation

```
1. load_osm_model(osm_path="/runs/examples/baseline-hvac/baseline_model.osm")
2. save_osm_model(save_path="/runs/baseline.osm")
3. run_simulation(osm_path="/runs/baseline.osm")
4. get_run_status(run_id=<id>)           # poll until "success"
5. extract_summary_metrics(run_id=<id>)  # note baseline EUI
```

### Write and Apply Measure

```
6. load_osm_model(osm_path="/runs/examples/baseline-hvac/baseline_model.osm")
7. create_measure(
     name="set_lights_8w",
     description="Set all lights to 8 W/m2",
     language="Ruby",
     run_body="    model.getLightsDefinitions.each do |ld|\n      ld.setWattsperSpaceFloorArea(8.0)\n    end\n    runner.registerFinalCondition('Set all lights to 8 W/m2')")
8. test_measure(measure_dir="/runs/custom_measures/set_lights_8w")
9. apply_measure(measure_dir="/runs/custom_measures/set_lights_8w")
```

### Retrofit Simulation

```
10. save_osm_model(save_path="/runs/retrofit_lights.osm")
11. run_simulation(osm_path="/runs/retrofit_lights.osm")
12. get_run_status(run_id=<id>)
13. extract_summary_metrics(run_id=<id>)  # compare to baseline EUI
```

### Compare

The AI compares baseline vs retrofit:
- **EUI** (kBtu/ft2/yr) — total energy use intensity change
- **Interior Lighting** end use — direct savings from the measure
- **Cooling** end use — reduced internal gains lower cooling load

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `create_measure` | Write custom Ruby measure with user-provided code |
| `test_measure` | Validate measure compiles and runs on example model |
| `apply_measure` | Apply measure to the loaded model |
| `run_simulation` | Run EnergyPlus (called twice: baseline + retrofit) |
| `extract_summary_metrics` | Extract EUI for comparison |

## Common Lighting Power Densities

| Space Type | ASHRAE 90.1-2019 (W/m2) |
|-----------|------------------------|
| Office (open) | 6.9 |
| Office (enclosed) | 8.6 |
| Lobby | 8.6 |
| Corridor | 5.4 |
| Retail | 11.8 |

## Integration Test

See `tests/llm/test_04_workflows.py::test_workflow[measure_set_lights_full_chain]`
