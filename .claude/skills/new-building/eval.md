## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Create a small office building" | create_new_building OR create_bar_building | building_type present |
| "Build me a new model from scratch" | create_new_building OR create_bar_building OR create_example_osm | — |
| "Start a new building energy model" | create_new_building OR create_bar_building OR create_example_osm | — |
| "Model a 3-story school" | create_new_building OR create_bar_building | num_stories_above_grade=3 |
| "Create a retail building, 25000 sqft" | create_new_building OR create_bar_building | building_type=RetailStandalone, total_bldg_floor_area=25000 |
| "Import the FloorspaceJS floor plan at /test-assets/sddc_office/floorplan.json" | import_floorspacejs | floorplan_path present |
| "Create a bar building for a medium office" | create_bar_building | building_type=MediumOffice |
| "Create a complete building with weather" | create_new_building | weather_file present |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "What spaces are in the model?" | create_new_building, create_bar_building | list_spaces, get_model_summary |
| "Add a boiler to the hot water loop" | create_new_building, create_bar_building | add_supply_equipment, list_plant_loops |
| "Run the simulation" | create_new_building, create_bar_building | run_simulation, load_osm_model, list_files |
| "Add HVAC to the building" | create_new_building, create_bar_building | add_baseline_system, list_thermal_zones, list_baseline_systems, get_model_summary, load_osm_model |
