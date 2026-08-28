---
name: tool-workflows
description: Multi-tool recipes for common building energy modeling tasks. Use when chaining tools together for operations like adding windows, changing insulation, setting up HVAC, or running simulations.
eval-exempt: "reference workflows; no single action-tool selection to assert"
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

## Change Wall/Roof Insulation

Add a layer to the EXISTING construction — do not rebuild the assembly from a
hand-typed material list (that silently drops the original membrane/decking
layers and can make the envelope worse):

```
create_standard_opaque_material(
    name="R20_Insulation", thickness_m=0.089,
    conductivity_w_m_k=0.04, density_kg_m3=30, specific_heat_j_kg_k=1000)
add_layer_to_construction(
    construction_name="ASHRAE 90.1 Ext Wall", material_name="R20_Insulation")
    # keeps all existing layers; verify assembly_r_si_after > assembly_r_si_before
assign_construction_to_surface(
    surface_name="South Wall", construction_name="ASHRAE 90.1 Ext Wall + R20_Insulation")
```

Repeat `assign_construction_to_surface` for each target surface, or use
`replace_window_constructions` for bulk window replacement. Reserve
`create_construction(name=..., material_names=[...])` for building NEW assemblies from
scratch, where you specify every layer deliberately.

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

Weather files are SERVER-side (remote clients stage their own with `request_upload`).
`change_building_location` sets weather, design days (from DDY), and climate zone in one call.
The EPW must have companion `.stat` and `.ddy` files alongside it (same directory, same base filename).

```
list_weather_files()                      # find available weather files
change_building_location(weather_file="/inputs/Chicago.epw")
```

## Fair HVAC System Sweep (decision-grade comparison)

Owned by the `add-hvac` skill — see its "Comparing Systems / Decision-Grade
Results" section (`get_skill("add-hvac")`): per-candidate
`create_typical_building(system_type=..., hvac_only=True)` swaps on the SAME
configured model, then `compare_runs`. Do NOT use
add_baseline_system/add_doas_system for comparative studies — generic wiring
templates, no standards tuning.

## Tune Component Properties

```
list_model_objects(object_type="CoilHeatingGas")  # find component names
get_component_properties(component_name="Heating Coil 1")
set_component_properties(component_name="Heating Coil 1",
    properties={"efficiency": 0.95})
```

### Economizer
```
set_economizer_properties(air_loop_name="VAV System",
    properties='{"economizer_control_type": "DifferentialEnthalpy"}')
```

### Plant Loop Sizing
```
set_sizing_properties(loop_name="Chilled Water Loop",
    properties='{"design_loop_exit_temperature_c": 6.67, "loop_design_temperature_difference_c": 5.56}')
```

## Apply External Measure

```
list_measure_arguments(measure_dir="/inputs/measures/my_measure")
apply_measure(measure_dir="/inputs/measures/my_measure",
    arguments={"param1": "value1", "param2": "42"})
```

Note: All measure arguments are strings. Booleans → `"true"` / `"false"`. Numbers → `"42"`.

## Write and Apply a Custom Measure / ReportingMeasure

Owned by the `measure-authoring` skill (`get_skill("measure-authoring")`):
the create_measure → test_measure → apply_measure chain, run_body patterns
(Ruby + Python), ReportingMeasures against a completed run
(`test_measure(measure_dir=..., run_id=...)` /
`apply_measure(measure_dir=..., run_id=...)`), and the before/after
comparison workflow. For HVAC measures, verify methods and wiring first:
```
search_api("CoilCoolingFourPipeBeam")             # check real setter/getter names
search_wiring_patterns("four pipe beam")           # get working Ruby wiring code
```

## Object Cleanup

```
list_model_objects(object_type="Space")   # find objects
rename_object(object_name="Zone 1", new_name="North Office")
delete_object(object_name="Unused Space")
clean_unused_objects()                    # remove orphans
```

## Inspect & Modify Any Object (Generic Access)

```
# Read all properties of any object
get_object_fields(object_type="BoilerHotWater", object_name="Boiler Hot Water 1")
# → returns property values + available setter methods

# Write a property using the discovered setter
set_object_property(object_type="BoilerHotWater", object_name="Boiler Hot Water 1",
    property_name="nominalThermalEfficiency", value=0.92)

# Works with any type — SizingSystem, CoilCoolingWater, etc.
get_object_fields(object_type="SizingSystem", object_name="VAV Sys 1 Sizing System")
```

Note: Always call `get_object_fields` first to discover property names and setter availability before using `set_object_property`.
