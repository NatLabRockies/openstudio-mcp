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
| Query | Why |
|---|---|
| "What spaces are in the model?" | Query — use list_spaces |
| "Add a boiler to the hot water loop" | Modification — use add_supply_equipment |
| "Run the simulation" | Simulation — use simulate skill |
| "Add HVAC to the building" | HVAC — use add-hvac skill |
