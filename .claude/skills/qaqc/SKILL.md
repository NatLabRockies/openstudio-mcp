---
name: qaqc
description: Run model quality checks before simulation. Use when user asks to "check the model", "validate", "QA/QC", or before running a simulation.
---

# Model Quality Check

Inspect the current model for common issues before running a simulation.

## Steps

1. Quick automated check:
   ```
   validate_model()
   ```
   Checks weather, design days, HVAC, constructions in one call.

2. Get model overview:
   ```
   get_model_summary()
   get_building_info()
   ```

3. Check for missing critical elements:
   - **Zones without HVAC:** `list_thermal_zones()` — look for zones with no equipment
   - **Spaces without zones:** `list_spaces()` — look for spaces not assigned to a thermal zone
   - **Missing constructions:** `list_surfaces()` — look for surfaces without constructions
   - **No weather file:** `get_weather_info()` — check if EPW is attached
   - **No design days:** needed for HVAC sizing
   - **No run period:** `get_run_period()` — check if simulation dates are set

4. Run ASHRAE QA/QC checks (if model has been simulated):
   ```
   run_qaqc_checks(run_id=<completed run_id>, template="90.1-2019")
   ```

5. Report findings organized by severity (same buckets `validate_model` uses):

   **Errors** (will cause simulation failure):
   - Missing design days (HVAC sizing fails)
   - Air loops serving no thermal zones (EnergyPlus fatal)
   - Single-zone setpoint managers without a control zone (EnergyPlus fatal)

   **Warnings** (may fail later or produce bad results):
   - No weather file on the model (can still pass epw_path to run_simulation)
   - Zones with no HVAC and no ideal air loads
   - Surfaces with no construction
   - Zones with no loads (people, lights, equipment)
   - No run period set (only sizing runs)
   - Unmet hours above threshold

   **Info** (notable but not problems):
   - Object counts by category
   - Total conditioned area
   - HVAC system types in use

6. Suggest fixes for each issue found, referencing specific tools.
