## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Show me the model" | view_model | — |
| "Visualize the building" | view_model | — |
| "3D view" | view_model | format |

## Should NOT trigger
| Query | Why |
|---|---|
| "Show me the results" | Results — use energy-report skill |
| "What does the model contain?" | Query — use get_model_summary |
