---
name: tool-workflows
description: Multi-tool recipes for common building energy modeling tasks. Use when chaining tools together for operations like adding windows, changing insulation, setting up HVAC, or running simulations.
user-invocable: false
---

# Tool Workflow Recipes

> Full workflows for simulation, results, HVAC setup, retrofit, geometry, and QA/QC
> are in dedicated skills. Call `list_skills()` to see them.

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

User must provide an EPW file in the docker-mounted input directory.
`change_building_location` sets weather, design days (from DDY), and climate zone in one call.

```
list_files()                              # find available weather files
change_building_location(weather_file="/inputs/Chicago.epw")
```

## Tune Component Properties

```
list_hvac_components(category="Coil")     # find component names
get_component_properties(component_name="Heating Coil 1")
set_component_properties(component_name="Heating Coil 1",
    properties={"efficiency": 0.95})
```

### Economizer
```
set_economizer_properties(air_loop_name="VAV System",
    economizer_type="DifferentialEnthalpy")
```

### Plant Loop Sizing
```
set_sizing_properties(component_name="Chilled Water Loop",
    design_loop_exit_temperature_c=6.67,
    loop_design_temperature_difference_c=5.56)
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
