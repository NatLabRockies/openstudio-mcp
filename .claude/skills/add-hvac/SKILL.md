---
name: add-hvac
description: Guided HVAC system selection and setup. Use when user asks to "add HVAC", "set up heating and cooling", or "what HVAC system should I use".
---

# Add HVAC System

Guide the user through selecting and applying an HVAC system to their model.

## Steps

1. Understand the current model:
   ```
   get_building_info()
   list_thermal_zones()
   ```

2. Ask the user about:
   - Building type (office, residential, retail, warehouse, etc.)
   - Heating fuel preference (natural gas, electric, district)
   - Any specific system preference (baseline, DOAS, VRF, radiant)

3. Recommend a system using ASHRAE 90.1 Table G3.1.1 logic (see `ashrae-baseline-guide` skill for selection criteria):
   - Residential → System 1 (PTAC) or 2 (PTHP)
   - Small non-residential → System 3 (PSZ-AC) or 4 (PSZ-HP)
   - Large non-residential → System 5/7 (VAV reheat) or 6/8 (VAV PFP)
   - Heated-only → System 9 or 10
   - High ventilation needs → DOAS
   - Many small zones → VRF
   - Comfort-critical → Radiant

4. Apply the selected system:
   ```
   # For baseline systems (1-10):
   add_baseline_system(system_type=<N>,
       thermal_zone_names=[<zone_names>],
       heating_fuel="NaturalGas")

   # For modern templates:
   add_doas_system(thermal_zone_names=[...], zone_equipment_type="FanCoil")
   add_vrf_system(thermal_zone_names=[...])
   add_radiant_system(thermal_zone_names=[...], radiant_type="Floor")
   ```

5. Verify the installation:
   ```
   list_air_loops()
   list_plant_loops()
   list_zone_hvac_equipment()
   ```

6. Report what was created: system name, zones served, equipment types, plant loops.

## Custom HVAC Wiring

For custom HVAC configurations beyond the baseline templates:
```
search_wiring_patterns("DOAS")                     # get working Ruby wiring code
search_api("CoilCoolingFourPipeBeam")              # verify SDK method names
```

## Comparing Systems / Decision-Grade Results

The generic templates above (add_baseline_system, add_doas_system, add_vrf_system)
are wiring templates — no standards efficiency tuning or availability-manager
coordination. For comparative studies or decision-grade EUI/comfort numbers, use
the standards-tuned path instead:

```
# Replace ONLY the HVAC on an already-configured model — loads, constructions,
# schedules, thermostats preserved. One call per candidate system:
create_typical_building(system_type="PVAV with gas boiler reheat",
    template="90.1-2019", climate_zone="ASHRAE 169-2013-5A", hvac_only=True)
save_osm_model(...); run_simulation(...)   # then next candidate

compare_runs(baseline_run_id=<run A>, retrofit_run_id=<run B>)  # EUI + unmet-hours deltas
```

## Notes

- Get all zone names from `list_thermal_zones()` — names must match exactly
- Systems 3-4 create one air loop per zone — pass the full zone list in one
  call, the tool fans out automatically
- Systems 5-8 create one shared air loop for all zones (multi-zone VAV)
- Systems 1-2, 9-10 create zone equipment only (no air loops)
