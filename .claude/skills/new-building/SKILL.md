---
name: new-building
description: Create a complete building model from scratch — geometry, envelope, loads, HVAC, weather, and simulation. Use when user wants to "create a building", "build a model", or "start a new model".
disable-model-invocation: true
---

# Create a Complete Building Model

Guide the user through creating a full building energy model step by step.

## Information to Gather

Ask the user for:
- **Building type:** office, retail, school, hospital, warehouse, residential
- **Size:** approximate floor area, number of floors
- **Geometry:** rectangular footprint dimensions, or custom floor plan
- **Climate/location:** city or climate zone
- **HVAC preference:** baseline system, or specific type
- **Weather file location:** EPW/DDY file path in docker-mounted directory

## Steps

### 1. Create Base Model
```
create_example_osm(name="<building_name>")
load_osm_model(osm_path=<path>)
```

Or for a pre-configured baseline with HVAC:
```
create_baseline_osm(name="<building_name>", ashrae_sys_num="<NN>")
load_osm_model(osm_path=<path>)
```

### 2. Geometry
Create thermal zones first, then extrude floor plans:
```
create_thermal_zone(name="Zone 1")
create_space_from_floor_print(
    name="Space 1",
    floor_vertices=[[0,0],[20,0],[20,15],[0,15]],
    floor_to_ceiling_height=3.0,
    thermal_zone_name="Zone 1")
```

For multi-zone buildings, create adjacent spaces and match shared walls:
```
match_surfaces()
```

### 3. Glazing
```
set_window_to_wall_ratio(surface_name="South Wall", ratio=0.4)
```

### 4. Envelope
```
create_standard_opaque_material(name="Insulation", thickness_m=0.089,
    conductivity_w_m_k=0.04, density_kg_m3=30, specific_heat_j_kg_k=1000)
create_construction(name="Ext Wall", material_names=["Brick", "Insulation", "Gypsum"])
assign_construction_to_surface(surface_name="South Wall", construction_name="Ext Wall")
```

### 5. Schedules
```
create_schedule_ruleset(name="Occupancy", schedule_type="Fractional", default_value=0.5)
```

### 6. Internal Loads
```
create_people_definition(name="People", space_name="Space 1",
    people_per_area=0.059, schedule_name="Occupancy")
create_lights_definition(name="Lights", space_name="Space 1", watts_per_area=10.76)
create_electric_equipment(name="Plugs", space_name="Space 1", watts_per_area=1.076)
```

### 7. HVAC
```
add_baseline_system(system_type=3,
    thermal_zone_names=["Zone 1"], heating_fuel="NaturalGas")
```

### 8. Weather
Ask user for EPW file location in the docker-mounted input directory:
```
list_files()
set_weather_file(epw_path="/inputs/<file>.epw")
add_design_day(name="Htg 99.6%", day_type="WinterDesignDay",
    month=1, day=21, dry_bulb_max_c=-20.6, dry_bulb_range_c=0.0)
add_design_day(name="Clg 0.4%", day_type="SummerDesignDay",
    month=7, day=21, dry_bulb_max_c=33.3, dry_bulb_range_c=10.7)
```

### 9. Simulate
```
save_osm_model(save_path="/runs/<building_name>.osm")
run_simulation(osm_path="/runs/<building_name>.osm", epw_path="/inputs/<file>.epw")
get_run_status(run_id=<id>)
extract_summary_metrics(run_id=<id>)
```

## Shortcut: Typical Building

For standards-based buildings with full loads/HVAC/schedules, use ComStock:
```
create_example_osm(name="<building_name>")
load_osm_model(osm_path=<path>)
# ... create geometry ...
create_typical_building(template="90.1-2019", climate_zone="ASHRAE 169-2013-5A")
```

This adds constructions, loads, HVAC, and schedules in one step.
