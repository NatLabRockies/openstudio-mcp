---
name: tool-workflows
description: Multi-tool recipes for common building energy modeling tasks. Use when chaining tools together for operations like adding windows, changing insulation, setting up HVAC, or running simulations.
user-invocable: false
---

# Tool Workflow Recipes

## Simulation Workflow

```
save_osm_model(save_path="/runs/model.osm")
  → run_simulation(osm_path="/runs/model.osm", epw_path="/inputs/weather.epw")
  → get_run_status(run_id=...)          # poll until "completed"
  → extract_summary_metrics(run_id=...) # EUI, energy, unmet hours
  → extract_end_use_breakdown(run_id=...)  # by fuel + end use
```

## Full Results Extraction

After simulation completes, extract all result categories:
```
extract_summary_metrics(run_id=...)       # EUI, total energy, unmet hours
extract_end_use_breakdown(run_id=...)     # energy by end use and fuel
extract_envelope_summary(run_id=...)      # U-values, areas, SHGC
extract_hvac_sizing(run_id=...)           # zone and system sizing
extract_zone_summary(run_id=...)          # per-zone areas, temps, loads
extract_component_sizing(run_id=...)      # autosized component values
query_timeseries(run_id=..., variable_name="Electricity:Facility", frequency="Monthly")
```

## Add Windows to a Wall

```
list_surfaces()                           # find exterior wall names + azimuths
set_window_to_wall_ratio(surface_name="South Wall", ratio=0.4)
```

For different ratios per orientation, bin surfaces by azimuth:
- South: 135-225 degrees
- North: 315-360, 0-45 degrees
- East: 45-135 degrees
- West: 225-315 degrees

## Change Wall Insulation

```
create_standard_opaque_material(
    name="R20_Insulation", thickness_m=0.089,
    conductivity_w_m_k=0.04, density_kg_m3=30, specific_heat_j_kg_k=1000)
create_construction(
    name="High_R_Wall",
    material_names=["Exterior Finish", "R20_Insulation", "Gypsum Board"])
assign_construction_to_surface(
    surface_name="South Wall", construction_name="High_R_Wall")
```

Repeat `assign_construction_to_surface` for each exterior wall, or use `replace_window_constructions` for bulk window replacement.

## Add Internal Loads to a Space

```
create_schedule_ruleset(name="Office_Occ", schedule_type="Fractional", default_value=0.5)
create_people_definition(
    name="Office People", space_name="Open Office",
    people_per_area=0.059, schedule_name="Office_Occ")
create_lights_definition(
    name="Office Lights", space_name="Open Office", watts_per_area=10.76)
create_electric_equipment(
    name="Office Plugs", space_name="Open Office", watts_per_area=1.076)
```

## Set Up Weather

User must provide EPW and DDY files in the docker-mounted input directory.

```
list_files()                              # find available weather files
set_weather_file(epw_path="/inputs/Chicago.epw")
add_design_day(name="Chicago Htg 99.6%", day_type="WinterDesignDay",
    month=1, day=21, dry_bulb_max_c=-20.6, dry_bulb_range_c=0.0)
add_design_day(name="Chicago Clg 0.4%", day_type="SummerDesignDay",
    month=7, day=21, dry_bulb_max_c=33.3, dry_bulb_range_c=10.7)
```

## HVAC System Setup

### Quick baseline
```
list_thermal_zones()                      # get zone names
add_baseline_system(system_type=7,
    thermal_zone_names=["Zone1", "Zone2", "Zone3"],
    heating_fuel="NaturalGas")
list_air_loops()                          # verify
```

### Tune component properties
```
list_hvac_components(category="Coil")     # find component names
get_component_properties(component_name="Heating Coil 1")
set_component_properties(component_name="Heating Coil 1",
    properties={"efficiency": 0.95})
```

### Modify economizer
```
set_economizer_properties(air_loop_name="VAV System",
    economizer_type="DifferentialEnthalpy")
```

### Adjust plant loop sizing
```
set_sizing_properties(component_name="Chilled Water Loop",
    design_loop_exit_temperature_c=6.67,
    loop_design_temperature_difference_c=5.56)
```

## Model Quality Check

```
inspect_osm_summary()                    # object counts, missing elements
get_model_summary()                      # category-level overview
run_qaqc_checks(template="90.1-2019")   # ASHRAE compliance checks
```

## Retrofit / Before-After Comparison

```
# 1. Baseline
save_osm_model(save_path="/runs/baseline.osm")
run_simulation(osm_path="/runs/baseline.osm", epw_path="/inputs/weather.epw")
extract_summary_metrics(run_id=<baseline_id>)   # save baseline EUI

# 2. Apply measure
adjust_thermostat_setpoints(cooling_offset_f=2.0, heating_offset_f=-2.0)
# or: replace_window_constructions(construction_name="Triple Pane Low-E")
# or: add_rooftop_pv(fraction_of_roof=0.5)

# 3. Post-retrofit
save_osm_model(save_path="/runs/retrofit.osm")
run_simulation(osm_path="/runs/retrofit.osm", epw_path="/inputs/weather.epw")
extract_summary_metrics(run_id=<retrofit_id>)   # compare EUI

# 4. Compare baseline vs retrofit results
```

## Geometry from Scratch

```
create_example_osm(name="my_building")
load_osm_model(osm_path=...)

# Create zones first
create_thermal_zone(name="Zone West")
create_thermal_zone(name="Zone East")

# Extrude floor polygons into 3D spaces
create_space_from_floor_print(name="West Office",
    floor_vertices=[[0,0],[10,0],[10,10],[0,10]],
    floor_to_ceiling_height=3.0, thermal_zone_name="Zone West")
create_space_from_floor_print(name="East Office",
    floor_vertices=[[10,0],[20,0],[20,10],[10,10]],
    floor_to_ceiling_height=3.0, thermal_zone_name="Zone East")

# Match shared walls (interior boundary conditions)
match_surfaces()

# Add glazing
set_window_to_wall_ratio(surface_name="South Wall 1", ratio=0.4)
```

## Apply External Measure

```
list_measure_arguments(measure_dir="/inputs/measures/my_measure")
apply_measure(measure_dir="/inputs/measures/my_measure",
    arguments={"param1": "value1", "param2": "42"})
```

Note: All measure arguments are strings. Booleans → `"true"` / `"false"`. Numbers → `"42"`.

## Object Cleanup

```
list_model_objects(object_type="Space")   # find objects
rename_object(object_name="Zone 1", new_name="North Office")
delete_object(object_name="Unused Space")
clean_unused_objects()                    # remove orphans
```
