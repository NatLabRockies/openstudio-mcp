# Example 2: HVAC System Design Exploration

Iterate on HVAC design by adding a DOAS system, inspecting plant loops, and tuning component properties.

## Scenario

A mechanical engineer is designing a DOAS + fan coil system for an office. They want to set chilled water to 44F and hot water to 140F, then inspect the cooling tower sizing.

## Prompt

> Create a 10-zone building with a DOAS + fan coil system. Set the chilled water supply to 44F and the hot water to 140F. What components are on each plant loop?

## Tool Call Sequence

```
1. create_baseline_osm(name="doas_office", ashrae_sys_num="07")
2. load_osm_model(osm_path=...)
3. add_doas_system(thermal_zone_names=[...], zone_equipment_type="FanCoil")
4. list_plant_loops()
5. set_sizing_properties(plant_loop_name="Chilled Water Loop",
     design_loop_exit_temperature_c=6.67)
6. set_sizing_properties(plant_loop_name="Hot Water Loop",
     design_loop_exit_temperature_c=60.0)
7. get_plant_loop_details(plant_loop_name="Chilled Water Loop")
8. get_plant_loop_details(plant_loop_name="Hot Water Loop")
```

### Follow-up: Tune Cooling Tower

```
9.  list_hvac_components()
10. get_component_properties(component_name="Cooling Tower...")
11. set_component_properties(component_name="Cooling Tower...",
      properties={"design_water_flow_rate_m3_per_s": 0.005})
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `add_doas_system` | Creates DOAS air loop + zone fan coils |
| `set_sizing_properties` | Adjusts plant loop temperatures |
| `list_hvac_components` | Discovers all HVAC components |
| `get/set_component_properties` | Read and modify equipment |

## Supported Zone Equipment Types

| Type | Description |
|------|-------------|
| `FanCoil` | Four-pipe fan coil unit |
| `Radiant` | Low-temp radiant floor/ceiling |
| `ChilledBeam` | Active chilled beam |

## Integration Test

See `tests/test_example_workflows.py::test_workflow_hvac_design_exploration`
