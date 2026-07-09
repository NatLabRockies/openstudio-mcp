"""DR demo iteration 3 — final controller revision.

Iteration 2 findings: (a) this building runs 7-day schedules, so weekend peaks
(329 kW Sat 6/26) escape a weekday-only window; (b) 20-min dwell lets the 08:30
startup spike through (320 kW residual). Revision: window applies every day,
10-min dwell, and a 2-stage jump when demand exceeds 115% of threshold.
Threshold unchanged (276.9 kW) for comparability.
"""
import asyncio
import json
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EPW = ("/opt/comstock-measures/ChangeBuildingLocation"
       "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")
OUT = Path("/runs/demo_dr_analysis")
POLL_S = 8
SIM_TIMEOUT_S = 2400
MONTHS = [(6, 30), (7, 31), (8, 31)]
DEMAND_VAR = "Facility Total Electricity Demand Rate"
BASELINE_RUN = "run_demo_dr_baseline_ce6de7f0a0c1"
ZONES_TO_PLOT = ["Story 2 Core Thermal Zone", "Story 2 South Perimeter Thermal Zone"]
THRESHOLD_W = 276900.0
PEAK_DAY = (6, 27)     # baseline peak weekday (morning spike + full afternoon)
WEEKEND_DAY = (6, 26)  # Saturday that set the v2 residual seasonal peak

PLUGIN_TEMPLATE = '''
from pyenergyplus.plugin import EnergyPlusPlugin

ZONES = __ZONES__
THRESHOLD_W = __THRESHOLD_W__     # shed target: clip demand to this level
OFFSETS_K = [0.0, 1.0, 2.0, 3.0]  # cooling setpoint offset per shed stage
WINDOW_START_HOUR = 8             # on-peak window 08:00-19:00, every day
WINDOW_END_HOUR = 19              # (this building runs 7-day schedules)
DWELL_MINUTES = 10.0              # min time between stage moves
JUMP_RATIO = 1.15                 # >115% of threshold from idle -> jump 2 stages
RELEASE_MINUTES = 30.0            # staggered post-event release (anti-rebound)
FALLBACK_BASE_C = 23.9


class DemandLimiter(EnergyPlusPlugin):
    """Staged demand-limiting supervisory controller (revision 3).

    Each zone timestep: read last timestep's whole-facility electric demand;
    inside the daily on-peak window, ratchet the shed stage up (never down)
    whenever demand exceeds THRESHOLD_W -- jumping two stages from idle on
    large excursions -- raising every zone's cooling setpoint by
    OFFSETS_K[stage]. After the window, release one stage per RELEASE_MINUTES
    so recovery load returns gradually (no rebound spike).
    """

    def __init__(self):
        super().__init__()
        self.handles_ready = False
        self.h_demand = -1
        self.h_stage = -1
        self.h_clg_act = {}
        self.h_clg_sens = {}
        self.base_clg = {}
        self.stage = 0
        self.minutes_since_change = 1.0e9

    def _lookup_handles(self, state):
        ex = self.api.exchange
        self.h_demand = ex.get_variable_handle(
            state, "Facility Total Electricity Demand Rate", "Whole Building")
        self.h_stage = ex.get_global_handle(state, "dr_stage")
        for zone in ZONES:
            self.h_clg_act[zone] = ex.get_actuator_handle(
                state, "Zone Temperature Control", "Cooling Setpoint", zone)
            self.h_clg_sens[zone] = ex.get_variable_handle(
                state, "Zone Thermostat Cooling Setpoint Temperature", zone)
        bad = []
        if self.h_demand == -1:
            bad.append("facility demand sensor")
        if self.h_stage == -1:
            bad.append("dr_stage global")
        bad += ["actuator " + z for z, h in self.h_clg_act.items() if h == -1]
        bad += ["setpoint sensor " + z for z, h in self.h_clg_sens.items() if h == -1]
        return bad

    def _weather_run(self, state):
        # Only actuate during the weather-file run period -- overriding
        # setpoints during sizing design days would shrink the cooling plant
        # and corrupt the baseline-vs-controlled comparison.
        try:
            return int(self.api.exchange.kind_of_sim(state)) == 3
        except Exception:
            return True

    def on_begin_timestep_before_predictor(self, state) -> int:
        ex = self.api.exchange
        if not ex.api_data_fully_ready(state):
            return 0
        if not self.handles_ready:
            bad = self._lookup_handles(state)
            if bad:
                self.api.runtime.issue_severe(
                    state, "DemandLimiter handle lookup failed: " + ", ".join(bad))
                return 1
            self.handles_ready = True
        if not self._weather_run(state):
            ex.set_global_value(state, self.h_stage, 0.0)
            return 0

        dt_minutes = 60.0 * ex.zone_time_step(state)
        self.minutes_since_change += dt_minutes
        hour = ex.hour(state)              # 0-23
        demand_w = ex.get_variable_value(state, self.h_demand)
        in_window = WINDOW_START_HOUR <= hour < WINDOW_END_HOUR

        if not in_window and self.stage == 0:
            # Unoverridden: remember each zone's scheduled cooling setpoint so
            # shed offsets stack on the schedule, not on our own override.
            for zone in ZONES:
                self.base_clg[zone] = ex.get_variable_value(
                    state, self.h_clg_sens[zone])

        max_stage = len(OFFSETS_K) - 1
        if in_window:
            if (demand_w > THRESHOLD_W and self.stage < max_stage
                    and self.minutes_since_change >= DWELL_MINUTES):
                step = 2 if (self.stage == 0
                             and demand_w > JUMP_RATIO * THRESHOLD_W) else 1
                self.stage = min(self.stage + step, max_stage)
                self.minutes_since_change = 0.0
        elif self.stage > 0 and self.minutes_since_change >= RELEASE_MINUTES:
            self.stage -= 1
            self.minutes_since_change = 0.0

        for zone in ZONES:
            if self.stage == 0:
                ex.reset_actuator(state, self.h_clg_act[zone])
            else:
                base = self.base_clg.get(zone, FALLBACK_BASE_C)
                ex.set_actuator_value(
                    state, self.h_clg_act[zone], base + OFFSETS_K[self.stage])
        ex.set_global_value(state, self.h_stage, float(self.stage))
        return 0
'''


