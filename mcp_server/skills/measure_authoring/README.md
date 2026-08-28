# measure_authoring — internal dev notes

Create, test, edit, and apply custom OpenStudio measures. Served agent
guidance lives in `.claude/skills/measure-authoring/SKILL.md` (via
`get_skill("measure-authoring")`; unit-conversion table is its
`unit-conversions.md` supporting file).

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

BCL/find_measure routing guidance: served skill ("Reuse Before Writing").

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

Migrated to the served supporting file `.claude/skills/measure-authoring/unit-conversions.md` — edit it there. `tests/test_unit_conversions.py` verifies every documented unit string.

## Languages

- **Ruby** — full support, `openstudio measure -u` syncs measure.xml
- **Python** — full support, but `openstudio measure -u` can't update measure.xml (SDK limitation). Arguments still work at runtime.

## ReportingMeasure Notes

- `measure_type: "ReportingMeasure"` — runs after simulation
- run() receives `(runner, user_arguments)` — no model param
- Boilerplate auto-generates model + SQL file loading
- Test with `test_measure(measure_dir, run_id=<completed_sim>)`
