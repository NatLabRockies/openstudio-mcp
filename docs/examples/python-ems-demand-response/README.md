# Python EMS demo: staged demand-limiting controller

Companion assets for **[Example 20](../20_python_ems_demand_response.md)**.

Grid-interactive demand-response study on the 10-zone baseline office
(ASHRAE System 7 VAV, Boston TMY3, Jun–Aug). A custom EnergyPlus Python Plugin
("DemandLimiter"), authored via `create_python_plugin` and revised twice via
`edit_python_plugin`, watches whole-building electric demand and ratchets every
zone's cooling setpoint up in stages when demand crosses a shed threshold.

## Files

| File | What it is |
|---|---|
| [`study.md`](study.md) | Full research writeup — testbed, controller, iteration story, results, caveats |
| [`dr_dashboard.html`](dr_dashboard.html) | Self-contained results dashboard (open in a browser; data embedded) |
| `dr_demo_driver.py` | Driver 1 — baseline characterization + v1 controller |
| `dr_demo_driver2.py` | Driver 2 — v2 controller (widened window); reuses driver1's baseline run |
| `dr_demo_driver3.py` | Driver 3 — v3 final controller (the headline numbers) |

The **controller itself** is the `PLUGIN_TEMPLATE` string inside each driver
(the `DemandLimiter` class). The rest of each driver is a reproducibility
harness: it drives the MCP server over stdio and calls the same MCP tools an AI
agent would (`create_baseline_osm`, `add_baseline_system`, `run_simulation`,
`create_python_plugin`, `query_timeseries`, …), frozen so the study reproduces
exactly.

## Reproduce

Build the image from `origin/develop`, then run the drivers inside it. Analysis
JSON lands in `runs/demo_dr_analysis/`; the dashboard is already self-contained.

```bash
docker build -f docker/Dockerfile -t openstudio-mcp:dev .   # from origin/develop
cd docs/examples/python-ems-demand-response
docker run --rm \
  -v "C:/projects/openstudio-mcp/runs:/runs" \
  -v "$(pwd):/scratch" \
  openstudio-mcp:dev bash -lc "python -u /scratch/dr_demo_driver.py"   # baseline + v1
```

`driver2`/`driver3` hardcode the baseline `run_id` printed by `driver1`
(`BASELINE_RUN = ...` near the top) — edit that value, then run each the same
way to reproduce v2 and the final v3.

## Results (v3, final)

Billing (30-min) peak **−7.2%** for the summer, threshold exceedances **−73%**,
energy **−3.9%** (setpoint DR sheds energy too, so no penalty). Full numbers and
the three-revision iteration story in [`study.md`](study.md).

## Gotcha

`query_timeseries` on this testbed returned sizing design-day rows blended with
run-period rows (Boston design days fall on 7/21). The drivers dedupe by keeping
the last row per timestamp. Fixed in the tool as of
[#87](https://github.com/NatLabRockies/openstudio-mcp/issues/87)
(`environment="run_period"` is now the default).
