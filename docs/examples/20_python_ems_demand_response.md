# Example 20: Grid-Interactive Demand Response with Python EMS

Author, tune, and evaluate a custom supervisory controller entirely through MCP tools — no custom EnergyPlus build, no hand-edited IDF, no measure boilerplate.

## Scenario

Commercial buildings pay **demand charges** based on their single highest 15-to-30-minute power spike each month, not just total energy consumed. In a mid-size office, air conditioning usually drives that spike. **Demand response (DR)** means shaving those spikes on purpose.

A researcher wants to test a simple idea on a 10-zone office: watch the whole-building electricity draw, and when it crosses a threshold, let the zones drift a couple degrees warmer so the chillers back off and the peak is clipped. The whole loop — build the model, author the controller, simulate, read the results, revise — is done through openstudio-mcp tools, so an AI agent can run it end to end.

## What this demonstrates (plain language)

- **The controller is plain Python attached to the model.** A custom EnergyPlus Python Plugin ("DemandLimiter"), authored via `create_python_plugin`, watches whole-building electric demand every 10 minutes and ratchets all 10 zones' cooling setpoints up in stages (+1 / +2 / +3 K) whenever demand crosses a shed threshold. The MCP tool wires the `PythonPlugin:Instance`/`Variables`/`OutputVariable` objects and validates the source against the plugin contract before it ever runs.
- **The iteration loop is minutes, not days.** Author → simulate → query → revise (`edit_python_plugin`) → re-simulate. Each full 3-month simulation ran in ~10 s on this testbed. It took three controller revisions, each driven by what the previous simulation revealed (see the iteration story below).
- **Custom telemetry rides along.** The plugin publishes its own state (`DR Shed Stage`) as a normal output variable, queryable next to standard outputs via `query_timeseries`.
- **DR that *saves* energy.** Raising cooling setpoints during events reduces consumption too, so there is no energy penalty for the peak reduction.

## Testbed

| Item | Value |
|---|---|
| Building | 10-zone, 2-story office, 100 m × 50 m (~10,000 m²), core+perimeter (`create_baseline_osm`) |
| HVAC | ASHRAE baseline System 7: VAV w/ reheat, chiller + boiler plant (`add_baseline_system(system_type=7)`) |
| Thermostats | 21.1 °C heating / 23.9 °C cooling |
| Weather | Boston-Logan TMY3 (`change_building_location`) |
| Run period | Jun 1 – Aug 31, 10-minute timesteps |

## Prompt

> I have a 10-zone baseline office on ASHRAE System 7 in Boston. Simulate the summer (Jun–Aug) and find its peak electricity demand. Then write me a custom controller that shaves that peak: whenever whole-building demand crosses about 82% of the baseline peak, nudge every zone's cooling setpoint up in stages so the chillers back off. Re-simulate, check whether the seasonal billing peak actually dropped, and revise the controller until it does. Tell me the peak reduction, how much less time we spend above the threshold, and any energy or comfort tradeoff.

## Tool Call Sequence

### Phase A — baseline testbed

```
1. create_baseline_osm(name="demo_dr")   → load_osm_model → list_thermal_zones
2. add_baseline_system(system_type=7, thermal_zone_names=[...10 zones])
3. change_building_location(Boston TMY3)  → set_run_period(6/1–8/31)
4. add_output_variable ×4 (Timestep): Facility Total Electricity Demand Rate,
   Zone Mean Air Temperature, Zone Thermostat Cooling Setpoint Temperature, Site OAT
5. add_output_meter ×3 (Hourly): Electricity:Facility, Cooling:Electricity, Fans:Electricity
6. save_osm_model → run_simulation → get_run_status (poll to success)
7. query_timeseries(Facility Total Electricity Demand Rate) → true baseline peak
   337.7 kW → threshold = 0.82 × peak = 276.9 kW
```

### Phase B — author, run, and revise the controller

```
8.  list_ems_actuators(component_type="Zone Temperature Control", control_type="Cooling")
    — confirm a per-zone Cooling Setpoint actuator exists for every zone
9.  create_python_plugin(name="Demand Limiter", template="custom",
      class_name="DemandLimiter", code=<controller>,
      global_variables=["dr_stage"], output_variable_name="DR Shed Stage")
10. save_osm_model (plugin script travels in the model's companion files/ dir)
    → run_simulation → get_run_status
11. extract_simulation_errors — verify "PythonPlugin: Class DemandLimiter imported", zero severe
12. query_timeseries (demand, DR Shed Stage, setpoints, zone temps, OAT)
    + extract_summary_metrics + extract_end_use_breakdown
13. edit_python_plugin ×2 (revisions v2, v3 — see iteration story) → rerun each
```

