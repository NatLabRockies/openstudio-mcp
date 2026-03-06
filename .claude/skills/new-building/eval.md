## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Create a 5-zone office" | create_baseline_osm, load_osm_model | ashrae_sys_num present |
| "Build me a new model from scratch" | create_example_osm OR create_baseline_osm | — |
| "Start a new building energy model" | create_example_osm OR create_baseline_osm | — |
| "Model a 3-story school with packaged rooftop units" | create_baseline_osm | num_floors=3, ashrae_sys_num |

## Should NOT trigger
| Query | Why |
|---|---|
| "What spaces are in the model?" | Query — use list_spaces |
| "Add a boiler to the hot water loop" | Modification — use add_supply_equipment |
| "Run the simulation" | Simulation — use simulate skill |
