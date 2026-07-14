# Plan: Demand-limiting EMS support + peak-analysis ergonomics

Status: **proposed** · Author seed: peak-shaving study on `SystemD_baseline.osm` (Jul 2026)
Owner: _unassigned_ · Pick this up in a fresh session.

## Why this exists

A user asked for a demand-responsive controller: raise every zone's cooling setpoint in
stages when whole-building demand nears the seasonal peak, then confirm the billing peak
dropped. It worked (−14.1% peak, −59% hours-above-threshold, −0.75% energy, +2 °C max
setback for 144 h), but getting there hit four avoidable rabbit holes. This plan turns
those lessons into repo changes so the next demand-response task is quick and correct.

**Validated result to regression-anchor against** (Baltimore TMY3, CZ 4A, Jun–Aug,
EnergyPlus 25.2, DOAS + 4-pipe FCU, 44 zones):

| Metric | Baseline | Controlled |
|---|---|---|
| Hourly billing peak | 40.85 kW (Jul 20 14:00) | 35.11 kW (Aug 14 15:00) |
| Hours > 33.5 kW | 148 | 61 |
| Season electricity | 30.66 MWh | 30.42 MWh |
| Unmet cooling hours | 0.33 | 0.33 |

Working artifacts from the study live in `/runs/` (container): `SystemD_summer_baseline.osm`,
`SystemD_controlled_v3.osm`. Reference plugin source is in Appendix A below.

## Root causes we're fixing

1. **Wrong demand sensor.** Sensing whole-building demand via the `Electricity:Facility`
   meter inside the plugin fails: `get_meter_value` returns **0** in
   `on_end_of_zone_timestep_before_zone_reporting` and only a **partial** value at
   begin-timestep (~16 kW where the hourly meter reads ~41 kW); `get_meter_handle` resolves
   inconsistently. The correct sensor is the **`Facility Total Electricity Demand Rate`**
   output variable, key **`Whole Building`** (instantaneous W, reconciles with the billing
   meter, holds prev-step value at begin-timestep).
2. **Weather not embedded.** A user OSM referenced the EPW by name but didn't embed a path →
   `run_simulation` and `list_ems_actuators` failed instantly. Fix = `change_building_location`.
3. **Variable discovery.** `list_output_variables` returns only *requested* variables;
   `Facility Total Electricity Demand Rate` lives mid-file in `eplusout.rdd` and was missed.
4. **No reduce on `query_timeseries`.** Every peak / hours-above computation dumped ~150 KB
   and required external reduction.

---

## Work item 1 — SKILL.md documentation (S, no tests)

**Goal:** Encode the demand-sensing recipe + gotchas so the model reaches for the right
sensor immediately.

**File:** `mcp_server/skills/python_ems/SKILL.md`

**Edits:**
- New worked example **"Demand-responsive setpoint reset (whole-building demand sensor)"**:
  request `Facility Total Electricity Demand Rate` (key `Whole Building`) via
  `add_output_variable`; read it at `on_begin_timestep_before_predictor` (prev-step W);
  stage a per-zone `Zone Temperature Control` / `Cooling Setpoint` actuator = base + offset,
  reading base live from the shared setpoint schedule via a `Schedule Value` sensor so the
  day/night profile is preserved and setpoints only rise.
- Add to **"Rules of the plugin runtime"**:
  - Do NOT read the `Electricity:Facility` meter for demand in a plugin (see root cause 1).
  - **Handle `0` is valid** — check `< 0`, never `<= 0`.
  - `issue_severe` should print the actual handle integers to pinpoint which lookup failed.
  - Debugging "the plugin does nothing": publish the sensed value through a
    `PythonPlugin:OutputVariable` global and inspect with `query_timeseries`.
  - On a user-supplied OSM, run `change_building_location` before simulating or
    `list_ems_actuators` (weather must be embedded); `/inputs` is read-only, save to `/runs`.

**Acceptance:** SKILL.md renders; example is copy-pasteable; no tool/code changes.

---

## Work item 2 — `demand_limit` template in `create_python_plugin` (M, needs tests)

**Goal:** Make a staged demand-limiting controller a one-call template instead of custom code.

**Files:**
- `mcp_server/skills/python_ems/templates.py` — add the generator (see Appendix A for
  validated logic to adapt).
