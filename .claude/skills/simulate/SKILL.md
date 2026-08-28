---
name: simulate
description: Run EnergyPlus simulation and extract results in one step. Use when user says "simulate", "run simulation", or "run the model".
disable-model-invocation: true
---

# Simulate Current Model

Run a simulation on the currently loaded model and present results.

## Steps

1. Save the model to a unique path under `/runs/`:
   ```
   save_osm_model(osm_path="/runs/<descriptive_name>.osm")
   ```

2. Ask the user which weather file to use. They must provide an EPW file path in the docker-mounted input directory. List available weather files if needed:
   ```
   list_weather_files()
   ```

3. Run the simulation:
   ```
   run_simulation(osm_path="<saved_path>", epw_path="<user_epw_path>")
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
