"""Grid-interactive demand-limiting demo driver.

Runs inside the openstudio-mcp:dev container and drives the MCP server over
stdio (same pattern as the integration tests). Everything model-related goes
through MCP tools:

  Phase A (baseline characterization)
    create_baseline_osm -> add_baseline_system(7) -> change_building_location
    -> set_run_period(Jun-Aug) -> output variables/meters -> run_simulation

  Phase B (controller research loop)
    list_ems_actuators -> create_python_plugin(template="custom") with a staged
    demand-limiting supervisory controller -> run_simulation -> verify plugin
    loaded -> query_timeseries for baseline-vs-controlled comparison.

Timeseries/metrics JSON is dumped to /runs/demo_dr_analysis for plotting.
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
POLL_S = 10
SIM_TIMEOUT_S = 2400
MONTHS = [(6, 30), (7, 31), (8, 31)]
DEMAND_VAR = "Facility Total Electricity Demand Rate"

PLUGIN_TEMPLATE = '''
from pyenergyplus.plugin import EnergyPlusPlugin

ZONES = __ZONES__
THRESHOLD_W = __THRESHOLD_W__     # shed target: clip demand to this level
OFFSETS_K = [0.0, 1.5, 3.0]       # cooling setpoint offset per shed stage
WINDOW_START_HOUR = 13            # weekday peak window 13:00-18:00
WINDOW_END_HOUR = 18
DWELL_MINUTES = 30.0              # min time between stage-ups (stability)
RELEASE_MINUTES = 30.0            # staggered post-event release (anti-rebound)
FALLBACK_BASE_C = 23.9


class DemandLimiter(EnergyPlusPlugin):
    """Staged demand-limiting supervisory controller.

    Each zone timestep: read last timestep's whole-facility electric demand;
    inside the weekday peak window, ratchet the shed stage up (never down)
    whenever demand exceeds THRESHOLD_W, raising every zone's cooling setpoint
    by OFFSETS_K[stage]. After the window, release one stage per
    RELEASE_MINUTES so the recovery load returns gradually instead of as a
    rebound spike.
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
        print(f"[{time.strftime('%H:%M:%S')}] run {run_id}: {state}", flush=True)
        if state in terminal:
            if state != "success":
                errs = unwrap(await s.call_tool(
                    "extract_simulation_errors", {"run_id": run_id}))
                raise SystemExit(
                    f"run {run_id} ended {state}: "
                    f"{json.dumps(errs, default=str)[:4000]}")
            return status
        await asyncio.sleep(POLL_S)


async def month_series(s, run_id, var, key, month, mdays):
    r = await call(s, "query_timeseries", {
        "run_id": run_id, "variable_name": var, "key_value": key,
        "start_month": month, "start_day": 1,
        "end_month": month, "end_day": mdays, "max_points": 6000,
    })
    return r["data"]


async def day_series(s, run_id, var, key, month, day):
    r = await call(s, "query_timeseries", {
        "run_id": run_id, "variable_name": var, "key_value": key,
        "start_month": month, "start_day": day,
        "end_month": month, "end_day": day, "max_points": 400,
    })
    return r["data"]


def dump(name, obj):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(obj, indent=1, default=str))
    print(f"wrote {path}", flush=True)


async def collect_run_outputs(s, run_id, tag, zones_to_plot, peak):
    """Dump demand (3 summer months), peak-day zone temps/setpoints/OAT."""
    demand = {}
    for month, mdays in MONTHS:
        demand[str(month)] = await month_series(
            s, run_id, DEMAND_VAR, "Whole Building", month, mdays)
    dump(f"{tag}_demand", demand)

    pm, pd = peak
    day = {"oat": await day_series(
        s, run_id, "Site Outdoor Air Drybulb Temperature", "Environment", pm, pd)}
    for z in zones_to_plot:
        day[f"temp::{z}"] = await day_series(
            s, run_id, "Zone Mean Air Temperature", z, pm, pd)
        day[f"clgsp::{z}"] = await day_series(
            s, run_id, "Zone Thermostat Cooling Setpoint Temperature", z, pm, pd)
    dump(f"{tag}_peakday", day)

    metrics = await call(s, "extract_summary_metrics", {"run_id": run_id})
    enduse = await call(s, "extract_end_use_breakdown", {"run_id": run_id})
    dump(f"{tag}_metrics", {"summary": metrics, "end_use": enduse})


