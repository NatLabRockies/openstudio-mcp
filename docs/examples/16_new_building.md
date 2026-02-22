# Example 16: Complete Building from Scratch (`/new-building`)

Create a full building model with geometry, loads, HVAC, weather, and run a simulation.

## Scenario

An engineer wants to create a new office building model from scratch and run an energy simulation. The `/new-building` skill walks through the entire process: starting from a baseline, adding glazing, schedules, internal loads, weather data, and running through to results.

## Prompt

> /new-building

## Tool Call Sequence

```
1.  create_baseline_osm(name="office", ashrae_sys_num="03")
2.  load_osm_model(osm_path=<returned path>)
3.  list_thermal_zones()                          # verify zones from baseline
4.  list_spaces()                                 # get space names for loads
5.  list_surfaces()                               # find exterior walls
6.  set_window_to_wall_ratio(
      surface_name="Story 1 South Wall", ratio=0.4)
7.  create_schedule_ruleset(name="Occ Schedule",
      schedule_type="Fractional", default_value=0.5)
8.  create_people_definition(name="Office People",
      space_name=<first space>, people_per_area=0.059,
      schedule_name="Occ Schedule")
9.  create_lights_definition(name="Office Lights",
      space_name=<first space>, watts_per_area=10.76)
10. create_electric_equipment(name="Office Plugs",
      space_name=<first space>, watts_per_area=1.076)
11. list_air_loops()                              # verify HVAC from baseline
12. set_weather_file(epw_path="/inputs/weather.epw")
13. add_design_day(name="Htg 99.6%", day_type="WinterDesignDay",
      month=1, day=21, dry_bulb_max_c=-20.6, dry_bulb_range_c=0.0)
14. add_design_day(name="Clg 0.4%", day_type="SummerDesignDay",
      month=7, day=21, dry_bulb_max_c=33.3, dry_bulb_range_c=10.7)
15. save_osm_model(save_path="/runs/office.osm")
16. run_simulation(osm_path="/runs/office.osm", epw_path="/inputs/weather.epw")
17. get_run_status(run_id=...)                    # poll until complete
18. extract_summary_metrics(run_id=...)
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `create_baseline_osm` | 10-zone model with ASHRAE system |
| `set_window_to_wall_ratio` | Add glazing to exterior walls |
| `create_schedule_ruleset` | Occupancy/operation schedules |
| `create_people_definition` | Occupancy loads |
| `create_lights_definition` | Lighting power density |
| `create_electric_equipment` | Plug loads |
| `set_weather_file` | Attach EPW weather file |
| `add_design_day` | HVAC sizing conditions |
| `run_simulation` | Launch EnergyPlus |
| `extract_summary_metrics` | Get simulation results |

## Typical Load Values

| Load Type | Office | Retail | School |
|-----------|--------|--------|--------|
| People (per m2) | 0.059 | 0.108 | 0.108 |
| Lighting (W/m2) | 10.76 | 14.0 | 12.9 |
| Equipment (W/m2) | 1.076 | 1.08 | 5.38 |

## Integration Test

See `tests/test_skill_new_building.py::test_skill_new_building_workflow`
