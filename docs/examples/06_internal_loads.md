# Example 4: Internal Loads Setup

Define occupancy, lighting, and equipment loads for office spaces with schedules.

## Scenario

A modeler is setting up internal loads for an open office space per ASHRAE 90.1 requirements: people density, lighting power density, and plug load density.

## Prompt

> Add people at 5.5 per 1000 sqft, lighting at 10 W/sqft, and plug loads at 1 W/sqft to the open office space. Use an occupancy schedule that's on during business hours.

## Tool Call Sequence

```
1. create_schedule_ruleset(name="Office_Occ",
     schedule_type="Fractional", default_value=0.5)
2. create_people_definition(name="Office People",
     space_name="Open Office", people_per_area=0.059,
     schedule_name="Office_Occ")
3. create_lights_definition(name="Office Lights",
     space_name="Open Office", watts_per_area=10.76)
4. create_electric_equipment(name="Office Plugs",
     space_name="Open Office", watts_per_area=1.076)
5. list_people_loads()
6. list_lighting_loads()
```

## Unit Conversions

The OpenStudio API uses SI units (metric). Common conversions:

| IP Value | SI Value | Notes |
|----------|----------|-------|
| 5.5 people/1000 sqft | 0.059 people/m2 | Occupancy density |
| 10 W/sqft | 10.76 W/m2 | Lighting power density |
| 1 W/sqft | 1.076 W/m2 | Equipment power density |
| 0.3 CFM/sqft | 0.00152 m3/s/m2 | Infiltration rate |

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `create_schedule_ruleset` | Fractional schedule for occupancy |
| `create_people_definition` | People by area or count |
| `create_lights_definition` | Lights by W/m2 or total watts |
| `create_electric_equipment` | Equipment by W/m2 or total watts |
| `create_gas_equipment` | Gas equipment (kitchens, labs) |
| `create_infiltration` | Infiltration by area flow or ACH |

## Available Schedule Types

| Type | Range | Use For |
|------|-------|---------|
| `Fractional` | 0.0 - 1.0 | Occupancy, lighting fractions |
| `Temperature` | any float | Thermostat setpoints |
| `OnOff` | 0 or 1 | Equipment on/off |

## Integration Test

See `tests/test_example_workflows.py::test_workflow_internal_loads`
