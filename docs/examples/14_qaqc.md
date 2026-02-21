# Example 14: Model Quality Check (`/qaqc`)

Check a model for common issues before running a simulation.

## Scenario

Before spending time on a simulation, an engineer wants to verify their model is complete — zones have HVAC, spaces are assigned, weather is set, and no objects are missing. The `/qaqc` skill inspects the model and reports issues by severity.

## Prompt

> /qaqc

## Tool Call Sequence

```
1. inspect_osm_summary(osm_path=...)    # structural overview of model file
2. get_model_summary()                  # object counts by type
3. list_thermal_zones()                 # zones present? zones without HVAC?
4. list_spaces()                        # spaces assigned to zones?
5. get_weather_info()                   # EPW file attached?
6. get_run_period()                     # simulation dates configured?
7. list_zone_hvac_equipment()           # HVAC equipment present?
8. Reports issues by severity (errors, warnings, info)
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `inspect_osm_summary` | File-level model structure check |
| `get_model_summary` | Count of each object type |
| `list_thermal_zones` | Verify zones exist and are connected |
| `list_spaces` | Verify spaces assigned to zones |
| `get_weather_info` | Check for attached weather file |
| `get_run_period` | Verify simulation period is set |
| `list_zone_hvac_equipment` | Confirm HVAC equipment exists |

## Common Issues Detected

| Severity | Issue |
|----------|-------|
| Error | No thermal zones defined |
| Error | No HVAC equipment on any zone |
| Warning | No weather file attached |
| Warning | Spaces not assigned to thermal zones |
| Info | Default run period (annual) in use |

## Notes

- No simulation required — this is a pre-flight check
- Claude can auto-invoke this skill when it detects model issues

## Integration Test

See `tests/test_skill_qaqc.py::test_skill_qaqc_workflow`
