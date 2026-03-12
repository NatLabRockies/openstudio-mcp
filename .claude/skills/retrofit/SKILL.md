---
name: retrofit
description: Analyze energy conservation measures — apply upgrades and compare before/after performance. Use when user asks about "retrofit", "upgrade", "ECM", "energy savings", or "what-if analysis".
disable-model-invocation: true
---

# Retrofit Analysis

Apply energy conservation measures to an existing model and compare before/after performance.

## Steps

### 1. Establish Baseline
Ensure a simulation has been run on the current model. If not:
```
save_osm_model(save_path="/runs/baseline.osm")
run_simulation(osm_path="/runs/baseline.osm", epw_path="<epw>")
get_run_status(run_id=<id>)
extract_summary_metrics(run_id=<baseline_id>)
```
Record baseline EUI and end-use breakdown.

### 2. Identify Upgrade Opportunities
Inspect the model to suggest relevant ECMs:
```
get_building_info()
list_model_objects(object_type="Construction")
list_air_loops()
list_zone_hvac_equipment()
```

### 3. Apply Selected Measures
Ask the user which upgrades to apply. Available ECM tools:

**Envelope:**
- `replace_window_constructions(construction_name="Triple Low-E")` — bulk replace windows
- `create_standard_opaque_material` + `create_construction` + `assign_construction_to_surface` — upgrade walls/roof

**HVAC/Controls:**
- `adjust_thermostat_setpoints(cooling_offset_f=2.0, heating_offset_f=-2.0)` — widen deadband
- `replace_thermostat_schedules(...)` — new thermostat schedules
- `shift_schedule_time(shift_value_hours=1)` — shift occupancy/HVAC schedules

**Renewables:**
- `add_rooftop_pv(fraction_of_roof=0.5)` — rooftop solar
- `add_pv_to_shading(...)` — PV on shading surfaces

**Loads:**
- `enable_ideal_air_loads()` — remove HVAC for load-only studies
- `add_zone_ventilation(...)` — modify ventilation rates
- `add_ev_load(...)` — add EV charging

**Model Cleanup:**
- `clean_unused_objects()` — remove orphans before re-simulation

See [ecm-catalog.md](ecm-catalog.md) for typical savings ranges.

### 4. Re-Simulate
```
save_osm_model(save_path="/runs/retrofit.osm")
run_simulation(osm_path="/runs/retrofit.osm", epw_path="<epw>")
get_run_status(run_id=<id>)
extract_summary_metrics(run_id=<retrofit_id>)
extract_end_use_breakdown(run_id=<retrofit_id>)
```

### 5. Compare Results
Present side-by-side comparison:
- EUI change (absolute and percentage)
- End-use breakdown delta (which categories improved)
- Unmet hours change (ensure comfort wasn't sacrificed)

## Notes

- Always save to a new path before re-simulating to preserve the baseline
- Multiple ECMs can be stacked before re-simulating
- Some measures modify the model in-memory (thermostat, window); others run as OpenStudio measures
