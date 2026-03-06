## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Add HVAC to the model" | add_baseline_system | system_type, thermal_zone_names |
| "Set up heating and cooling" | add_baseline_system OR add_vrf_system | — |
| "What HVAC system should I use?" | list_baseline_systems, get_baseline_system_info | — |
| "Add a VAV system" | add_baseline_system | system_type=7 |

## Should NOT trigger
| Query | Why |
|---|---|
| "Change the coil efficiency" | Component property — use set_component_properties |
| "Add a boiler to the loop" | Loop surgery — use add_supply_equipment |
| "What air loops exist?" | Query — use list_air_loops |
