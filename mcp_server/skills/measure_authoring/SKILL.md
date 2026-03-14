# measure_authoring

Create, test, edit, and apply custom OpenStudio measures.

## Overview

Measures are the primary extension mechanism for OpenStudio models. They modify a model programmatically (ModelMeasure) or extract post-simulation results (ReportingMeasure). This skill handles the full lifecycle: scaffold, inject code, test, apply.

## Workflow

```
create_measure → test_measure → apply_measure
```

Use `edit_measure` to iterate on existing measures. Use `list_custom_measures` to find previously created measures.

## Argument Strategy — Make Measures Reusable

**Parameterize anything model-specific.** Hard-code only measure logic (traversal, formulas, output structure).

| What to parameterize | Argument type | Example |
|---|---|---|
| Setpoints, thresholds, R-values, W/m2 | Double | `target_r_value`, default 19.0 |
| Object names, filters | String | `zone_name_filter`, default "" |
| Enable/disable features | Boolean | `apply_to_exterior_only`, default true |
| Predefined options | Choice (with `values`) | `insulation_type`, values: ["fiberglass", "foam", "mineral_wool"] |
| Counts, priorities | Integer | `max_zones`, default 0 (all) |

**Bad:** Hard-coding `surface.name.include?("Exterior Wall")` and R-value 19.

**Good:** Arguments `surface_filter` (String, default ""), `target_r_value` (Double, default 19.0) so the measure works on any model.

## Argument Schema

```json
{
  "name": "target_r_value",
  "display_name": "Target R-Value (ft2-F-hr/Btu)",
  "description": "Units in ft2-F-hr/Btu. Applied to all matching surfaces.",
  "type": "Double",
  "required": true,
  "default_value": "19.0"
}
```

**Always include `description`** — it becomes the argument's help text in the measure UI and XML.

For Choice arguments, also include `values`:
```json
{
  "name": "insulation_type",
  "display_name": "Insulation Type",
  "description": "Material type determines thermal conductivity used in R-value calculation.",
  "type": "Choice",
  "required": true,
  "default_value": "fiberglass",
  "values": ["fiberglass", "foam", "mineral_wool"]
}
```

Types: `Boolean` | `Double` | `Integer` | `String` | `Choice`

**Auto-generated code:** Argument extraction (`runner.get*ArgumentValue`) is auto-generated above the `# --- begin user logic ---` marker. `run_body` should NOT include argument extraction — just reference the variables directly.

## Tools

### create_measure
Scaffold a new measure with user-provided run() body and arguments. Output: `/runs/custom_measures/<name>/`.

### test_measure
Run tests against a real model (not empty). Auto-detects language. For ReportingMeasures, provide `run_id` of a completed simulation.

### edit_measure
Replace run() body, arguments, or description on an existing measure. Use to add arguments to a measure that hard-codes values.

### list_custom_measures
List all measures in `/runs/custom_measures/`.

### apply_measure
Apply a measure to the currently loaded model (from `measure_application` skill).

### list_measure_arguments
Inspect arguments of any measure (from `measure_application` skill).

## Unit Conversion

`OpenStudio.convert(value, from_unit, to_unit).get` — composable unit parser.

Syntax: `*` (multiply), `/` (divide), `^` (exponent). Scale prefixes: `k`, `M`, `G`, `m`, `c`.

| Category | Unit strings |
|---|---|
| Energy | `J`, `kJ`, `MJ`, `GJ`, `kWh`, `MWh`, `Btu`, `kBtu`, `therm` |
| Power | `W`, `kW`, `Btu/h`, `ton` |
| EUI | `kWh/m^2`, `kBtu/ft^2`, `GJ/m^2` |
| Power density | `W/m^2`, `W/ft^2`, `Btu/hr*ft^2` |
| R-value | `m^2*K/W`, `ft^2*hr*R/Btu` |
| U-value | `W/m^2*K`, `Btu/hr*ft^2*R` |
| Thermal conductivity | `W/m*K`, `Btu/hr*ft*R` |
| Specific heat | `J/kg*K`, `Btu/lb_m*R` |
| Flow rate | `m^3/s`, `cfm`, `L/s`, `gal/min` |
| Flow/area | `cfm/ft^2`, `m^3/s*m^2`, `L/s*m^2` |
| Temperature | `C`, `F`, `K`, `R` |
| Length/Area/Volume | `m`, `ft`, `in`, `m^2`, `ft^2`, `m^3`, `ft^3`, `gal`, `L` |
| Pressure | `Pa`, `kPa`, `psi`, `inHg` |
| Mass/Density | `kg`, `lb`, `lb_m`, `kg/m^3`, `lb/ft^3` |
| Illuminance | `lux`, `fc` |

Source: [OpenStudio SDK units](https://github.com/NREL/OpenStudio/tree/develop/src/utilities/units/)

## Languages

- **Ruby** — full support, `openstudio measure -u` syncs measure.xml
- **Python** — full support, but `openstudio measure -u` can't update measure.xml (SDK limitation). Arguments still work at runtime.

## ReportingMeasure Notes

- `measure_type: "ReportingMeasure"` — runs after simulation
- run() receives `(runner, user_arguments)` — no model param
- Boilerplate auto-generates model + SQL file loading
- Test with `test_measure(measure_dir, run_id=<completed_sim>)`
