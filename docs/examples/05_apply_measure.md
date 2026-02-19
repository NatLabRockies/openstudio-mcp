# Example 5: Apply an OpenStudio Measure

Apply a local OpenStudio measure to modify the in-memory model.

## Scenario

An engineer has a local measure directory (downloaded from BCL or custom-written) that sets the building name. They want to inspect the measure's arguments, then apply it with a custom value.

## Prompt

> List the arguments for the "set_building_name" measure, then apply it with the name "My New Office Building".

## Tool Call Sequence

```
1. list_measure_arguments(measure_dir="/inputs/measures/set_building_name")
   -> [{name: "building_name", type: "String", default: "Test Building"}]

2. apply_measure(measure_dir="/inputs/measures/set_building_name",
     arguments={"building_name": "My New Office Building"})

3. get_building_info()  # verify name changed
```

## How It Works

The `apply_measure` uses an OSW-based approach:

1. Saves the current in-memory model to a temporary OSM
2. Copies the measure into a run directory
3. Builds a minimal OSW with the measure step
4. Runs `openstudio run --measures_only -w workflow.osw`
5. Reloads the resulting model back into memory

This avoids Ruby script execution complexity and uses the well-tested OSW runner.

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `list_measure_arguments` | Inspect measure args before applying |
| `apply_measure` | Apply measure to in-memory model |

## Measure Directory Structure

A valid OpenStudio measure directory must contain:

```
my_measure/
  measure.rb      # Ruby script (required)
  measure.xml     # Metadata with arguments (required)
  tests/          # Optional test directory
```

## Notes

- Measures run via `openstudio run --measures_only` (no EnergyPlus)
- The model is modified in-place in memory after measure application
- Arguments are passed as string key-value pairs
- Only local measure directories are supported (no BCL download)

## Integration Test

See `tests/test_example_workflows.py::test_workflow_apply_measure`
