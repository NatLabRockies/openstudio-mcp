# Example 18: Model Visualization (`/view`)

Generate an interactive 3D view of the current model.

## Scenario

An engineer wants to visually inspect their building geometry — check zone layout, surface orientations, and window placement. The `/view` skill generates an HTML visualization using the OpenStudio common measures `ViewModel` measure.

## Prompt

> /view

## Tool Call Sequence

```
1. view_model()
2. Reports run_dir path — open the HTML file in a browser
```

## Key Tools Used

| Tool | Purpose |
|------|---------|
| `view_model` | Runs ViewModel measure, generates 3D HTML output |

## Notes

- Requires a model loaded in memory (`load_osm_model` must have been called)
- Output is an HTML file with Three.js-based 3D viewer
- The `run_dir` in the response contains the generated visualization files
- Works with any model — baseline, custom geometry, or loaded from file

## Integration Test

See `tests/test_skill_view.py::test_skill_view_workflow`
