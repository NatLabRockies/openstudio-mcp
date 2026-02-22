---
name: qaqc
description: Run model quality checks before simulation. Use when user asks to "check the model", "validate", "QA/QC", or before running a simulation.
---

# Model Quality Check

Inspect the current model for common issues before running a simulation.

## Steps

1. Get model overview:
   ```
   inspect_osm_summary()
   get_model_summary()
   ```

2. Check for missing critical elements:
   - **Zones without HVAC:** `list_thermal_zones()` — look for zones with no equipment
   - **Spaces without zones:** `list_spaces()` — look for spaces not assigned to a thermal zone
   - **Missing constructions:** `list_surfaces()` — look for surfaces without constructions
   - **No weather file:** `get_weather_info()` — check if EPW is attached
   - **No design days:** needed for HVAC sizing
   - **No run period:** `get_run_period()` — check if simulation dates are set

3. Run ASHRAE QA/QC checks (if model has been simulated):
   ```
   run_qaqc_checks(template="90.1-2019")
   ```

4. Report findings organized by severity:

   **Errors** (will cause simulation failure):
   - Missing weather file
   - Zones with no HVAC and no ideal air loads
   - Surfaces with no construction

   **Warnings** (may produce bad results):
   - Zones with no loads (people, lights, equipment)
   - Missing design days (HVAC won't autosize)
   - No run period set (only sizing runs)
   - Unmet hours above threshold

   **Info** (notable but not problems):
   - Object counts by category
   - Total conditioned area
   - HVAC system types in use

5. Suggest fixes for each issue found, referencing specific tools.
