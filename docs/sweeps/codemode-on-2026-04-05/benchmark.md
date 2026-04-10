# LLM Benchmark Report

**Date:** 2026-04-05T22:50:04+00:00  
**Model:** sonnet | **Retries:** 0 | **CodeMode:** ON  
**Result:** 31/129 passed (24.0%) in 10102s  
**Tokens:** 1.6k in + 300.1k out + 20.3M cache | **Cost:** $22.3458 (notional API pricing)

## Summary by Tier

| Tier   |  Passed |   Rate |   Time |    Avg |
|--------|---------|--------|--------|--------|
| progressive |  31/129 |  24.0% | 10102s |    78s |

## Detailed Results

### progressive

| Test                                | Result | Time | Turns | Tools                                                                                   | In Tok | Out Tok |  Cache |    Cost | Att |
|-------------------------------------|--------|------|-------|-----------------------------------------------------------------------------------------|--------|---------|--------|---------|-----|
| import_floorplan_L1                 |   FAIL | 120s |     0 | get_skill, list_skills                                                                  |      0 |       0 |      0 | $0.0000 |   1 |
| import_floorplan_L2                 |   PASS |  50s |     6 | import_floorspacejs                                                                     |     10 |    2.5k | 100.6k | $0.1176 |   1 |
| import_floorplan_L3                 |   PASS |  96s |     8 | import_floorspacejs                                                                     |     16 |    4.9k | 134.2k | $0.1555 |   1 |
| add_hvac_L1                         |   FAIL |  69s |    10 | load_osm_model, load_osm_model                                                          |     16 |    3.5k | 156.0k | $0.1522 |   1 |
| add_hvac_L2                         |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| add_hvac_L3                         |   FAIL |  96s |     9 | load_osm_model, load_osm_model, load_osm_model                                          |     15 |    1.6k | 235.2k | $0.4525 |   1 |
| view_model_L1                       |   FAIL | 108s |    15 | load_osm_model, load_osm_model                                                          |     22 |    5.3k | 287.4k | $0.2429 |   1 |
| view_model_L2                       |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| view_model_L3                       |   FAIL |  94s |     9 | load_osm_model, load_osm_model                                                          |     18 |    3.0k | 166.9k | $0.3817 |   1 |
| set_weather_L1                      |   FAIL | 120s |     0 | load_osm_model                                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| set_weather_L2                      |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| set_weather_L3                      |   PASS | 120s |     0 | load_osm_model, load_osm_model, change_building_location                                |      0 |       0 |      0 | $0.0000 |   1 |
| run_qaqc_L1                         |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| run_qaqc_L2                         |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| run_qaqc_L3                         |   FAIL |  60s |    12 | load_osm_model                                                                          |     16 |    3.0k | 207.7k | $0.1991 |   1 |
| create_building_L1                  |   FAIL | 120s |     0 | list_skills, list_weather_files                                                         |      0 |       0 |      0 | $0.0000 |   1 |
| create_building_L2                  |   PASS |  54s |     7 | create_new_building                                                                     |     13 |    3.0k | 121.3k | $0.1285 |   1 |
| create_building_L3                  |   PASS |  79s |     8 | create_bar_building                                                                     |     14 |    4.3k | 168.3k | $0.2166 |   1 |
| add_pv_L1                           |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| add_pv_L2                           |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| add_pv_L3                           |   FAIL |  56s |     6 | load_osm_model, load_osm_model                                                          |     10 |    2.7k | 106.3k | $0.1473 |   1 |
| thermostat_L1                       |   FAIL | 120s |     0 | load_osm_model                                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| thermostat_L2                       |   FAIL |  51s |     8 | load_osm_model                                                                          |     15 |    2.8k | 120.6k | $0.1299 |   1 |
| thermostat_L3                       |   FAIL |  80s |    10 | load_osm_model, load_osm_model                                                          |     18 |    3.9k | 209.2k | $0.2123 |   1 |
| list_spaces_L1                      |   FAIL |  56s |    10 | load_osm_model                                                                          |     16 |    3.0k | 167.1k | $0.1703 |   1 |
| list_spaces_L2                      |   PASS |  99s |    12 | load_osm_model, load_osm_model, list_spaces                                             |     19 |    4.2k | 197.0k | $0.1768 |   1 |
| list_spaces_L3                      |   FAIL |  86s |     8 | load_osm_model, load_osm_model                                                          |     14 |    1.3k | 132.9k | $0.3118 |   1 |
| schedules_L1                        |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| schedules_L2                        |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| schedules_L3                        |   PASS | 120s |     0 | load_osm_model, list_model_objects, load_osm_model, list_model_objects                  |      0 |       0 |      0 | $0.0000 |   1 |
| inspect_component_L1                |   FAIL |  83s |    10 | load_osm_model, load_osm_model                                                          |     19 |    1.5k | 214.1k | $0.3361 |   1 |
| inspect_component_L2                |   FAIL | 120s |     0 | load_osm_model, load_osm_model, load_osm_model                                          |      0 |       0 |      0 | $0.0000 |   1 |
| inspect_component_L3                |   FAIL |  90s |    11 | load_osm_model, load_osm_model                                                          |     18 |    4.4k | 264.8k | $0.3014 |   1 |
| modify_component_L1                 |   FAIL |  51s |     8 | load_osm_model, load_osm_model                                                          |     13 |    2.5k | 179.9k | $0.1966 |   1 |
| modify_component_L2                 |   FAIL | 120s |     0 | load_osm_model, load_osm_model, load_osm_model, list_model_objects                      |      0 |       0 |      0 | $0.0000 |   1 |
| modify_component_L3                 |   FAIL |  90s |    15 | load_osm_model, load_osm_model, load_osm_model, list_model_objects                      |     21 |    4.8k | 242.2k | $0.2044 |   1 |
| list_dynamic_type_L1                |   FAIL | 106s |    10 | load_osm_model, load_osm_model                                                          |     18 |    4.8k | 171.7k | $0.2786 |   1 |
| list_dynamic_type_L2                |   PASS | 120s |     0 | load_osm_model, load_osm_model, list_model_objects, load_osm_model, list_model_objects  |      0 |       0 |      0 | $0.0000 |   1 |
| list_dynamic_type_L3                |   PASS |  56s |     9 | load_osm_model, list_model_objects                                                      |     16 |    3.1k | 135.3k | $0.1324 |   1 |
| floor_area_L1                       |   PASS | 110s |     8 | load_osm_model, load_osm_model, get_building_info                                       |     13 |    1.0k | 148.3k | $0.4459 |   1 |
| floor_area_L2                       |   PASS |  97s |     9 | load_osm_model, load_osm_model, get_building_info                                       |     18 |    1.1k | 165.7k | $0.4157 |   1 |
| floor_area_L3                       |   FAIL |  69s |     9 | load_osm_model                                                                          |     19 |    3.7k | 171.2k | $0.1699 |   1 |
| materials_L1                        |   FAIL |  82s |    14 | load_osm_model, load_osm_model, load_osm_model                                          |     20 |    4.2k | 208.3k | $0.2107 |   1 |
| materials_L2                        |   PASS | 110s |    13 | load_osm_model, load_osm_model, list_materials                                          |     22 |    3.4k | 215.1k | $0.3383 |   1 |
| materials_L3                        |   FAIL | 118s |    10 | load_osm_model                                                                          |     20 |    6.0k | 182.5k | $0.2068 |   1 |
| thermal_zones_L1                    |   PASS |  63s |    11 | load_osm_model, load_osm_model, list_thermal_zones                                      |     21 |    3.1k | 193.6k | $0.1550 |   1 |
| thermal_zones_L2                    |   FAIL | 120s |     0 | load_osm_model                                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| thermal_zones_L3                    |   FAIL |  68s |    10 | load_osm_model                                                                          |     17 |    2.9k | 213.3k | $0.2076 |   1 |
| subsurfaces_L1                      |   FAIL |  78s |     8 | load_osm_model, load_osm_model                                                          |     13 |    1.0k | 139.3k | $0.3755 |   1 |
| subsurfaces_L2                      |   FAIL |  60s |     0 | —                                                                                       |      0 |       0 |      0 | $0.0000 |   1 |
| subsurfaces_L3                      |   FAIL |  76s |    10 | load_osm_model, load_osm_model                                                          |     20 |    3.6k | 180.2k | $0.1674 |   1 |
| surface_details_L1                  |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| surface_details_L2                  |   FAIL |  81s |    10 | load_osm_model, load_osm_model                                                          |     19 |    1.6k | 205.7k | $0.3878 |   1 |
| surface_details_L3                  |   FAIL |  78s |    11 | load_osm_model, load_osm_model, load_osm_model                                          |     20 |    2.6k | 236.1k | $0.3762 |   1 |
| run_simulation_L1                   |   FAIL |  96s |     9 | load_osm_model                                                                          |     14 |    4.9k | 140.5k | $0.1722 |   1 |
| run_simulation_L2                   |   FAIL |  86s |    12 | load_osm_model, load_osm_model                                                          |     24 |    4.4k | 288.5k | $0.2508 |   1 |
| run_simulation_L3                   |   FAIL | 144s |     9 | load_osm_model                                                                          |     15 |    2.4k | 174.4k | $0.1570 |   1 |
| get_eui_L1                          |   PASS |  93s |    10 | extract_summary_metrics, extract_summary_metrics, extract_end_use_breakdown             |     22 |    2.7k | 174.0k | $0.2803 |   1 |
| get_eui_L2                          |   PASS | 258s |    40 | extract_summary_metrics                                                                 |     51 |   12.8k |   1.3M | $0.7618 |   1 |
| get_eui_L3                          |   PASS |  99s |    12 | extract_summary_metrics, extract_summary_metrics                                        |     22 |    3.5k | 233.8k | $0.3359 |   1 |
| end_use_breakdown_L1                |   PASS |  51s |     6 | extract_end_use_breakdown, extract_end_use_breakdown                                    |     12 |     719 |  86.9k | $0.1955 |   1 |
| end_use_breakdown_L2                |   PASS |  76s |     6 | extract_end_use_breakdown, extract_end_use_breakdown                                    |     12 |     783 |  87.8k | $0.2445 |   1 |
| end_use_breakdown_L3                |   PASS |  54s |     8 | extract_end_use_breakdown                                                               |     16 |    2.4k | 136.2k | $0.1338 |   1 |
| hvac_sizing_L1                      |   PASS |  58s |     6 | extract_hvac_sizing, extract_hvac_sizing                                                |     12 |     760 |  95.9k | $0.2433 |   1 |
| hvac_sizing_L2                      |   PASS |  58s |     6 | extract_hvac_sizing, extract_hvac_sizing                                                |     12 |     791 |  95.3k | $0.1673 |   1 |
| hvac_sizing_L3                      |   PASS | 135s |    19 | extract_hvac_sizing                                                                     |     29 |    7.1k | 443.6k | $0.3254 |   1 |
| set_wwr_L1                          |   FAIL |  90s |    10 | load_osm_model, load_osm_model                                                          |     14 |    1.4k | 129.5k | $0.3587 |   1 |
| set_wwr_L2                          |   FAIL | 107s |    13 | load_osm_model, load_osm_model                                                          |     18 |    6.0k | 191.4k | $0.2157 |   1 |
| set_wwr_L3                          |   PASS | 120s |     0 | load_osm_model, load_osm_model, list_surfaces, set_window_to_wall_ratio, save_osm_model |      0 |       0 |      0 | $0.0000 |   1 |
| replace_windows_L1                  |   FAIL | 106s |    11 | load_osm_model, load_osm_model                                                          |     13 |    5.5k | 230.6k | $0.3376 |   1 |
| replace_windows_L2                  |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| replace_windows_L3                  |   FAIL |  90s |    12 | load_osm_model, load_osm_model                                                          |     20 |    3.7k | 248.2k | $0.2120 |   1 |
| construction_details_L1             |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| construction_details_L2             |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| construction_details_L3             |   FAIL |  90s |    11 | load_osm_model                                                                          |     20 |    2.1k | 217.1k | $0.3163 |   1 |
| check_loads_L1                      |   FAIL | 120s |     0 | load_osm_model, load_osm_model, load_osm_model                                          |      0 |       0 |      0 | $0.0000 |   1 |
| check_loads_L2                      |   FAIL | 120s |     0 | load_osm_model, load_osm_model, load_osm_model                                          |      0 |       0 |      0 | $0.0000 |   1 |
| check_loads_L3                      |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| create_loads_L1                     |   FAIL |  68s |    10 | load_osm_model, load_osm_model                                                          |     15 |    3.5k | 168.3k | $0.1589 |   1 |
| create_loads_L2                     |   FAIL | 120s |     0 | load_osm_model, list_spaces, load_osm_model                                             |      0 |       0 |      0 | $0.0000 |   1 |
| create_loads_L3                     |   FAIL | 116s |    11 | load_osm_model                                                                          |     20 |    6.1k | 191.3k | $0.2208 |   1 |
| create_plant_loop_L1                |   FAIL | 118s |    12 | load_osm_model, load_osm_model                                                          |     17 |    5.9k | 261.7k | $0.2578 |   1 |
| create_plant_loop_L2                |   FAIL |  72s |     7 | load_osm_model                                                                          |     13 |    3.9k | 120.1k | $0.1389 |   1 |
| create_plant_loop_L3                |   PASS |  79s |     9 | load_osm_model, create_plant_loop                                                       |     16 |    4.3k | 136.6k | $0.1589 |   1 |
| schedule_details_L1                 |   FAIL |  84s |    14 | load_osm_model                                                                          |     21 |    4.7k | 199.8k | $0.1867 |   1 |
| schedule_details_L2                 |   FAIL | 120s |     0 | load_osm_model, load_osm_model, load_osm_model                                          |      0 |       0 |      0 | $0.0000 |   1 |
| schedule_details_L3                 |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| space_type_info_L1                  |   FAIL |  78s |    11 | load_osm_model, load_osm_model                                                          |     18 |    4.1k | 253.5k | $0.2611 |   1 |
| space_type_info_L2                  |   FAIL | 120s |     0 | load_osm_model, load_osm_model, list_model_objects                                      |      0 |       0 |      0 | $0.0000 |   1 |
| space_type_info_L3                  |   FAIL |  69s |     8 | load_osm_model                                                                          |     16 |    3.6k | 137.7k | $0.1496 |   1 |
| set_run_period_L1                   |   PASS | 104s |    11 | load_osm_model, load_osm_model, set_run_period, get_run_period                          |     16 |    3.3k | 175.0k | $0.3013 |   1 |
| set_run_period_L2                   |   PASS | 120s |     0 | load_osm_model, load_osm_model, set_run_period, set_run_period                          |      0 |       0 |      0 | $0.0000 |   1 |
| set_run_period_L3                   |   FAIL | 120s |     0 | load_osm_model                                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| ideal_air_L1                        |   PASS | 120s |     0 | load_osm_model, load_osm_model, enable_ideal_air_loads, load_osm_model                  |      0 |       0 |      0 | $0.0000 |   1 |
| ideal_air_L2                        |   PASS |  49s |     8 | load_osm_model, enable_ideal_air_loads                                                  |     13 |    2.7k | 186.9k | $0.2062 |   1 |
| ideal_air_L3                        |   FAIL |  82s |    12 | load_osm_model, load_osm_model                                                          |     17 |    2.6k | 198.5k | $0.2574 |   1 |
| save_model_L1                       |   FAIL |  61s |    11 | load_osm_model                                                                          |     18 |    3.3k | 219.1k | $0.2806 |   1 |
| save_model_L2                       |   FAIL |  68s |    10 | load_osm_model, load_osm_model                                                          |     16 |    2.9k | 213.1k | $0.1844 |   1 |
| save_model_L3                       |   PASS |  87s |    14 | load_osm_model, save_osm_model, load_osm_model                                          |     24 |    4.4k | 285.4k | $0.2206 |   1 |
| add_ev_L1                           |   FAIL | 120s |     0 | load_osm_model, load_osm_model, load_osm_model                                          |      0 |       0 |      0 | $0.0000 |   1 |
| add_ev_L2                           |   FAIL |  80s |    11 | load_osm_model, load_osm_model, load_osm_model                                          |     13 |    4.2k | 173.7k | $0.1788 |   1 |
| add_ev_L3                           |   FAIL | 120s |     0 | load_osm_model, load_osm_model                                                          |      0 |       0 |      0 | $0.0000 |   1 |
| list_measures_L1                    |   PASS |  46s |     8 | list_custom_measures, list_custom_measures                                              |     14 |    2.3k | 172.6k | $0.1555 |   1 |
| list_measures_L2                    |   PASS |  63s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| list_measures_L3                    |   FAIL |   5s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| create_measure_L1                   |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| create_measure_L2                   |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| create_measure_L3                   |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| test_measure_L1                     |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| test_measure_L2                     |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| test_measure_L3                     |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| apply_existing_measure_L1           |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| apply_existing_measure_L2           |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| apply_existing_measure_L3           |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| replace_terminals_cooled_beam_L1    |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| replace_terminals_cooled_beam_L2    |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| replace_terminals_cooled_beam_L3    |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| replace_terminals_four_pipe_beam_L1 |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| replace_terminals_four_pipe_beam_L2 |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| replace_terminals_four_pipe_beam_L3 |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| measure_replace_terminals_L1        |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| measure_replace_terminals_L2        |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| measure_replace_terminals_L3        |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| zone_equipment_priority_L1          |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| zone_equipment_priority_L2          |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| zone_equipment_priority_L3          |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| edit_measure_L1                     |   FAIL |   3s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| edit_measure_L2                     |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |
| edit_measure_L3                     |   FAIL |   2s |    11 | list_custom_measures                                                                    |     19 |    2.8k | 268.1k | $0.2392 |   1 |

