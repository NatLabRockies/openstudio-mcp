# measure_authoring

Create, test, edit, and apply custom OpenStudio measures.

## Overview

Measures are the primary extension mechanism for OpenStudio models. They modify a model programmatically (ModelMeasure) or extract post-simulation results (ReportingMeasure). This skill handles the full lifecycle: scaffold, inject code, test, apply.

## Workflow

```
create_measure → test_measure → apply_measure
```

Use `edit_measure` to iterate on existing measures. Use `list_custom_measures` to find previously created measures.

Custom measures are **private per user**: in multi-user (HTTP) mode each caller's
authored and downloaded measures live under their own `/measures/<user>/{custom,bcl}`
and are never visible to or writable by other users. Don't tell users measures are
shared.

For requests to use an existing measure by name, BCL page title, or intent,
first call `find_measure`. It searches the caller's own custom measures,
bundled common measures, bundled ComStock measures, and the caller's BCL cache
before searching BCL. If BCL returns a strong match, `find_measure` downloads it
into the caller's `bcl` dir and returns a top-level `measure_dir` / `selected_measure_dir`.
Pass that value directly to `list_measure_arguments` or `apply_measure`. Use
`search_bcl_measures` only when you need to inspect BCL candidates without
downloading.

## Before Writing HVAC Measures

LLM training data may reference deprecated or nonexistent OpenStudio methods. Before writing SDK calls:

1. **`search_api("CoilCoolingFourPipeBeam")`** — verify methods exist on the class. Returns real setters/getters grouped by category.
2. **`search_wiring_patterns("four pipe beam")`** — get working Ruby code showing how to connect components to loops, terminals to air loops, etc.

This prevents hallucinated method names (e.g. `setRatedCoolingCoefficientOfPerformance` does not exist on `CoilCoolingFourPipeBeam`) and incorrect wiring order.

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
Scaffold a new measure with user-provided run() body and arguments. Output: your per-user custom measures dir.

### test_measure
Run tests against a real model (not empty). Auto-detects language. For ReportingMeasures, provide `run_id` of a completed simulation.

### edit_measure
Replace run() body, arguments, or description on an existing measure. Use to add arguments to a measure that hard-codes values.

### list_custom_measures
List all measures in your per-user custom measures dir.

### list_local_measures
Search mounted, downloaded, custom, common measures, and ComStock measures. Use directly only when you need the full local inventory; otherwise prefer `find_measure`.

### find_measure
Find an existing measure by name, BCL page title, or intent. This is the default
tool for existing-measure requests. It searches locally first, then BCL, and
downloads a strong BCL match into your per-user BCL cache. On success, use the top-level
`measure_dir` or `next.apply.arguments.measure_dir` for the next tool call.

Example query: `Replace Chiller with Air Source Heat Pumps Measure Details`.

### search_bcl_measures
Search BCL and rank candidates without downloading. Use this when you need to
show or inspect BCL candidates before choosing one.

### download_measure_from_bcl
Download a known measure archive URL into your per-user BCL cache. Prefer `find_measure`
when starting from a measure name or intent. On success, use the top-level
`measure_dir` or `next.apply.arguments.measure_dir`.

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
