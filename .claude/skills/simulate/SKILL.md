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

3. Run the simulation with the path the save returned:
   ```
   run_simulation(osm_path=<osm_path from save>, epw_path="<epw_path>")
   ```

4. Poll until complete — first status check ~60 seconds after submitting, then
   no more than once per minute (every 2-3 minutes for long simulations):
   ```
   get_run_status(run_id=<id>)
   ```
   Each status check costs a full LLM turn. If your client can wait (e.g. a
   shell sleep), wait before checking rather than polling back-to-back.

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

## Error Handling

- If no model is loaded, tell the user to load one first
- If simulation fails, show `get_run_logs(run_id=<id>)` output
- Common failure: missing weather file or design days
