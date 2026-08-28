## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Compare before and after adding insulation" | save_osm_model, run_simulation, extract_summary_metrics (x2) | — |
| "What energy savings from better windows?" | replace_window_constructions, run_simulation | — |
| "Evaluate an ECM" | save_osm_model, apply_measure, run_simulation, compare_runs | — |
| "Do a retrofit analysis" | save_osm_model, run_simulation x2, extract_summary_metrics x2 | — |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "Change wall insulation" | compare_runs | create_standard_opaque_material, add_layer_to_construction, assign_construction_to_surface, get_construction_details, list_model_objects |
| "Run a simulation" | compare_runs | run_simulation, save_osm_model |
| "Create a new building" | compare_runs, replace_window_constructions | create_new_building, create_bar_building, create_baseline_osm |
