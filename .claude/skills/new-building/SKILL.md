---
name: new-building
description: Create a complete building model from scratch — geometry, envelope, loads, HVAC, weather, and simulation. Use when user wants to "create a building", "build a model", or "start a new model".
disable-model-invocation: true
---

# Create a Complete Building Model

Three workflows, from simplest to most customizable:

## Workflow A: One-Call (Recommended)

`create_new_building` does everything — geometry, loads, HVAC, weather, design days:
```
create_new_building(
    building_type="SmallOffice",
    total_bldg_floor_area=10000,
    num_stories_above_grade=1,
    weather_file="/inputs/<city>.epw",
    template="90.1-2019")
```
Ready to simulate immediately.

## Workflow B: Bar + Typical (More Control)

Step 1 — Bar geometry (creates spaces, zones, surfaces):
```
create_bar_building(
    building_type="SmallOffice",
    total_bldg_floor_area=10000,
    num_stories_above_grade=1,
    template="90.1-2019",
    climate_zone="4A")
```

Step 2 — Weather + design days + climate zone (MUST come AFTER bar):
```
change_building_location(weather_file="/inputs/<city>.epw")
```
This sets the EPW, loads design days from the DDY file, and sets the ASHRAE climate zone.
The EPW must have companion `.stat` and `.ddy` files alongside it (same base filename).

Step 3 — Typical building (adds constructions, loads, HVAC, schedules):
```
create_typical_building(
    climate_zone="ASHRAE 169-2013-4A",
    building_type="SmallOffice")
```

## Workflow C: FloorspaceJS Custom Geometry

For buildings with custom floor plans drawn in FloorspaceJS editor
(https://nrel.github.io/floorspace.js/):

Step 1 — Import geometry:
```
import_floorspacejs(
    floorplan_path="/inputs/floorplan.json",
    building_type="SmallOffice")
```
Creates spaces, zones with thermostats, surfaces, and runs matching.

Step 2 — Weather + design days (same as Workflow B steps 2-3)

Step 3 — Typical building (same as Workflow B step 4)

## Manual Workflow (Advanced)

For fully custom buildings not matching DOE prototypes:

1. `create_example_osm(name="<name>")` or `create_baseline_osm(name="<name>")`
2. Create geometry with `create_space_from_floor_print` + `match_surfaces`
3. Add glazing with `set_window_to_wall_ratio`
4. Create materials/constructions/loads manually
5. Add HVAC with `add_baseline_system`
6. Set weather + design days
7. Simulate

## Simulation

After any workflow:
```
save_osm_model(save_path="/runs/<name>.osm")
run_simulation(osm_path="/runs/<name>.osm", epw_path="/inputs/<city>.epw")
get_run_status(run_id=<id>)
extract_summary_metrics(run_id=<id>)
```

## Information to Gather

Ask the user for:
- **Building type:** SmallOffice, MediumOffice, LargeOffice, RetailStandalone,
  Warehouse, PrimarySchool, Hospital, etc.
- **Size:** floor area in ft2, number of stories
- **Location:** city or climate zone (for weather file + ASHRAE climate zone)
- **Custom geometry?** If yes, ask for FloorspaceJS JSON file path

## Climate Zone Format

For create_typical_building, use full format: "ASHRAE 169-2013-4A"
For create_bar_building, short form works: "4A"
