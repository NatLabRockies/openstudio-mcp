---
name: view
description: Generate 3D visualization of the current model. Use when user says "show me the model", "visualize", or "view".
disable-model-invocation: true
argument-hint: [format]
---

# View Model

Generate an interactive 3D HTML viewer of the current model geometry.

## Steps

1. Generate the visualization:
   ```
   view_model()
   ```

2. Report the output file path to the user so they can open it in a browser.

## Options

- `geometry_diagnostics: true` — highlights surface normal issues and unmatched surfaces
- After simulation, use `view_simulation_data` instead for data overlaid on geometry
