"""DR demo iteration 2 — controller revision via edit_python_plugin.

Iteration 1 finding: the 13:00-18:00 event window missed the building's true
daily peak (08:30 morning-recovery spike), so the seasonal billing peak was
untouched. Revision: cover the full utility on-peak window (weekdays
08:00-19:00), 4 shed stages, threshold set from the *run-period* (design-day
deduped) baseline peak.

Reuses the existing baseline run; edits the plugin in the shed model in place,
reruns it, and re-collects analysis JSON.
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

PLUGIN_TEMPLATE = '''
from pyenergyplus.plugin import EnergyPlusPlugin

ZONES = __ZONES__
THRESHOLD_W = __THRESHOLD_W__     # shed target: clip demand to this level
OFFSETS_K = [0.0, 1.0, 2.0, 3.0]  # cooling setpoint offset per shed stage
WINDOW_START_HOUR = 8             # weekday utility on-peak window 08:00-19:00
WINDOW_END_HOUR = 19
DWELL_MINUTES = 20.0              # min time between stage-ups (stability)
RELEASE_MINUTES = 30.0            # staggered post-event release (anti-rebound)
FALLBACK_BASE_C = 23.9


class DemandLimiter(EnergyPlusPlugin):
    """Staged demand-limiting supervisory controller (revision 2).

    Each zone timestep: read last timestep's whole-facility electric demand;
    inside the weekday on-peak window, ratchet the shed stage up (never down)
    whenever demand exceeds THRESHOLD_W, raising every zone's cooling setpoint
    by OFFSETS_K[stage]. After the window, release one stage per
    RELEASE_MINUTES so recovery load returns gradually (no rebound spike).
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
        dow = ex.day_of_week(state)        # 1=Sunday .. 7=Saturday
        weekday = 2 <= dow <= 6
        demand_w = ex.get_variable_value(state, self.h_demand)
        in_window = weekday and WINDOW_START_HOUR <= hour < WINDOW_END_HOUR

        if not in_window and self.stage == 0:
            # Unoverridden: remember each zone's scheduled cooling setpoint so
            # shed offsets stack on the schedule, not on our own override.
            for zone in ZONES:
                self.base_clg[zone] = ex.get_variable_value(
                    state, self.h_clg_sens[zone])

        if in_window:
            if (demand_w > THRESHOLD_W
                    and self.stage < len(OFFSETS_K) - 1
                    and self.minutes_since_change >= DWELL_MINUTES):
                self.stage += 1
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


async def month_series(s, run_id, var, key, month, mdays, freq=None):
    args = {"run_id": run_id, "variable_name": var, "key_value": key,
            "start_month": month, "start_day": 1,
            "end_month": month, "end_day": mdays, "max_points": 6000}
    if freq:
        args["frequency"] = freq
    r = await call(s, "query_timeseries", args)
    return r["data"]


async def day_series(s, run_id, var, key, month, day, freq=None):
    args = {"run_id": run_id, "variable_name": var, "key_value": key,
            "start_month": month, "start_day": day,
            "end_month": month, "end_day": day, "max_points": 2000}
    if freq:
        args["frequency"] = freq
    r = await call(s, "query_timeseries", args)
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
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(obj, indent=1, default=str))
    print(f"wrote {path}", flush=True)