- `mcp_server/skills/python_ems/operations.py` / `tools.py` — wire template name + args,
  auto-add the required `Output:Variable` requests (demand rate + base schedule value),
  validate source through the existing contract check.
- `mcp_server/skills/python_ems/SKILL.md` — document the template.
- `tests/test_*` — integration test (mock nothing; real sim); assert the plugin loads,
  the offset output engages during a synthetic high-demand period, and the season peak on
  a small fixture drops vs a no-plugin run.
- `.github/workflows/ci.yml` — append test file to the lightest shard's `FILES=`.
- `tests/test_skill_registration.py` — no new *tool* (still `create_python_plugin`), so
  `EXPECTED_TOOLS` likely unchanged; confirm.

**Template args (proposed):**
| arg | meaning |
|---|---|
| `threshold_w` **or** `threshold_fraction` + `baseline_peak_w` | engage level (W) |
| `setpoint_kind` | `"cooling"` (raise) or `"heating"` (lower) |
| `zone_names` | default all zones with that thermostat; skip missing actuators |
| `base_schedule_name` | shared setpoint schedule to read base from |
| `step_c` (0.5), `max_offset_c` (2.0), `release_fraction` (0.95), `clamp_c` | staging |
| `output_variable_name` | publishes applied offset (default derived) |

**Design notes (carry the hard-won correctness):**
- Sensor = `Facility Total Electricity Demand Rate` / `Whole Building`, read at begin-timestep.
- Base setpoint via `Schedule Value` sensor on `base_schedule_name` (uncontaminated — the
  actuator overrides the thermostat, not the schedule); offset added on top; only ever moves
  in the shed direction; reset actuator when offset == 0 so the schedule fully resumes.
- Lazy handle resolution after `api_data_fully_ready`; `< 0` check; `issue_severe` with values.
- Cooling raises setpoint / heating lowers it; clamp to `clamp_c`.

**Acceptance:** template produces a plugin that (a) loads with no severe errors, (b) shows a
nonzero offset only above threshold, (c) reduces the fixture's hourly peak, (d) leaves unmet
hours ~unchanged.

---

## Work item 3 — reduce/stat option on `query_timeseries` (M, needs test)

**Goal:** Return scalars (peak, mean, hours-above) instead of thousands of rows; this is the
CLAUDE.md-sanctioned extractor, so peak/threshold analysis shouldn't require external reduction.

**File:** `mcp_server/skills/results/tools.py` (+ its operations module).

**Design:** add optional `reduce` arg, e.g. `reduce={"stat":"peak"|"min"|"mean"|"sum",
"hours_above": <value>, "hours_below": <value>}`. When present, return
`{"ok":True, "stat":..., "value":..., "peak_time":{m,d,h}, "hours_above":..., "n":...,
"units":...}` and **omit the raw `data` array**. Keep W-vs-J consistent (document that meters
are J/interval; divide by interval seconds for demand). Follows rule 13 (`list|str`) if any
list args; ops return `{"ok":...}`.

**Acceptance:** integration test asserts `reduce={"stat":"peak"}` on `Electricity:Facility`
matches the max computed from the full series, and `hours_above` matches a hand count on a
small fixture.

---

## Work item 4 — `include_available` on `list_output_variables` (S–M, needs test)

**Goal:** Surface *all* available output variables (parse `eplusout.rdd`/`.mdd`), not only
requested ones, so variable-name discovery doesn't require reading the raw .rdd.

**File:** `mcp_server/skills/results/tools.py` (+ ops). Add `include_available: bool=False`;
when True, parse `.rdd` + `.mdd` from the run dir and return names grouped by
variable/meter with a `requested` flag. Cap output; support a `filter` substring
(e.g. "Demand") to keep payloads small.

**Acceptance:** test asserts `filter="Facility Total Electricity Demand Rate"` appears with
`include_available=True` even when it was never requested.

---

## Suggested order & sizing

1. **Item 1** (docs) — do first, immediate value, zero risk.
2. **Item 3** (query_timeseries reduce) — unblocks clean analysis everywhere.
3. **Item 2** (demand_limit template) — biggest ergonomic win; depends on nothing but benefits from 3.
4. **Item 4** (variable discovery) — nice-to-have.

## CLAUDE.md rules to honor for items 2–4