def unwrap(res):
    content = getattr(res, "content", None)
    if not content:
        return res if isinstance(res, dict) else {"_raw": str(res)}
    text = getattr(content[0], "text", None)
    if text is None:
        return str(content[0])
    try:
        return json.loads(text.strip())
    except Exception:
        return text.strip()


async def call(s, tool, args=None, must=True):
    res = unwrap(await s.call_tool(tool, args or {}))
    ok = isinstance(res, dict) and res.get("ok") is True
    print(f"[{time.strftime('%H:%M:%S')}] {tool} -> {'ok' if ok else 'FAIL'}",
          flush=True)
    if must and not ok:
        raise SystemExit(f"{tool} failed: {json.dumps(res, default=str)[:3000]}")
    return res


async def poll_run(s, run_id):
    terminal = {"success", "failed", "error", "cancelled"}
    started = time.time()
    while True:
        if time.time() - started > SIM_TIMEOUT_S:
            raise SystemExit(f"run {run_id} timed out")
        status = unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))
        state = (status.get("run", {}).get("status") or "unknown").lower()
        if state in terminal:
            if state != "success":
                errs = unwrap(await s.call_tool(
                    "extract_simulation_errors", {"run_id": run_id}))
                raise SystemExit(
                    f"run {run_id} ended {state}: "
                    f"{json.dumps(errs, default=str)[:4000]}")
            print(f"run {run_id}: {state}", flush=True)
            return status
        await asyncio.sleep(POLL_S)


async def series(s, run_id, var, key, m1, d1, m2, d2, cap):
    r = await call(s, "query_timeseries", {
        "run_id": run_id, "variable_name": var, "key_value": key,
        "start_month": m1, "start_day": d1,
        "end_month": m2, "end_day": d2, "max_points": cap})
    return r["data"]


def dedupe(rows):
    """Sizing design days share calendar dates with the run period; the
    run-period environment is simulated last, so keep the last row per stamp."""
    out = {}
    for d in rows:
        out[(d["month"], d["day"], d["hour"], d["minute"])] = d["value"]
    return out


def dump(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=1, default=str))
    print(f"wrote {name}.json", flush=True)