async def main():
    params = StdioServerParameters(command="openstudio-mcp", args=[], env=None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            # ---- Phase A: baseline testbed --------------------------------
            cr = await call(s, "create_baseline_osm", {"name": "demo_dr"})
            await call(s, "load_osm_model", {"osm_path": cr["osm_path"]})
            zr = await call(s, "list_thermal_zones", {"max_results": 0})
            zones = [z["name"] for z in zr["thermal_zones"]]
            print("zones:", zones, flush=True)
            await call(s, "add_baseline_system",
                       {"system_type": 7, "thermal_zone_names": zones})
            await call(s, "change_building_location", {"weather_file": EPW})
            await call(s, "set_run_period", {"begin_month": 6, "begin_day": 1,
                                             "end_month": 8, "end_day": 31})
            for var in [DEMAND_VAR,
                        "Zone Mean Air Temperature",
                        "Zone Thermostat Cooling Setpoint Temperature",
                        "Site Outdoor Air Drybulb Temperature"]:
                await call(s, "add_output_variable",
                           {"variable_name": var, "key_value": "*",
                            "reporting_frequency": "Timestep"})
            for meter in ["Electricity:Facility", "Cooling:Electricity",
                          "Fans:Electricity"]:
                await call(s, "add_output_meter",
                           {"meter_name": meter, "reporting_frequency": "Hourly"})
            await call(s, "save_osm_model",
                       {"osm_path": "/runs/demo_dr_baseline/model.osm"})
            sim = await call(s, "run_simulation", {
                "osm_path": "/runs/demo_dr_baseline/model.osm",
                "epw_path": EPW, "name": "demo_dr_baseline"})
            base_run = sim["run_id"]
            await poll_run(s, base_run)

            # Baseline peak + peak day (true peak: timestep resolution)
            peak_w, peak = 0.0, (7, 15)
            for month, mdays in MONTHS:
                for d in await month_series(
                        s, base_run, DEMAND_VAR, "Whole Building", month, mdays):
                    if d["value"] > peak_w:
                        peak_w, peak = d["value"], (d["month"], d["day"])
            print(f"baseline peak {peak_w:.0f} W on {peak}", flush=True)

            # ---- Phase B: author + run the controller ---------------------
            act = await call(s, "list_ems_actuators", {
                "component_type": "Zone Temperature Control",
                "control_type": "Cooling", "max_results": 0})
            dump("actuators", act)
            found = {a["actuator_key"].upper() for a in act["actuators"]}
            missing = [z for z in zones if z.upper() not in found]
            if missing:
                raise SystemExit(f"cooling setpoint actuators missing: {missing}")

            threshold_w = round(0.80 * peak_w, -2)
            code = (PLUGIN_TEMPLATE
                    .replace("__ZONES__", json.dumps(zones))
                    .replace("__THRESHOLD_W__", str(threshold_w)))
            created = await call(s, "create_python_plugin", {
                "name": "Demand Limiter", "template": "custom",
                "class_name": "DemandLimiter", "code": code,
                "global_variables": ["dr_stage"],
                "output_variable_name": "DR Shed Stage", "units": ""})
            dump("plugin_created", created)
            inspected = await call(s, "get_python_plugin", {"name": "Demand Limiter"})
            dump("plugin_inspect", inspected)

            await call(s, "save_osm_model",
                       {"osm_path": "/runs/demo_dr_shed/model.osm"})
            sim2 = await call(s, "run_simulation", {
                "osm_path": "/runs/demo_dr_shed/model.osm",
                "epw_path": EPW, "name": "demo_dr_shed"})
            shed_run = sim2["run_id"]
            await poll_run(s, shed_run)

            errs = await call(s, "extract_simulation_errors", {"run_id": shed_run})
            dump("shed_sim_errors", errs)
            errtxt = await call(s, "read_file", {
                "file_path": f"/runs/{shed_run}/run/eplusout.err",
                "max_bytes": 200000})
            imported = [ln for ln in errtxt.get("text", "").splitlines()
                        if "PythonPlugin" in ln]
            dump("plugin_import_lines", imported)

            # ---- Outputs for plotting -------------------------------------
            zones_to_plot = []
            for want in ("Core", "South"):
                match = [z for z in zones if want.lower() in z.lower()
                         and "2" in z]
                zones_to_plot += match[:1]
            if not zones_to_plot:
                zones_to_plot = zones[:2]
            print("plot zones:", zones_to_plot, flush=True)

            await collect_run_outputs(s, base_run, "baseline", zones_to_plot, peak)
            await collect_run_outputs(s, shed_run, "shed", zones_to_plot, peak)

            pm, pd = peak
            stage = await day_series(s, shed_run, "PythonPlugin:OutputVariable",
                                     "DR Shed Stage", pm, pd)
            dump("shed_stage_peakday", stage)

            shed_peak_w = 0.0
            for month, mdays in MONTHS:
                for d in await month_series(
                        s, shed_run, DEMAND_VAR, "Whole Building", month, mdays):
                    shed_peak_w = max(shed_peak_w, d["value"])

            dump("manifest", {
                "epw": EPW, "zones": zones, "zones_to_plot": zones_to_plot,
                "baseline_run": base_run, "shed_run": shed_run,
                "baseline_peak_w": peak_w, "shed_peak_w": shed_peak_w,
                "threshold_w": threshold_w, "peak_day": {"month": pm, "day": pd},
                "window": "weekdays 13:00-18:00",
                "offsets_k": [0.0, 1.5, 3.0],
                "dwell_min": 30, "release_min": 30,
            })
            print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
