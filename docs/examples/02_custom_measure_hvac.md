# Example 2: Custom Measure — Replace Air Terminals with Chilled Beams

Write a complex HVAC measure to replace air terminals, then compare energy performance.

## Scenario

A mechanical engineer is exploring a retrofit from conventional VAV terminals to 4-pipe active chilled beams. The model has existing air loops with standard terminals. They ask the AI to write a custom measure that replaces all terminals with chilled beams, wires the coils to plant loops, and compares the energy impact.

## Prompt

> Load the model. Run a baseline simulation and note the EUI. Then write a Ruby measure that replaces all air terminals with 4-pipe chilled beams. For each air loop, remove existing terminals, create FourPipeBeam terminals with cooling and heating coils, wire them to the chilled water and hot water plant loops, and reconnect. Test it, apply it, re-simulate, and compare.

## Tool Call Sequence

### Baseline

```
1. load_osm_model(osm_path="/runs/examples/baseline-hvac/baseline_model.osm")
2. list_air_loops()                       # understand existing HVAC topology
3. list_plant_loops()                     # identify CHW and HW loops
4. save_osm_model(save_path="/runs/baseline.osm")
5. run_simulation(osm_path="/runs/baseline.osm")
6. get_run_status(run_id=<id>)
7. extract_summary_metrics(run_id=<id>)   # baseline EUI
```

### Write Measure

```
8. load_osm_model(osm_path="/runs/examples/baseline-hvac/baseline_model.osm")
9. create_measure(
     name="replace_terminals_beam",
     description="Replace air terminals with 4-pipe chilled beams",
     language="Ruby",
     run_body=<see below>)
10. test_measure(measure_dir="/runs/custom_measures/replace_terminals_beam")
```

The `run_body` iterates air loops, removes existing terminals, creates `CoilCoolingFourPipeBeam` + `CoilHeatingFourPipeBeam`, wires them to plant loops, constructs `AirTerminalSingleDuctConstantVolumeFourPipeBeam`, and reconnects via `addBranchForZone`.

### Apply and Compare

```
11. apply_measure(measure_dir="/runs/custom_measures/replace_terminals_beam")
12. save_osm_model(save_path="/runs/retrofit_beams.osm")
13. run_simulation(osm_path="/runs/retrofit_beams.osm")
14. get_run_status(run_id=<id>)
15. extract_summary_metrics(run_id=<id>)
16. extract_end_use_breakdown(run_id=<id>)  # detailed fuel/end-use comparison
```

### Compare

The AI compares:
- **EUI** — total energy change
- **Cooling** — chilled beams use radiant + convective cooling (lower fan energy)
- **Heating** — 4-pipe beams provide zone-level heating
- **Fans** — chilled beams reduce air-side flow requirements

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `list_air_loops` | Understand existing HVAC before writing measure |
| `list_plant_loops` | Identify CHW/HW loops for coil wiring |
| `create_measure` | Write complex HVAC measure with SDK calls |
| `test_measure` | Catch Ruby errors before applying |
| `extract_end_use_breakdown` | Detailed energy comparison by category |

## Air Terminal Types

| Terminal Type | Description | Plant Loops |
|---------------|-------------|-------------|
| VAV_Reheat | Variable air volume with reheat coil | HW |
| CooledBeam | 2-pipe cooling-only beam | CHW only |
| FourPipeBeam | 4-pipe active beam (heating + cooling) | CHW + HW |
| CAV | Constant air volume (no reheat) | None |
| PFP_Electric | Parallel fan-powered with electric reheat | None |

## Notes

- The AI may call `create_measure` more than once if the first attempt has a Ruby syntax error — this is normal self-correction behavior
- `test_measure` validates compilation against an example model; `apply_measure` runs against the loaded model
- `edit_measure` can fix issues without recreating from scratch
- Chilled beams are AIR TERMINALS (connected via `addBranchForZone`), NOT zone equipment

## Integration Test

See `tests/llm/test_04_workflows.py::test_workflow[measure_replace_terminals_full_chain]`
