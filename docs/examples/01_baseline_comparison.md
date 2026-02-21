# Example 1: Energy Code Baseline Comparison

Compare ASHRAE 90.1 System 3 (PSZ-AC) vs System 7 (VAV) for a commercial building.

## Scenario

An engineer needs to evaluate which baseline HVAC system produces lower energy use for a 10-zone office. This is a common ASHRAE 90.1 Appendix G workflow.

## Prompt

> Create a baseline model with ASHRAE System 3, set the Chicago weather file, and run a simulation. Then do the same with System 7 and compare the EUI.

## Tool Call Sequence

### System 3 (PSZ-AC)

```
1. create_baseline_osm(name="office_sys3", ashrae_sys_num="03")
2. load_osm_model(osm_path=<returned path>)
3. set_weather_file(epw_path="/inputs/Chicago.epw")
4. add_design_day(name="Chicago Heating 99.6%",
     day_type="WinterDesignDay", month=1, day=21,
     dry_bulb_max_c=-20.6, dry_bulb_range_c=0.0)
5. add_design_day(name="Chicago Cooling .4%",
     day_type="SummerDesignDay", month=7, day=21,
     dry_bulb_max_c=33.3, dry_bulb_range_c=10.7)
6. save_osm_model(save_path="/runs/office_sys3.osm")
7. run_simulation(osm_path="/runs/office_sys3.osm", epw_path="/inputs/Chicago.epw")
8. get_run_status(run_id=<returned id>)   # poll until "success"
9. extract_summary_metrics(run_id=<id>)   # EUI, energy by fuel, unmet hours
```

### System 7 (VAV w/ Reheat)

Repeat steps 1-9 with `ashrae_sys_num="07"`.

### Compare

The AI compares:

- **EUI** (kBtu/ft2/yr) — total energy use intensity
- **Heating/cooling energy** — fuel breakdown
- **Unmet hours** — comfort compliance

## Key Tools Used

| Tool                      | Purpose                                           |
| ------------------------- | ------------------------------------------------- |
| `create_baseline_osm`     | Creates 10-zone model with ASHRAE system          |
| `set_weather_file`        | Attaches EPW to the model                         |
| `add_design_day`          | Heating/cooling design conditions for HVAC sizing |
| `run_simulation`          | Creates OSW and runs EnergyPlus                   |
| `extract_summary_metrics` | Extracts EUI and unmet hours                      |

## ASHRAE Baseline Systems Reference

| System | Type          | Typical Use                      |
| ------ | ------------- | -------------------------------- |
| 01     | PTAC          | Hotels, small offices            |
| 03     | PSZ-AC        | Small commercial (<25,000 sqft)  |
| 05     | Packaged VAV  | Medium commercial                |
| 07     | VAV w/ Reheat | Large commercial (>150,000 sqft) |

## Integration Test

See `tests/test_example_workflows.py::test_workflow_baseline_with_weather`

The integration test runs an actual EnergyPlus simulation (sizing period) and verifies successful completion with metrics extraction.
