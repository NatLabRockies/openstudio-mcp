---
name: parallel-annual
description: Run one annual EnergyPlus simulation as parallel time segments and stitch the results into monthly and annual totals. Use when an annual run is too slow, or the user asks for a parallel, segmented or faster annual simulation.
---

# Parallel Annual Simulation

Split the year into segments, run them at the same time, and add up the kept days. On a 44-zone
model (Boston weather), 12 segments finished in a third of the annual wall-clock time and stitched
to +0.02% of the annual run's electricity. Each segment pays a fixed start-up cost, so the gain
grows with the model's annual run time.

The recipe has three parts:

- **Hard-size once.** Every segment must use the same equipment sizes, so one sizing run fixes them
  in the model and sizing is turned off.
- **Lead-in.** Segment 1 gets 7 warmup days. Every later segment gets 1 warmup day plus real-weather
  lead-in days before its kept days: 7 days for segments starting October to May, 2 days for June to
  September. Lead-in days are simulated and then dropped.
- **One wave.** One segment per free run slot, all submitted together.

All five measures live in `/opt/common-measures` (`list_common_measures(category="parallel")`).
Below, `<model>` is the loaded model's name and `<epw>` the weather file path.

## Steps

1. **Choose the segment count.** `get_server_status()` reports `max_concurrency`, the number of runs
   the server executes at once. Use that many segments, minus runs you already have queued or
   running. With fewer than 2 free slots the segments run one after another and only add overhead:
   run the annual simulation instead. Each run carries a fixed cost (about a minute on a large
   model) for translating the model, so past about 24 segments the speedup stops growing.
   Done when: you have a segment count N.

2. **Sizing run.** Run the design days only:
   ```
   set_simulation_control(run_for_weather_file=False, do_zone_sizing=True, do_system_sizing=True, do_plant_sizing=True)
   save_osm_model(save_name="<model>_sizing")
   run_simulation(osm_path=<osm_path from save>, epw_path="<epw>")
   get_run_status(run_id=<sizing run_id>, wait_seconds=50)   # repeat until terminal
   set_simulation_control(run_for_weather_file=True)
   ```
   Done when: the sizing run's status is `success` and the session model runs the weather file again.

3. **Hard-size.** The measure runs sandboxed and reads only its own run folder, so the sizing SQL
   goes into the model's companion `files/` folder first, and the measure takes its bare name.
   For a model saved as `/runs/u/x_hardsize.osm` that folder is `/runs/u/x_hardsize/files`.
   `get_run_artifacts(run_id=<sizing run_id>)` lists the sizing run's `run/eplusout.sql` path.
   ```
   save_osm_model(save_name="<model>_hardsize")
   copy_file(file_path="<sizing run>/run/eplusout.sql", destination="<osm_path minus .osm>/files")
   apply_measure(measure_dir="/opt/common-measures/hard_size_from_sizing_sql", arguments={"sql_path": "eplusout.sql"})
   save_osm_model(save_name="<model>_hardsized")   # its osm_path is the segments' seed
   ```
   The measure turns zone, system and plant sizing off only when no field is left `Autosize`. Read
   its `runner_messages`: a warning lists fields OpenStudio could not hard-size, and sizing then stays
   on. That is safe, since every segment sizes from the same design days, but each segment then pays
   for the sizing calculation again.
   Done when: `<model>_hardsized` is saved and you know whether sizing is off.

4. **Write the segment OSWs.**
   ```
   apply_measure(measure_dir="/opt/common-measures/write_segment_osws", arguments={"seed_osm_path": <osm_path of <model>_hardsized>, "weather_file": "<epw>", "number_of_segments": N})
   ```
   The final condition names the folder; the OSWs are `<folder>/segment_01/segment_01.osw` through
   `segment_NN`. Each one sets its run period (lead-in plus kept days) and warmup days, and adds
   `segment_results_summary`, which writes the kept days to `run/segment_results.json`. Change
   `long_lead_in_days`, `short_lead_in_days` or `short_lead_in_months` here when a check in step 7
   fails.
   Done when: N OSWs exist (`list_files(directory=<folder>)`).

5. **Run all segments in one wave.** Submit every OSW before polling any of them:
   ```
   run_osw(osw_path="<folder>/segment_01/segment_01.osw", name="<model>_seg01")
   ...
   get_run_status(run_id=<each run_id>, wait_seconds=50)   # repeat until all are terminal
   ```
   Segments after the first log `CheckWarmupConvergence` severe errors: one warmup day never
   converges, and the lead-in days absorb that. Only a `failed` status is a failure.
   Done when: every segment's status is `success`.

6. **Stitch.**
   ```
   stitch_segment_results(run_ids=[<every segment run_id>])
   ```
   Returns monthly and annual end uses (kWh) per fuel, annual electricity and monthly peak electric
   demand (W). It refuses segments that overlap or leave days out.
   Done when: the stitch returns `ok: true` with `kept_days` equal to the days in the run period.

7. **Check against an annual reference** the first time you use the recipe on a model type, or when
   the user needs the error stated. Write and run a one-segment reference, then stitch with it:
   ```
   apply_measure(measure_dir="/opt/common-measures/write_segment_osws", arguments={"seed_osm_path": <same seed>, "weather_file": "<epw>", "number_of_segments": 1})
   run_osw(osw_path="<new folder>/segment_01/segment_01.osw", name="<model>_annual_ref")
   stitch_segment_results(run_ids=[<every segment run_id>], reference_run_id=<reference run_id>)
   ```
   Read `reference_check`:
   - `annual_electricity_error_pct` within ±0.1%.
   - `monthly_electricity_bias_pct` within ±0.5% each month. A biased month starting October to May
     needs a longer lead-in: raise `long_lead_in_days`. A biased June to September month needs that
     month taken out of `short_lead_in_months`. (A 2-day lead-in left May heating 1.5% low on one
     model.)
   - `first_kept_day_error_pct` names the segments whose first day is off; large errors follow cold
     spells and point at the same lead-in fix.
   `monthly_cv_rmse_pct` and `daily_cv_rmse_pct` summarize the spread.
   Done when: every check passes, or you have reported which month fails and by how much.

## Notes

- Large models: `apply_measure` runs inside the tool call, and some clients cut a call off after
  about 60 seconds. Steps 3 and 4 can hit that on a model with thousands of objects. Background
  `apply_measure` (issue #245) will return a run id to poll instead.
- Each segment translates the whole model to EnergyPlus input again. Running pre-translated IDFs
  (issue #246) would remove most of the fixed per-segment cost.
- A queue-aware `get_queue_status` and batch submission `run_batch` are planned (issue #218); until
  then, step 1 uses `max_concurrency` and step 5 submits runs one by one.
- Segments are equal day counts, so 12 segments are not calendar months; the stitch sums by
  calendar month regardless.
