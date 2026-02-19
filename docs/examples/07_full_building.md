# Example 7: Full Building Model — Ready to Simulate

Build a complete energy model programmatically — starting from a baseline with geometry, adding loads, weather, design days — then run EnergyPlus.

## Scenario

An engineer wants to start from a baseline model with ASHRAE System 5 (packaged VAV with reheat), add internal loads, set weather and design days, then run a simulation.

## Prompt

> Create a baseline model with System 5, add office loads, set Chicago weather with design days, and run a simulation.

## Tool Call Sequence

```
 1. create_baseline_osm(name="office_building", ashrae_sys_num="05")
 2. load_osm_model(osm_path=...)
 3. list_spaces()    # find existing spaces with geometry
 4. create_people_definition(name="Office People",
      space_name=<first_space>, people_per_area=0.059)
 5. create_lights_definition(name="Office Lights",
      space_name=<first_space>, watts_per_area=10.76)
 6. set_weather_file(epw_path="/inputs/Chicago.epw")
 7. add_design_day(name="Chicago Heating 99.6%",
      day_type="WinterDesignDay", month=1, day=21,
      dry_bulb_max_c=-20.6, dry_bulb_range_c=0.0)
 8. add_design_day(name="Chicago Cooling .4%",
      day_type="SummerDesignDay", month=7, day=21,
      dry_bulb_max_c=33.3, dry_bulb_range_c=10.7)
 9. save_osm_model(save_path="/runs/office_building.osm")
10. run_simulation(osm_path="/runs/office_building.osm",
      epw_path="/inputs/Chicago.epw")
11. get_run_status(run_id=...)    # poll until "success"
12. extract_summary_metrics(run_id=...)
```

## Workflow Phases

### Phase 1: Baseline Model (Steps 1-3)
Start with `create_baseline_osm` which generates a multi-zone model with geometry, thermal zones, constructions, thermostats, and HVAC (System 5 = packaged VAV with reheat). This gives you a simulation-ready starting point.

### Phase 2: Internal Loads (Steps 4-5)
Add occupancy and lighting loads to spaces. These drive the simulation's internal heat gains.

### Phase 3: Weather & Design Days (Steps 6-8)
- **Weather file**: drives the annual simulation hour-by-hour
- **Design days**: used for HVAC sizing calculations (peak heating/cooling conditions)

### Phase 4: Simulate & Review (Steps 9-12)
Save the model, run EnergyPlus, poll for completion, and extract key metrics.

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `create_baseline_osm` | Multi-zone model with geometry + HVAC |
| `create_people_definition` | Occupancy loads |
| `create_lights_definition` | Lighting loads |
| `set_weather_file` | Attach EPW to model |
| `add_design_day` | Heating/cooling design conditions |
| `run_simulation` | Run EnergyPlus from OSM + EPW |
| `extract_summary_metrics` | EUI, energy, unmet hours |

## Integration Test

See `tests/test_example_workflows.py::test_workflow_full_building`

The integration test runs an actual EnergyPlus simulation (sizing period) and verifies successful completion with metrics extraction.