- Every new/changed tool needs an integration test; add it to the lightest `ci.yml` shard.
- Integration tests mock nothing; assert exact values, not existence; add `# Regression:` /
  `# Validates:` comments; never weaken/delete failing tests.
- Ops return `{"ok":True/False,...}`; never raise through MCP. No `getattr`/string dispatch.
- `list[str] | str` + `parse_str_list()` for any list args from MCP clients.
- Keep files ≤ ~250–400 lines; split by responsibility if `templates.py` grows.
- Tool roster single source of truth = `EXPECTED_TOOLS` in `tests/test_skill_registration.py`.
- Docs say "150+ tools", not an exact count.

## Open questions

- Should the `demand_limit` template also expose a **pre-emptive ramp** (start shedding N
  timesteps before a predicted crossing) to push the peak *under* the target? The reactive
  +2 °C version stalls ~1.6 kW above the 82% line on the worst afternoon.
- Multi-schedule models: this study had one shared cooling schedule. Generalize base-setpoint
  sensing when zones use several schedules (per-zone `Zone Thermostat Cooling Setpoint
  Temperature` is contaminated by the actuator — need a clean per-zone base source).
- Demand signal for on-site PV / net metering: `Facility Net Purchased Electricity Rate` vs
  `Facility Total Electricity Demand Rate` — expose choice in the template.

---

## Appendix A — validated reference plugin (v3, the one that worked)

Sensor = `Facility Total Electricity Demand Rate` (`Whole Building`), read at begin-timestep.
Requires `add_output_variable` for that variable and for `Schedule Value` of the base schedule,
plus a `demand_shed_offset` global + `PythonPlugin:OutputVariable`.

```python
from pyenergyplus.plugin import EnergyPlusPlugin

THRESHOLD_W = 33500.0     # 0.82 x 40.85 kW baseline hourly peak
STEP_C = 0.5
MAX_STAGE = 4             # cap = +2.0 C
RELEASE_FRAC = 0.95
CMAX_C = 30.0
ZONES = ["Zone - Space %d" % n for n in list(range(101, 124)) + list(range(201, 222))]

class DemandShedController(EnergyPlusPlugin):
    def __init__(self):
        super().__init__()
        self.inited = False
        self.dem_h = -1; self.base_h = -1; self.gh = -1
        self.zone_h = []; self.stage = 0

    def _init(self, state):
        ex = self.api.exchange
        self.dem_h = ex.get_variable_handle(
            state, "Facility Total Electricity Demand Rate", "Whole Building")
        self.base_h = ex.get_variable_handle(state, "Schedule Value", "General Cooling Setpt")
        self.gh = ex.get_global_handle(state, "demand_shed_offset")
        if self.dem_h < 0 or self.base_h < 0 or self.gh < 0:            # handle 0 is VALID
            self.api.runtime.issue_severe(
                state, "handles dem=%d base=%d gh=%d" % (self.dem_h, self.base_h, self.gh))
            return False
        self.zone_h = []
        for z in ZONES:
            h = ex.get_actuator_handle(state, "Zone Temperature Control", "Cooling Setpoint", z)
            if h >= 0:
                self.zone_h.append(h)
        self.inited = True
        return True

    def on_begin_timestep_before_predictor(self, state):
        ex = self.api.exchange
        if not ex.api_data_fully_ready(state):
            return 0
        if not self.inited and not self._init(state):
            return 1
        d = ex.get_variable_value(state, self.dem_h)       # W, previous timestep (lagged)
        if d > THRESHOLD_W:
            if self.stage < MAX_STAGE: self.stage += 1
        elif d < THRESHOLD_W * RELEASE_FRAC:
            if self.stage > 0: self.stage -= 1
        offset = self.stage * STEP_C
        if offset > 0.0:
            target = ex.get_variable_value(state, self.base_h) + offset
            if target > CMAX_C: target = CMAX_C
            for h in self.zone_h:
                ex.set_actuator_value(state, h, target)
        else:
            for h in self.zone_h:
                ex.reset_actuator(state, h)              # hand control back to the schedule
        ex.set_global_value(state, self.gh, offset)
        return 0
```

**Things that did NOT work (don't repeat):** reading `Electricity:Facility` via
`get_meter_handle`/`get_meter_value` (0 at end-of-timestep, partial at begin-timestep);
assuming `list_output_variables` lists all available variables; running the user OSM before
`change_building_location`.
