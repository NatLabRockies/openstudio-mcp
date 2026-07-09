# Grid-Interactive Demand Limiting with Python EMS
## An openstudio-mcp research demo: authoring, tuning, and evaluating a supervisory controller entirely through MCP tools

**Date:** 2026-07-07 · **Image:** openstudio-mcp:dev @ origin/develop `9d76327` (v1.1.0)
**Interactive dashboard:** `dr_dashboard.html` (self-contained, this directory) · https://claude.ai/code/artifact/4139f7ac-85d0-44b7-9d65-fa53c264c12b
**Repro assets:** this directory (drivers + dashboard HTML) · data regenerated to `runs/demo_dr_analysis/*.json`
**Runs:** baseline `run_demo_dr_baseline_ce6de7f0a0c1` · final `run_demo_dr_shed_v3_8953d5dbc6ec`

---

## One-slide summary

A custom **EnergyPlus Python Plugin** ("DemandLimiter") authored via `create_python_plugin`
watches whole-building electric demand every 10 minutes and ratchets all 10 zones' cooling
setpoints up in stages (+1/+2/+3 K) whenever demand crosses a shed threshold. Two controller
revisions via `edit_python_plugin`, each driven by simulated evidence. Final result on a
10-zone VAV office in Boston (Jun–Aug):

| Metric | Baseline | Demand-limited (v3) | Change |
|---|---|---|---|
| Summer billing peak (30-min basis) | 335.2 kW | 311.1 kW | **−7.2%** |
| 10-min intervals above 276.9 kW threshold | 2,276 | 610 | **−73%** |
| Summer electricity (Jun–Aug) | 811.7 MWh | 779.8 MWh | **−3.9% (saved)** |
| Demand-charge value @ $15/kW·mo | — | — | **≈ $1,300 / summer** |

Demand response that *saves* energy: raising cooling setpoints during events reduces
consumption too, so there is no energy penalty for the peak reduction.

## Why researchers should care

- **No custom E+ builds, no IDF hacking, no measure boilerplate:** control logic is plain
  Python attached to the model; the MCP tool wires PythonPlugin:Instance/Variables/
  OutputVariable and validates the source against the plugin contract before it ever runs.
- **The controller iteration loop is minutes, not days:** author → simulate → query →
  revise (`edit_python_plugin`) → re-simulate. Each full 3-month simulation ran in ~10 s
  on this testbed.
- **Custom telemetry:** the plugin publishes its own state (`DR Shed Stage`) as a normal
  output variable, queryable alongside standard outputs via `query_timeseries`.
- The whole study — model creation, HVAC, weather, control authoring, simulation,
  extraction — is a reproducible tool-call script (an AI agent can run the entire loop).

## Testbed

| Item | Value |
|---|---|
| Building | 10-zone, 2-story office, 100 m × 50 m (~10,000 m²), core+perimeter zoning (`create_baseline_osm`) |
| HVAC | ASHRAE baseline System 7: VAV w/ reheat, chiller + boiler plant (`add_baseline_system(system_type=7)`) |
| Thermostats | 21.1 °C heating / 23.9 °C cooling |
| Weather | Boston-Logan TMY3 (`change_building_location`, sets EPW + design days) |
| Run period | Jun 1 – Aug 31, 10-minute timesteps |
| Outputs | Facility Total Electricity Demand Rate, Zone Mean Air Temperature, Zone Thermostat Cooling Setpoint Temperature, Site OAT (timestep); Electricity:Facility / Cooling / Fans meters (hourly) |

## Controller (final, v3)

**Sensor:** Facility Total Electricity Demand Rate (previous timestep — realistic metering lag).
**Actuators:** `Zone Temperature Control / Cooling Setpoint` per zone (discovered and confirmed with `list_ems_actuators`).
**Logic, each zone timestep:**

