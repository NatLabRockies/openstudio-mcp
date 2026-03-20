# Benchmark: Description Guidance Before/After

## Before (pre-guidance, current descriptions)

### Confusion Pairs (test_10): 8/8 PASS (100%)

| Test | Result | Tools called |
|------|--------|-------------|
| qaqc_vs_validate_post_sim | PASS | run_qaqc_checks |
| validate_vs_qaqc_pre_sim | PASS | validate_model |
| load_details_vs_space_details | PASS | get_load_details |
| summary_metrics_vs_end_use | PASS | extract_summary_metrics |
| end_use_vs_summary_metrics | PASS | extract_end_use_breakdown |
| inspect_osm_vs_model_summary | PASS | inspect_osm_summary |
| create_baseline_vs_new_building | PASS | create_new_building |
| apply_measure_vs_create_measure | PASS | apply_measure |

### L1 Failures (test_06 progressive): 3/7 PASS (42.9%)

| Test | Result | Expected | Got instead |
|------|--------|----------|-------------|
| import_floorplan_L1 | PASS | import_floorspacejs | — |
| thermostat_L1 | PASS | adjust_thermostat_setpoints | — |
| save_model_L1 | PASS | save_osm_model | — |
| run_qaqc_L1 | FAIL | run_qaqc_checks | validate_model |
| list_dynamic_type_L1 | FAIL | list_model_objects | get_sizing_zone_properties x10 |
| replace_windows_L1 | FAIL | replace_window_constructions | list_model_objects, get_construction_details, list_common_measures |
| check_loads_L1 | FAIL | get_load_details | list_spaces, get_space_details, get_space_type_details |

**Total before: 11/15 (73.3%)**

---

## After (post-guidance, ~35 tools changed)

Changes: confusion pair disambiguation (16 tools), when-to-use (7),
emphasis keywords (8), short expansion (12). Docker rebuilt.

### Confusion Pairs (test_10): 8/8 PASS (100%) — unchanged

### L1 Failures (test_06 progressive): 3/7 PASS (42.9%) — unchanged

| Test | Before | After | Expected | Still got |
|------|--------|-------|----------|-----------|
| import_floorplan_L1 | PASS | PASS | — | — |
| thermostat_L1 | PASS | PASS | — | — |
| save_model_L1 | PASS | PASS | — | — |
| run_qaqc_L1 | FAIL | FAIL | run_qaqc_checks | validate_model |
| list_dynamic_type_L1 | FAIL | FAIL | list_model_objects | get_sizing_zone_properties x10 |
| replace_windows_L1 | FAIL | FAIL | replace_window_constructions | list_model_objects, list_materials, list_common_measures |
| check_loads_L1 | FAIL | FAIL | get_load_details | list_spaces, get_space_details, get_space_type_details |

**Total after: 11/15 (73.3%) — no change**

## Conclusion

Description guidance (when-to-use, negative scope, emphasis) did not
improve L1 tool selection. The 4 failures are structural:

- **run_qaqc_L1:** "Check model for issues" → validate_model is a
  reasonable choice (it IS checking for issues, pre-sim)
- **list_dynamic_type_L1:** "What sizing parameters?" → using explicit
  sizing tools is arguably more correct than generic list
- **replace_windows_L1:** "Upgrade the windows" → agent explores
  constructions/materials before finding the bulk-replace tool
- **check_loads_L1:** "What loads?" → agent inspects spaces (which
  contain loads) rather than calling load-specific tool

These are not description problems. The prompts are genuinely ambiguous
and the agent's alternative tool choices are reasonable.