## Progressive Prompt Analysis

Pass rates by specificity level per case:

| Case                 | L1 (vague) | L2 (moderate) | L3 (explicit) |
|----------------------|------------|---------------|---------------|
| import_floorplan     |       FAIL |          PASS |          PASS |
| add_hvac             |       FAIL |          FAIL |          FAIL |
| view_model           |       FAIL |          FAIL |          FAIL |
| set_weather          |       FAIL |          FAIL |          PASS |
| run_qaqc             |       FAIL |          FAIL |          FAIL |
| create_building      |       FAIL |          PASS |          PASS |
| add_pv               |       FAIL |          FAIL |          FAIL |
| thermostat           |       FAIL |          FAIL |          FAIL |
| list_spaces          |       FAIL |          PASS |          FAIL |
| schedules            |       FAIL |          FAIL |          PASS |
| inspect_component    |       FAIL |          FAIL |          FAIL |
| modify_component     |       FAIL |          FAIL |          FAIL |
| list_dynamic_type    |       FAIL |          PASS |          PASS |
| floor_area           |       PASS |          PASS |          FAIL |
| materials            |       FAIL |          PASS |          FAIL |
| thermal_zones        |       PASS |          FAIL |          FAIL |
| subsurfaces          |       FAIL |          FAIL |          FAIL |
| surface_details      |       FAIL |          FAIL |          FAIL |
| run_simulation       |       FAIL |          FAIL |          FAIL |
| get_eui              |       PASS |          PASS |          PASS |
| end_use_breakdown    |       PASS |          PASS |          PASS |
| hvac_sizing          |       PASS |          PASS |          PASS |
| set_wwr              |       FAIL |          FAIL |          PASS |
| replace_windows      |       FAIL |          FAIL |          FAIL |
| construction_details |       FAIL |          FAIL |          FAIL |
| check_loads          |       FAIL |          FAIL |          FAIL |
| create_loads         |       FAIL |          FAIL |          FAIL |
| create_plant_loop    |       FAIL |          FAIL |          PASS |
| schedule_details     |       FAIL |          FAIL |          FAIL |
| space_type_info      |       FAIL |          FAIL |          FAIL |
| set_run_period       |       PASS |          PASS |          FAIL |
| ideal_air            |       PASS |          PASS |          FAIL |
| save_model           |       FAIL |          FAIL |          PASS |
| add_ev               |       FAIL |          FAIL |          FAIL |
| list_measures        |       PASS |          PASS |          FAIL |
| create_measure       |       FAIL |          FAIL |          FAIL |
| test_measure         |       FAIL |          FAIL |          FAIL |
| apply_existing_measure |       FAIL |          FAIL |          FAIL |
| replace_terminals_cooled_beam |       FAIL |          FAIL |          FAIL |
| replace_terminals_four_pipe_beam |       FAIL |          FAIL |          FAIL |
| measure_replace_terminals |       FAIL |          FAIL |          FAIL |
| zone_equipment_priority |       FAIL |          FAIL |          FAIL |
| edit_measure         |       FAIL |          FAIL |          FAIL |