## Expected Results (v3, final)

| Metric | Baseline | Demand-limited (v3) | Change |
|---|---|---|---|
| Summer billing peak (30-min basis) | 335.2 kW | 311.1 kW | **−7.2%** |
| 10-min intervals above 276.9 kW threshold | 2,276 | 610 | **−73%** |
| Summer electricity (Jun–Aug) | 811.7 MWh | 779.8 MWh | **−3.9% (saved)** |
| Demand-charge value @ $15/kW·mo | — | — | **≈ $1,300 / summer** |

On the peak weekday, zone temperatures float 23.9 → 26.9 °C during the event and the staggered release returns to schedule with ≤ +5 kW rebound.

## The iteration story (the research payoff)

Each revision was driven by simulated evidence, not guesswork:

| Rev | Controller | What the simulation said |
|---|---|---|
| v1 | Weekdays 13:00–18:00, 3 stages, 30-min dwell | Sheds 37–52 kW in-window, but the building peaks at **08:30** (morning pulldown after night setback) — the seasonal peak was untouched. |
| v2 | Weekdays 08:00–19:00, 4 stages, 20-min dwell | Weekday peaks clipped to ~290 kW, but the seasonal peak **moved to Saturday** (329 kW) because the model runs 7-day schedules; the 20-min dwell also let the 08:30 spike through. |
| v3 | **Every day** 08:00–19:00, 10-min dwell, 2-stage jump-start when demand > 115% of threshold | Billing peak −7.2%, exceedances −73%, energy −3.9%. Residual spikes are single-timestep chiller-staging transients. |

## Common Pitfalls

- **The `kind_of_sim` guard is mandatory** for any plugin that actuates thermostats/setpoints. Actuation must be gated to the weather run period (`kind_of_sim == 3`) — otherwise the raised setpoints reach the sizing design days, the plant autosizes smaller, and the baseline-vs-controlled comparison is corrupted.
- **Design-day rows in `query_timeseries`:** sizing design days share calendar dates with the run period (Boston: 7/21) and, before the fix, came back blended with run-period rows. Fixed in [#88](https://github.com/NatLabRockies/openstudio-mcp/pull/88) (closes [#87](https://github.com/NatLabRockies/openstudio-mcp/issues/87)) — `environment="run_period"` is now the default. (This demo is where that bug was found.)
- **One output variable per plugin:** `create_python_plugin` reports one output variable (the first global). Design controllers so a single state variable plus standard E+ outputs tell the story.
- **Feedback-only control can't preempt step changes:** the metered interval that trips the controller is itself the residual peak. Forecast or schedule-aware feed-forward is the fix.
- **Shed capacity is finite:** the stage-3 floor is ~285–295 kW. Deeper cuts need pre-cooling, chiller demand limiting, or lighting/plug DR — all expressible as more plugin logic.

## Reproduce / Assets

Everything needed to rebuild this study lives in **[`python-ems-demand-response/`](python-ems-demand-response/)**:

- **[`study.md`](python-ems-demand-response/study.md)** — full research writeup (results detail, comfort analysis, method caveats, figure inventory).
- **[`dr_dashboard.html`](python-ems-demand-response/dr_dashboard.html)** — self-contained results dashboard (open in a browser).
- `dr_demo_driver.py` / `dr_demo_driver2.py` / `dr_demo_driver3.py` — reproducibility drivers (baseline+v1, v2, v3). Each embeds its controller as the `DemandLimiter` `PLUGIN_TEMPLATE`; the rest is the frozen MCP tool-call sequence above.

See [`python-ems-demand-response/README.md`](python-ems-demand-response/README.md) for the `docker run` reproduce command.

## Related

- Skill: `python-ems` (`get_skill("python-ems")`) — when to reach for a Python Plugin vs a packaged tool.
- Example 2: [Custom Measure: Chilled Beams](02_custom_measure_hvac.md) — the measure-authoring path (vs. runtime EMS control here).