- Window: 08:00–19:00, **every day** (building runs 7-day schedules).
- If demand > threshold (276.9 kW = 82% of true baseline peak): ratchet stage up
  (never down in-window). 10-min dwell between moves; from idle, jump 2 stages when
  demand > 115% of threshold (catches the 08:30 startup spike).
- Stage offsets on the *scheduled* cooling setpoint: 0 / +1 / +2 / +3 K
  (23.9 → 24.9 / 25.9 / 26.9 °C). Base setpoint sampled from the schedule whenever
  unoverridden, so offsets never stack on the controller's own override.
- After the window: release one stage per 30 min (staggered recovery — no rebound spike).
- Publishes `dr_stage` as PythonPlugin:OutputVariable "DR Shed Stage".
- Guards: handles looked up lazily after `api_data_fully_ready`, `-1` handles raise
  a severe error and abort; actuation gated on `kind_of_sim == 3` so sizing design
  days are untouched (otherwise the raised setpoints would shrink the autosized plant
  and corrupt the comparison).

Full source: `dr_demo_driver3.py` (PLUGIN_TEMPLATE), or
`get_python_plugin("Demand Limiter")` on the saved model `runs/demo_dr_shed/model.osm`.

## Tool workflow (the entire study)

1. `create_baseline_osm` → `load_osm_model` → `list_thermal_zones`
2. `add_baseline_system(system_type=7, thermal_zone_names=[...10 zones])`
3. `change_building_location(Boston TMY3)` → `set_run_period(6/1–8/31)`
4. `add_output_variable` ×4 (timestep) + `add_output_meter` ×3 (hourly)
5. `save_osm_model` → `run_simulation` → `get_run_status` (baseline)
6. `query_timeseries` → true baseline peak 337.7 kW → threshold = 0.82 × peak
7. `list_ems_actuators(component_type="Zone Temperature Control")` — verify per-zone Cooling Setpoint actuator triples from the E+ .edd
8. `create_python_plugin(name="Demand Limiter", template="custom", class_name="DemandLimiter", global_variables=["dr_stage"], output_variable_name="DR Shed Stage")`
9. `save_osm_model` (plugin script travels in the model's companion `files/` dir) → `run_simulation`
10. `extract_simulation_errors` — verify `PythonPlugin: Class DemandLimiter imported`, zero severe
11. `edit_python_plugin` ×2 (revisions below) → rerun
12. `query_timeseries` (demand, stage, setpoints, zone temps, OAT, meters) + `extract_summary_metrics` + `extract_end_use_breakdown`

## The iteration story (the research-workflow payoff)

| Rev | Controller | What the simulation said |
|---|---|---|
| v1 | Weekdays 13:00–18:00, 3 stages, 30-min dwell | Sheds 37–52 kW in-window, but the building peaks at **08:30** (morning pulldown after night setback) — seasonal peak untouched. Also surfaced the design-day/SQL analysis trap (below). |
| v2 | Weekdays 08:00–19:00, 4 stages, 20-min dwell | Weekday peaks clipped to ~290 kW; seasonal peak **moved to Saturday** (329 kW, 6/26) because the model runs 7-day schedules; 20-min staging let the 08:30 spike through at 320 kW. |
| v3 | Every day 08:00–19:00, 10-min dwell, 2-stage jump-start >115% of threshold | Billing peak −7.2%; exceedances −73%; energy −3.9%. Residual instantaneous spikes are single-timestep chiller-staging transients. |

## Results detail

**Monthly billing peak (30-min rolling basis, the demand-charge metric):**

| Month | Baseline kW | v3 kW | Reduction |
|---|---|---|---|
| Jun | 335.2 | 306.0 | −8.7% |
| Jul | 333.8 | 300.2 | −10.1% |
| Aug | 335.1 | 311.1 | −7.2% |

**Monthly facility electricity (MWh):** Jun 258.5→251.6, Jul 272.6→259.1, Aug 280.5→269.0.

**Peak weekday (Jun 27) anatomy:** baseline holds ~324–327 kW from 08:30 to 17:30;
controller jump-starts 2 stages on the 08:30 spike (337.7 → 320.6 kW at first trip, one
timestep of irreducible metering lag), reaches stage 3 by 09:00, holds ~283–293 kW all
day, zone temps float 23.9 → 26.9 °C, and the staggered release (19:00–20:30) returns to
schedule with ≤ +5 kW rebound.

**Comfort:** zones spend event hours up to 26.9 °C. Reported unmet cooling hours
*improve* (152.5 → 24.7 h) — an artifact, not a comfort gain: EnergyPlus scores unmet
hours against the **actuated** setpoint. The honest comfort story is the zone-temperature
traces.

## Findings a researcher would chase next

1. **Shed capacity is finite:** stage 3 floor ≈ 285–295 kW. Deeper cuts need pre-cooling,
   chiller demand limiting, or lighting/plug DR — all expressible as more plugin logic.
2. **Demand limiting induces plant cycling:** brief chiller-staging transients up to
   +19 kW *above baseline* for a single timestep. They wash out on a 30-min billing basis;
   plant-level control (CHW reset, compressor limiting) would remove them.
3. **Feedback-only control cannot preempt step changes:** the metered interval that trips
   the controller is itself the residual peak. Forecast or schedule-aware feed-forward is
   the fix.
4. **The baseline plant is capacity-limited:** baseline zones already float 0.5–1.5 K above
   setpoint on peak afternoons — why the 351 kW sizing-day plateau never appears in the
   run period, and a reminder that setpoint-based DR sheds nothing from saturated equipment.

## Method caveats / gotchas (worth keeping)

- **Design-day rows in `query_timeseries`:** sizing design days share calendar dates with
  the run period (Boston: 7/21, 1/21) and are returned blended with run-period rows.
  Workaround: keep the last row per timestamp (run period simulates last). Tool fix filed
  as [#87](https://github.com/NatLabRockies/openstudio-mcp/issues/87).
- **`kind_of_sim` guard is mandatory** for any plugin that actuates thermostats/setpoints —
  otherwise sizing runs see the overrides and the plant autosizes smaller.
- "Billing peak" = max 30-minute rolling average of 10-min instantaneous demand.
- Custom plugins report **one** output variable per `create_python_plugin` call (the first
  global); design controllers so one state variable + standard E+ outputs tell the story.
- TMY3 single-year weather; demand-charge $ uses a $15/kW·mo placeholder tariff.

## Figure inventory (for slides)

All figures live in the self-contained dashboard (`dr_dashboard.html`,
same as the artifact link). Underlying series JSON regenerated to `runs/demo_dr_analysis/`:

| Figure | Data files |
|---|---|
| Peak-day demand, baseline vs v3, threshold + window band | `baseline_demand.json`, `shed3_demand.json` (Jun 27 slice) |
| Controller anatomy: stage step + setpoint/zone-temp traces | `shed3_peakday.json`, `baseline_peakday_v2.json` |
| Weekend clip (Sat Jun 26, the v2 miss) | `baseline_weekend.json`, `shed3_weekend.json` |
| Monthly billing peaks + monthly energy bars | `monthly_peaks_w.json`, `monthly_energy_mwh.json`, `shed3_monthly_*` |
| Stat tiles (peak, exceedances, energy, $) | `manifest_v3.json`, metrics JSONs |

## Reproduce

```bash
docker build -f docker/Dockerfile -t openstudio-mcp:dev .   # from origin/develop
cd docs/examples/python-ems-demand-response
docker run --rm -v "C:/projects/openstudio-mcp/runs:/runs" -v "$(pwd):/scratch" \
  openstudio-mcp:dev bash -lc "python -u /scratch/dr_demo_driver.py"   # baseline + v1
# driver2/driver3 hardcode the baseline run id printed by driver1 — edit, then run the same way
```
