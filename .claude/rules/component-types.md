---
description: Recipes for adding HVAC component types and setpoint manager types
globs:
  - mcp_server/skills/component_properties/**
---

## Adding New Component Types
To add a new HVAC component type to `component_properties`:
1. Add `_get_<type>_props(obj)` in `components.py` — returns dict of property_name -> {"value": ..., "unit": "..."}. Comment each API call.
2. Add `_set_<type>_props(obj, properties)` — explicit if/elif per property. Returns (changes_dict, errors_list).
3. Add entry to `COMPONENT_TYPES` at bottom of `components.py`.
4. Add test in `tests/test_component_properties.py`.

## Adding Setpoint Manager Types
To add a new SPM type to `set_setpoint_manager_properties`:
1. Add `_get_spm_<type>_props(obj)` in `operations.py` — returns dict of property_name -> {"value": ..., "unit": "..."}
2. Add `_set_spm_<type>_props(obj, properties)` — explicit if/elif per property. Returns (changes_dict, errors_list).
3. Add entry to `SPM_TYPES` registry with getter method name and get/set functions.
4. Add test in `tests/test_component_controls.py`.
5. `add_setpoint_manager` / `remove_setpoint_manager` (`loop_operations/setpoint_managers.py`) need an explicit constructor branch in `_construct_spm` and a `get<Type>ByName` branch in `_find_spm`; add a case to `tests/test_add_setpoint_manager.py`.

## Critical
**No getattr() or string-based dispatch.** Every OpenStudio API method must be called directly — grepable, lintable, visible in stack traces.