**Summary:** L1=8/43 | L2=12/43 | L3=11/43

## Tool Discovery Overhead

| Metric | Value |
|--------|-------|
| Avg ToolSearch calls/test | 5.8 |
| Max ToolSearch calls | 14 |
| Tests with 0 ToolSearch | 1/129 |

## Failure Mode Analysis

| Mode | Count | Description |
|------|-------|-------------|
| wrong_tool | 67 | MCP tool called but not the expected one |
| timeout | 30 | Timed out before completing |
| no_mcp_tool | 1 | No MCP tool called (stuck in builtins) |

## Failed Tests

- **import_floorplan_L1** (progressive, timeout): 120s, 0 turns, tools: get_skill -> list_skills
- **add_hvac_L1** (progressive, wrong_tool): 69s, 10 turns, tools: load_osm_model -> load_osm_model
- **add_hvac_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **add_hvac_L3** (progressive, wrong_tool): 96s, 9 turns, tools: load_osm_model -> load_osm_model -> load_osm_model
- **view_model_L1** (progressive, wrong_tool): 108s, 15 turns, tools: load_osm_model -> load_osm_model
- **view_model_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **view_model_L3** (progressive, wrong_tool): 94s, 9 turns, tools: load_osm_model -> load_osm_model
- **set_weather_L1** (progressive, timeout): 120s, 0 turns, tools: load_osm_model
- **set_weather_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **run_qaqc_L1** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **run_qaqc_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **run_qaqc_L3** (progressive, wrong_tool): 60s, 12 turns, tools: load_osm_model
- **create_building_L1** (progressive, timeout): 120s, 0 turns, tools: list_skills -> list_weather_files
- **add_pv_L1** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **add_pv_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **add_pv_L3** (progressive, wrong_tool): 56s, 6 turns, tools: load_osm_model -> load_osm_model
- **thermostat_L1** (progressive, timeout): 120s, 0 turns, tools: load_osm_model
- **thermostat_L2** (progressive, wrong_tool): 51s, 8 turns, tools: load_osm_model
- **thermostat_L3** (progressive, wrong_tool): 80s, 10 turns, tools: load_osm_model -> load_osm_model
- **list_spaces_L1** (progressive, wrong_tool): 56s, 10 turns, tools: load_osm_model
- **list_spaces_L3** (progressive, wrong_tool): 86s, 8 turns, tools: load_osm_model -> load_osm_model
- **schedules_L1** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **schedules_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **inspect_component_L1** (progressive, wrong_tool): 83s, 10 turns, tools: load_osm_model -> load_osm_model
- **inspect_component_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model -> load_osm_model
- **inspect_component_L3** (progressive, wrong_tool): 90s, 11 turns, tools: load_osm_model -> load_osm_model
- **modify_component_L1** (progressive, wrong_tool): 51s, 8 turns, tools: load_osm_model -> load_osm_model
- **modify_component_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model -> load_osm_model -> list_model_objects
- **modify_component_L3** (progressive, wrong_tool): 90s, 15 turns, tools: load_osm_model -> load_osm_model -> load_osm_model -> list_model_objects
- **list_dynamic_type_L1** (progressive, wrong_tool): 106s, 10 turns, tools: load_osm_model -> load_osm_model
- **floor_area_L3** (progressive, wrong_tool): 69s, 9 turns, tools: load_osm_model
- **materials_L1** (progressive, wrong_tool): 82s, 14 turns, tools: load_osm_model -> load_osm_model -> load_osm_model
- **materials_L3** (progressive, wrong_tool): 118s, 10 turns, tools: load_osm_model
- **thermal_zones_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model
- **thermal_zones_L3** (progressive, wrong_tool): 68s, 10 turns, tools: load_osm_model
- **subsurfaces_L1** (progressive, wrong_tool): 78s, 8 turns, tools: load_osm_model -> load_osm_model
- **subsurfaces_L2** (progressive, no_mcp_tool): 60s, 0 turns, tools: no tools called
- **subsurfaces_L3** (progressive, wrong_tool): 76s, 10 turns, tools: load_osm_model -> load_osm_model
- **surface_details_L1** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **surface_details_L2** (progressive, wrong_tool): 81s, 10 turns, tools: load_osm_model -> load_osm_model
- **surface_details_L3** (progressive, wrong_tool): 78s, 11 turns, tools: load_osm_model -> load_osm_model -> load_osm_model
- **run_simulation_L1** (progressive, wrong_tool): 96s, 9 turns, tools: load_osm_model
- **run_simulation_L2** (progressive, wrong_tool): 86s, 12 turns, tools: load_osm_model -> load_osm_model
- **run_simulation_L3** (progressive, wrong_tool): 144s, 9 turns, tools: load_osm_model
- **set_wwr_L1** (progressive, wrong_tool): 90s, 10 turns, tools: load_osm_model -> load_osm_model
- **set_wwr_L2** (progressive, wrong_tool): 107s, 13 turns, tools: load_osm_model -> load_osm_model
- **replace_windows_L1** (progressive, wrong_tool): 106s, 11 turns, tools: load_osm_model -> load_osm_model
- **replace_windows_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **replace_windows_L3** (progressive, wrong_tool): 90s, 12 turns, tools: load_osm_model -> load_osm_model
- **construction_details_L1** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **construction_details_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **construction_details_L3** (progressive, wrong_tool): 90s, 11 turns, tools: load_osm_model
- **check_loads_L1** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model -> load_osm_model
- **check_loads_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model -> load_osm_model
- **check_loads_L3** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **create_loads_L1** (progressive, wrong_tool): 68s, 10 turns, tools: load_osm_model -> load_osm_model
- **create_loads_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> list_spaces -> load_osm_model
- **create_loads_L3** (progressive, wrong_tool): 116s, 11 turns, tools: load_osm_model
- **create_plant_loop_L1** (progressive, wrong_tool): 118s, 12 turns, tools: load_osm_model -> load_osm_model
- **create_plant_loop_L2** (progressive, wrong_tool): 72s, 7 turns, tools: load_osm_model
- **schedule_details_L1** (progressive, wrong_tool): 84s, 14 turns, tools: load_osm_model
- **schedule_details_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model -> load_osm_model
- **schedule_details_L3** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **space_type_info_L1** (progressive, wrong_tool): 78s, 11 turns, tools: load_osm_model -> load_osm_model
- **space_type_info_L2** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model -> list_model_objects
- **space_type_info_L3** (progressive, wrong_tool): 69s, 8 turns, tools: load_osm_model
- **set_run_period_L3** (progressive, timeout): 120s, 0 turns, tools: load_osm_model
- **ideal_air_L3** (progressive, wrong_tool): 82s, 12 turns, tools: load_osm_model -> load_osm_model
- **save_model_L1** (progressive, wrong_tool): 61s, 11 turns, tools: load_osm_model
- **save_model_L2** (progressive, wrong_tool): 68s, 10 turns, tools: load_osm_model -> load_osm_model
- **add_ev_L1** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model -> load_osm_model
- **add_ev_L2** (progressive, wrong_tool): 80s, 11 turns, tools: load_osm_model -> load_osm_model -> load_osm_model
- **add_ev_L3** (progressive, timeout): 120s, 0 turns, tools: load_osm_model -> load_osm_model
- **list_measures_L3** (progressive, wrong_tool): 5s, 11 turns, tools: list_custom_measures
- **create_measure_L1** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **create_measure_L2** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **create_measure_L3** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **test_measure_L1** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **test_measure_L2** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **test_measure_L3** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **apply_existing_measure_L1** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **apply_existing_measure_L2** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **apply_existing_measure_L3** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **replace_terminals_cooled_beam_L1** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **replace_terminals_cooled_beam_L2** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **replace_terminals_cooled_beam_L3** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **replace_terminals_four_pipe_beam_L1** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **replace_terminals_four_pipe_beam_L2** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **replace_terminals_four_pipe_beam_L3** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **measure_replace_terminals_L1** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **measure_replace_terminals_L2** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **measure_replace_terminals_L3** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **zone_equipment_priority_L1** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **zone_equipment_priority_L2** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **zone_equipment_priority_L3** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **edit_measure_L1** (progressive, wrong_tool): 3s, 11 turns, tools: list_custom_measures
- **edit_measure_L2** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
- **edit_measure_L3** (progressive, wrong_tool): 2s, 11 turns, tools: list_custom_measures