async def main():
    params = StdioServerParameters(command="openstudio-mcp", args=[], env=None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            await call(s, "load_osm_model",
                       {"osm_path": "/runs/demo_dr_shed/model.osm"})
            zr = await call(s, "list_thermal_zones", {"max_results": 0})
            zones = [z["name"] for z in zr["thermal_zones"]]
            code = (PLUGIN_TEMPLATE
                    .replace("__ZONES__", json.dumps(zones))
                    .replace("__THRESHOLD_W__", str(THRESHOLD_W)))
            await call(s, "edit_python_plugin",
                       {"name": "Demand Limiter", "code": code})
            plugin = await call(s, "get_python_plugin", {"name": "Demand Limiter"})
            dump("plugin_v3", plugin)
            await call(s, "save_osm_model",
                       {"osm_path": "/runs/demo_dr_shed/model.osm"})
            sim = await call(s, "run_simulation", {
                "osm_path": "/runs/demo_dr_shed/model.osm",
                "epw_path": EPW, "name": "demo_dr_shed_v3"})
            shed_run = sim["run_id"]
            await poll_run(s, shed_run)
            errs = await call(s, "extract_simulation_errors", {"run_id": shed_run})
            dump("shed3_sim_errors", errs)

            shed_demand = {}
            for month, mdays in MONTHS:
                shed_demand[str(month)] = await series(
                    s, shed_run, DEMAND_VAR, "Whole Building",
                    month, 1, month, mdays, 6000)
            dump("shed3_demand", shed_demand)
            sall = dedupe([d for m in shed_demand.values() for d in m])
            speak_stamp, speak = max(sall.items(), key=lambda kv: kv[1])
            print(f"shed v3 peak {speak/1000:.1f} kW at {speak_stamp}", flush=True)

            for tag, (pm, pd_) in (("peakday", PEAK_DAY), ("weekend", WEEKEND_DAY)):
                day = {"demand": await series(
                    s, shed_run, DEMAND_VAR, "Whole Building", pm, pd_, pm, pd_, 2000)}
                if tag == "peakday":
                    day["oat"] = await series(
                        s, shed_run, "Site Outdoor Air Drybulb Temperature",
                        "Environment", pm, pd_, pm, pd_, 2000)
                    for z in ZONES_TO_PLOT:
                        day[f"temp::{z}"] = await series(
                            s, shed_run, "Zone Mean Air Temperature",
                            z, pm, pd_, pm, pd_, 2000)
                        day[f"clgsp::{z}"] = await series(
                            s, shed_run,
                            "Zone Thermostat Cooling Setpoint Temperature",
                            z, pm, pd_, pm, pd_, 2000)
                day["stage"] = await series(
                    s, shed_run, "PythonPlugin:OutputVariable", "DR Shed Stage",
                    pm, pd_, pm, pd_, 2000)
                dump(f"shed3_{tag}", day)

            # Baseline weekend-day demand for the weekend comparison panel
            wm, wd = WEEKEND_DAY
            dump("baseline_weekend", {"demand": await series(
                s, BASELINE_RUN, DEMAND_VAR, "Whole Building", wm, wd, wm, wd, 2000)})

            metrics = await call(s, "extract_summary_metrics", {"run_id": shed_run})
            enduse = await call(s, "extract_end_use_breakdown", {"run_id": shed_run})
            dump("shed3_metrics", {"summary": metrics, "end_use": enduse})

            energy = {}
            for month, mdays in MONTHS:
                rows = await series(s, shed_run, "Electricity:Facility", "*",
                                    month, 1, month, mdays, 6000)
                energy[str(month)] = sum(dedupe(rows).values()) / 3.6e9  # J->MWh
            dump("shed3_monthly_energy_mwh", energy)

            peaks = {}
            for month, _ in MONTHS:
                peaks[str(month)] = max(v for k, v in sall.items() if k[0] == month)
            dump("shed3_monthly_peaks_w", peaks)

            dump("manifest_v3", {
                "baseline_run": BASELINE_RUN, "shed_run": shed_run,
                "shed_peak_w": speak, "shed_peak_stamp": speak_stamp,
                "threshold_w": THRESHOLD_W,
                "window": "every day 08:00-19:00",
                "offsets_k": [0.0, 1.0, 2.0, 3.0],
                "dwell_min": 10, "jump_ratio": 1.15, "release_min": 30,
            })
            print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
