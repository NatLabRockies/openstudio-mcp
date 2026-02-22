# Example 17: Retrofit Analysis (`/retrofit`)

Apply energy conservation measures and compare before/after performance.

## Scenario

An engineer has a baseline building model and wants to evaluate the energy savings from widening the thermostat deadband. The `/retrofit` skill automates the baseline simulation, applies the ECM, re-simulates, and compares results.

## Prompt

> /retrofit

## Tool Call Sequence

```
1.  create_baseline_osm(name="retro", ashrae_sys_num="03")
2.  load_osm_model(osm_path=<returned path>)
3.  set_weather_file(epw_path="/inputs/weather.epw")
4.  add_design_day(name="Htg", day_type="WinterDesignDay", ...)
5.  add_design_day(name="Clg", day_type="SummerDesignDay", ...)
6.  save_osm_model(save_path="/runs/baseline.osm")
7.  run_simulation(osm_path="/runs/baseline.osm", epw_path=...)
8.  get_run_status(run_id=<baseline>)             # poll until done
9.  extract_summary_metrics(run_id=<baseline>)    # record baseline EUI
10. adjust_thermostat_setpoints(
      cooling_offset_f=2.0, heating_offset_f=-2.0)
11. save_osm_model(save_path="/runs/retrofit.osm")
12. run_simulation(osm_path="/runs/retrofit.osm", epw_path=...)
13. get_run_status(run_id=<retrofit>)              # poll until done
14. extract_summary_metrics(run_id=<retrofit>)     # compare EUI
15. Presents side-by-side comparison
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `create_baseline_osm` | Create reference building |
| `run_simulation` | Run both baseline and retrofit simulations |
| `extract_summary_metrics` | Get EUI for comparison |
| `adjust_thermostat_setpoints` | Apply thermostat ECM |
| `save_osm_model` | Save baseline and retrofit variants |

## Available ECMs

| ECM | Tool | Typical Savings |
|-----|------|-----------------|
| Thermostat deadband | `adjust_thermostat_setpoints` | 5-15% HVAC |
| Window upgrade | `replace_window_constructions` | 5-10% envelope |
| Roof insulation | `create_construction` + `assign_construction_to_surface` | 3-8% envelope |
| LED lighting | `create_lights_definition` | 20-40% lighting |
| Rooftop PV | `add_rooftop_pv` | 10-30% total |

## Notes

- Both simulations use the same weather file and design days for valid comparison
- The retrofit modifies the in-memory model, so the baseline is saved first
- Multiple ECMs can be stacked before the retrofit simulation

## Integration Test

See `tests/test_skill_retrofit.py::test_skill_retrofit_workflow`
