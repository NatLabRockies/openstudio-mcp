## Should trigger
| Query | Expected tools | Critical params |
|---|---|---|
| "The annual run takes 40 minutes. Split it into parallel segments to finish faster" | get_server_status, set_simulation_control, apply_measure | — |
| "The segment runs finished. Add them up into monthly and annual totals" | stitch_segment_results | run_ids present |
| "Check the stitched segments against the annual reference run" | stitch_segment_results | reference_run_id present |

## Should NOT trigger
| Query | Forbidden tools | Expected alternatives |
|---|---|---|
| "Run an annual simulation with the Boston weather file" | stitch_segment_results | run_simulation |
| "Compare the baseline run with the retrofit run" | stitch_segment_results | compare_runs |
| "Simulate only January" | stitch_segment_results | set_run_period |
