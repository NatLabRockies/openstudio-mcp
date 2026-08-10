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
`create_construction(material_names=[...])` for building NEW assemblies from
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

User must provide an EPW file in the docker-mounted input directory.
`change_building_location` sets weather, design days (from DDY), and climate zone in one call.
The EPW must have companion `.stat` and `.ddy` files alongside it (same directory, same base filename).

```
list_files()                              # find available weather files
change_building_location(weather_file="/inputs/Chicago.epw")
```

## Fair HVAC System Sweep (decision-grade comparison)

Compare candidate systems on the SAME configured model — standards-tuned
equipment/controls each time, loads and schedules never touched:

```
# One-time setup: geometry + weather + typical build + any load customizations
create_bar_building(...); change_building_location(...)
create_typical_building(template="90.1-2019", climate_zone="ASHRAE 169-2013-5A")
# ... apply load reductions, setbacks, etc. ...

# Per candidate: swap ONLY the HVAC, simulate, compare
create_typical_building(system_type="PVAV with gas boiler reheat",
    template="90.1-2019", climate_zone="ASHRAE 169-2013-5A", hvac_only=True)
save_osm_model(osm_path="/runs/sweep_pvav.osm"); run_simulation(...)

create_typical_building(system_type="PSZ-HP", ..., hvac_only=True)
save_osm_model(osm_path="/runs/sweep_pszhp.osm"); run_simulation(...)

compare_runs(run_id_a, run_id_b)          # EUI + unmet-hours deltas
```

Do NOT use add_baseline_system/add_doas_system for comparative studies — they
are generic wiring templates without standards tuning (see add-hvac skill).

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

## Write and Apply a Custom Measure

Full chain: create → test → apply → simulate → compare results.

```
# 1. Baseline simulation
save_osm_model(save_path="/runs/baseline.osm")
run_simulation(osm_path="/runs/baseline.osm", epw_path="<epw>")
extract_summary_metrics(run_id=<baseline_id>)

# 2. Create custom measure
create_measure(name="my_measure", description="...",
    language="Ruby", run_body="    model.get...each { |x| ... }")
test_measure(measure_dir="/runs/custom_measures/my_measure")

# 3. Reload original model, apply measure, re-simulate
load_osm_model(osm_path="<original>")
apply_measure(measure_dir="/runs/custom_measures/my_measure")
save_osm_model(save_path="/runs/retrofit.osm")
run_simulation(osm_path="/runs/retrofit.osm", epw_path="<epw>")
extract_summary_metrics(run_id=<retrofit_id>)

# 4. Compare baseline vs retrofit EUI
```

See the `measure-authoring` skill for run_body patterns and language guidance.

For HVAC measures, verify methods exist and get wiring code first:
```
search_api("CoilCoolingFourPipeBeam")             # check real setter/getter names
search_wiring_patterns("four pipe beam")           # get working Ruby wiring code
```

## Write and Apply a Custom ReportingMeasure

ReportingMeasures run after simulation to analyze SQL results.

```
# 1. Run simulation first
run_simulation(osm_path="/runs/model.osm", epw_path="<epw>")

# 2. Create reporting measure
create_measure(name="custom_report", description="...",
    language="Ruby", measure_type="ReportingMeasure",
    run_body="    val = sql.execAndReturnFirstDouble('SELECT ...')\n    runner.registerValue('metric', val.get) if val.is_initialized")

# 3. Test against completed simulation
test_measure(measure_dir="/runs/custom_measures/custom_report", run_id="<run_id>")

# 4. Apply to completed simulation
apply_measure(measure_dir="/runs/custom_measures/custom_report", run_id="<run_id>")
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
