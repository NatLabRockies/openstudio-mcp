---
name: troubleshoot
description: Diagnose simulation failures and unexpected results. Use when user says "simulation failed", "error", "EUI looks wrong", "unmet hours", or when get_run_status shows failure.
user-invocable: true
disable-model-invocation: true
---

# Troubleshoot Simulation Issues

## Simulation Failed

1. Check status and logs:
```
get_run_status(run_id=...)
get_run_logs(run_id=..., log_type="stderr")
```

2. Common fatal errors and fixes:

| Error pattern | Cause | Fix |
|---|---|---|
| `No weather file` | Missing or wrong EPW path | `change_building_location(weather_file="/inputs/...")` |
| `No SizingPeriod` | Missing design days | `change_building_location` (loads DDY automatically) |
| `Could not find the stat file` | EPW missing companion .stat/.ddy | EPW needs .stat + .ddy files alongside with same base filename |
| `Node not connected` | Broken HVAC loop | Check with `get_air_loop_details` / `get_plant_loop_details` |
| `Surface has no vertices` | Bad geometry | Check `list_surfaces()` for degenerate surfaces |
| `Zone has no surfaces` | Empty thermal zone | Zone needs spaces with geometry assigned |

## Results Look Wrong

1. Check EUI range (typical commercial: 50-200 kBtu/ft2):
```
extract_summary_metrics(run_id=...)
```

2. Common causes of bad EUI:

**EUI too high:**
- Missing/wrong thermostat schedules → `get_schedule_details`, `set_thermostat_schedules`
- Oversized HVAC → `extract_hvac_sizing` to check autosizing
- High infiltration → `list_infiltration`

**EUI too low:**
- Missing internal loads → `list_people_loads`, `list_lighting_loads`, `list_electric_equipment`
- No HVAC (ideal air or missing) → `list_air_loops`, `list_zone_hvac_equipment`
- Wrong run period (partial year) → `get_run_period`

**High unmet hours:**
- Undersized equipment → `extract_component_sizing`
- Thermostat vs availability schedule conflict
- Missing plant loop equipment → `get_plant_loop_details`

3. Detailed diagnostics:
```
extract_zone_summary(run_id=...)          # per-zone temps and loads
extract_component_sizing(run_id=...)      # autosized values
query_timeseries(run_id=..., variable_name="Zone Mean Air Temperature",
    frequency="Hourly", key_value="Zone 1")
```

## Quick Fixes

| Problem | Tool |
|---|---|
| Add missing weather | `change_building_location` (sets EPW + DDY + climate zone) |
| Add missing HVAC | `add_baseline_system` |
| Remove broken objects | `clean_unused_objects` |
| Check model completeness | `run_qaqc_checks` |
| Inspect without simulating | `inspect_osm_summary` |
