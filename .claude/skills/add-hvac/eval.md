## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Add HVAC to the model" | add_baseline_system | system_type, thermal_zone_names |
| "Set up heating and cooling" | add_baseline_system OR add_vrf_system | — |
| "What HVAC system should I use?" | list_baseline_systems, get_baseline_system_info | — |
| "Add a VAV reheat system with a chiller and boiler plant" | add_baseline_system | system_type=7 |
| "Swap the DX coil on the air loop for a two-speed coil" | replace_air_loop_supply_component | air_loop_name, component_name, new_component_type=CoilCoolingDXTwoSpeed |
| "Put a hot water preheat coil upstream of the cooling coil on the VAV loop" | add_air_loop_supply_component | component_type=CoilHeatingWater, insert_before, plant_loop_name |
| "Add an outdoor air reset setpoint manager to the VAV loop" | add_setpoint_manager | spm_type=SetpointManagerOutdoorAirReset, air_loop_name, replace_existing |
| "Add a scheduled setpoint manager to the hot water loop" | add_setpoint_manager | spm_type=SetpointManagerScheduled, plant_loop_name, schedule_name |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "Change the coil efficiency" | add_baseline_system, add_doas_system, add_vrf_system, add_radiant_system | set_component_properties, get_component_properties, list_model_objects |
| "Replace the cooling coil on the air loop" | add_baseline_system, create_measure, delete_object | replace_air_loop_supply_component, get_air_loop_details |
| "Add a boiler to the loop" | add_baseline_system, add_doas_system | add_supply_equipment, list_plant_loops |
| "What air loops exist?" | add_baseline_system, add_doas_system, add_vrf_system | list_air_loops |
