---
name: simulate
description: Run EnergyPlus simulation and extract results in one step. Use when user says "simulate", "run simulation", or "run the model".
disable-model-invocation: true
---

# Simulate Current Model

Run a simulation on the currently loaded model and present results.

## Steps

1. Save the model — the server picks a private writable path and returns it:
   ```
   save_osm_model(save_name="<descriptive_name>")   # response carries osm_path
   ```

2. Ask the user which weather file to use. Weather files are SERVER-side; list the available ones (remote clients can stage their own EPW with `request_upload`):
   ```
   list_weather_files()
   ```

3. Run the simulation with the path the save returned. If the response carries a `warnings`
   entry about edits that are not saved, the file on disk is behind the session model:
   save again and rerun.
   ```
   run_simulation(osm_path=<osm_path from save>, epw_path="<epw_path>")
   ```

4. Wait for completion. Call this repeatedly until `status` is terminal
   (`success`, `failed`, `cancelled`, `error`); the server holds each call open
   until the run finishes or the wait cap passes (`wait_exhausted: true` means
   call again):
   ```
   get_run_status(run_id=<id>, wait_seconds=50)
   ```
   Each status check costs a full LLM turn. If your client cannot hold a call
   that long, use `wait_seconds=0` and sleep `poll_interval_seconds` (from the
   response) between calls rather than polling back-to-back.

5. Extract key results:
   ```
   extract_summary_metrics(run_id=<id>)
   extract_end_use_breakdown(run_id=<id>)
   ```

6. Present a summary with:
   - Total site energy (GJ and kBtu)
   - EUI (MJ/m2 and kBtu/ft2)
   - Unmet heating/cooling hours
   - End-use breakdown by category (heating, cooling, lighting, equipment, fans, pumps)

## Many runs of one model (time segments)

Translating a large model to EnergyPlus input takes tens of seconds per run. For runs that
differ only in dates or warmup days, run the first one with `run_simulation`, then rerun its
translated IDF with new dates (same status and extract tools):
```
run_idf(idf_path="<run_dir>/run/in.idf", epw_path="<epw_path>",
        begin_month=4, begin_day=1, end_month=4, end_day=30)
```
`pin_run` the first run so its `Schedule:File` CSVs stay until the others finish.

## Error Handling

- If no model is loaded, tell the user to load one first
- If simulation fails, show `get_run_logs(run_id=<id>)` output
- Common failure: missing weather file or design days
