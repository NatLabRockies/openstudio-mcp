## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "Show me the model" | view_model | — |
| "Visualize the building" | view_model | — |
| "Show me a 3D view highlighting geometry problems" | view_model | geometry_diagnostics=true |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "A simulation already completed. Show me the results" | view_model | extract_summary_metrics, view_simulation_data, generate_results_report, list_files |
| "What does the model contain?" | view_model | get_model_summary, list_spaces |