async def main():
    params = StdioServerParameters(command="openstudio-mcp", args=[], env=None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            # True baseline peak from design-day-deduped series
            base_demand = {}
            for month, mdays in MONTHS:
                base_demand[str(month)] = await month_series(
                    s, BASELINE_RUN, DEMAND_VAR, "Whole Building", month, mdays)
            ball = dedupe([d for m in base_demand.values() for d in m])
            (pm, pd_, ph, pmin), peak_w = max(ball.items(), key=lambda kv: kv[1])
            threshold_w = round(0.82 * peak_w, -2)
            print(f"true baseline peak {peak_w/1000:.1f} kW at "
                  f"{pm}/{pd_} {ph:02d}:{pmin:02d}; threshold {threshold_w/1000:.1f} kW",
                  flush=True)

            # ---- Revise controller via edit_python_plugin -----------------
            await call(s, "load_osm_model",
                       {"osm_path": "/runs/demo_dr_shed/model.osm"})
            zr = await call(s, "list_thermal_zones", {"max_results": 0})
            zones = [z["name"] for z in zr["thermal_zones"]]
            code = (PLUGIN_TEMPLATE
                    .replace("__ZONES__", json.dumps(zones))
                    .replace("__THRESHOLD_W__", str(threshold_w)))
            edited = await call(s, "edit_python_plugin",
                                {"name": "Demand Limiter", "code": code})
            dump("plugin_edited_v2", edited)
            await call(s, "save_osm_model",
                       {"osm_path": "/runs/demo_dr_shed/model.osm"})
            sim = await call(s, "run_simulation", {
                "osm_path": "/runs/demo_dr_shed/model.osm",
                "epw_path": EPW, "name": "demo_dr_shed_v2"})
            shed_run = sim["run_id"]
            await poll_run(s, shed_run)
            errs = await call(s, "extract_simulation_errors", {"run_id": shed_run})
            dump("shed2_sim_errors", errs)

            # ---- Collect comparison data ----------------------------------
            shed_demand = {}
            for month, mdays in MONTHS:
                shed_demand[str(month)] = await month_series(
                    s, shed_run, DEMAND_VAR, "Whole Building", month, mdays)
            dump("shed2_demand", shed_demand)
            sall = dedupe([d for m in shed_demand.values() for d in m])
            speak = max(sall.values())
            print(f"shed v2 peak {speak/1000:.1f} kW "
                  f"({100*(peak_w-speak)/peak_w:.1f}% below baseline)", flush=True)

            # Peak-day detail (baseline peak day), both runs
            for tag, run_id in (("baseline", BASELINE_RUN), ("shed2", shed_run)):
                day = {
                    "demand": await day_series(
                        s, run_id, DEMAND_VAR, "Whole Building", pm, pd_),
                    "oat": await day_series(
                        s, run_id, "Site Outdoor Air Drybulb Temperature",
                        "Environment", pm, pd_),
                }
                for z in ZONES_TO_PLOT:
                    day[f"temp::{z}"] = await day_series(
                        s, run_id, "Zone Mean Air Temperature", z, pm, pd_)
                    day[f"clgsp::{z}"] = await day_series(
                        s, run_id, "Zone Thermostat Cooling Setpoint Temperature",
                        z, pm, pd_)
                for meter in ("Cooling:Electricity", "Fans:Electricity"):
                    day[f"meter::{meter}"] = await day_series(
                        s, run_id, meter, "*", pm, pd_)
                dump(f"{tag}_peakday_v2", day)

            stage = await day_series(s, shed_run, "PythonPlugin:OutputVariable",
                                     "DR Shed Stage", pm, pd_)
            dump("shed2_stage_peakday", stage)

            metrics = await call(s, "extract_summary_metrics", {"run_id": shed_run})
            enduse = await call(s, "extract_end_use_breakdown", {"run_id": shed_run})
            dump("shed2_metrics", {"summary": metrics, "end_use": enduse})

            # Monthly energy (hourly facility meter, deduped) for both runs
            energy = {}
            for tag, run_id in (("baseline", BASELINE_RUN), ("shed2", shed_run)):
                energy[tag] = {}
                for month, mdays in MONTHS:
                    rows = await month_series(
                        s, run_id, "Electricity:Facility", "*", month, mdays)
                    per_stamp = dedupe(rows)
                    energy[tag][str(month)] = sum(per_stamp.values()) / 3.6e9  # J->MWh
            dump("monthly_energy_mwh", energy)

            # Monthly true peaks
            peaks = {"baseline": {}, "shed2": {}}
            for month, _ in MONTHS:
                peaks["baseline"][str(month)] = max(
                    v for k, v in ball.items() if k[0] == month)
                peaks["shed2"][str(month)] = max(
                    v for k, v in sall.items() if k[0] == month)
            dump("monthly_peaks_w", peaks)

            dump("manifest_v2", {
                "baseline_run": BASELINE_RUN, "shed_run": shed_run,
                "baseline_peak_w": peak_w, "shed_peak_w": speak,
                "threshold_w": threshold_w,
                "peak_stamp": {"month": pm, "day": pd_, "hour": ph, "minute": pmin},
                "window": "weekdays 08:00-19:00",
                "offsets_k": [0.0, 1.0, 2.0, 3.0],
                "dwell_min": 20, "release_min": 30,
                "zones_to_plot": ZONES_TO_PLOT,
            })
            print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
