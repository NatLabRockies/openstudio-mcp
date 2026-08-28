## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Add HVAC to the model" | add_baseline_system | system_type, thermal_zone_names |
| "Set up heating and cooling" | add_baseline_system OR add_vrf_system | — |
| "What HVAC system should I use?" | list_baseline_systems, get_baseline_system_info | — |
| "Add a VAV reheat system with a chiller and boiler plant" | add_baseline_system | system_type=7 |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "Change the coil efficiency" | add_baseline_system, add_doas_system, add_vrf_system, add_radiant_system | set_component_properties, get_component_properties, list_model_objects |
| "Add a boiler to the loop" | add_baseline_system, add_doas_system | add_supply_equipment, list_plant_loops |
| "What air loops exist?" | add_baseline_system, add_doas_system, add_vrf_system | list_air_loops |
