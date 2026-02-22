# Example 15: Guided HVAC Selection (`/add-hvac`)

Get a recommendation for the right HVAC system based on building characteristics.

## Scenario

An engineer has a model with zones but no HVAC. They want help choosing the right system type. The `/add-hvac` skill inspects the building, recommends an ASHRAE 90.1 baseline system, and applies it.

## Prompt

> /add-hvac

## Tool Call Sequence

```
1. get_building_info()                        # building type, floor area
2. list_thermal_zones()                       # zone count, names
3. Recommends system type based on ASHRAE 90.1 Table G3.1.1
4. add_baseline_system(system_type=3,
     thermal_zone_names=["Zone 1", "Zone 2", ...],
     heating_fuel="NaturalGas")
5. list_air_loops()                           # verify loops created
6. list_zone_hvac_equipment()                 # verify zone equipment
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `get_building_info` | Building type, area, stories for system selection |
| `list_thermal_zones` | Get zone names to connect to HVAC |
| `add_baseline_system` | Apply ASHRAE system template |
| `list_air_loops` | Verify air loops were created |
| `list_zone_hvac_equipment` | Confirm equipment attached to zones |

## ASHRAE System Selection Logic

| Building Type | Area | Heating Fuel | System |
|---------------|------|-------------|--------|
| Non-residential | < 25,000 sqft | Fossil | 3 (PSZ-AC) |
| Non-residential | < 25,000 sqft | Electric | 4 (PSZ-HP) |
| Non-residential | >= 25,000 sqft & <= 150,000 sqft | Any | 5 (Packaged VAV) |
| Non-residential | > 150,000 sqft | Any | 7 (VAV w/ Reheat) |
| Residential | Any | Fossil | 1 (PTAC) |
| Residential | Any | Electric | 2 (PTHP) |

## Notes

- Uses `create_example_osm` (minimal model) for the test, not `create_baseline_osm` (which includes HVAC)
- The skill uses background knowledge from `ashrae-baseline-guide` to inform recommendations

## Integration Test

See `tests/test_skill_add_hvac.py::test_skill_add_hvac_workflow`
