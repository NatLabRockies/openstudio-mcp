"""In-image fact extractor for LLM benchmark outcome grading.

Runs INSIDE the pinned benchmark image (/opt/venv/bin/python) via
`docker run` from tests/llm/grading/host.py. Uses the OpenStudio SDK and
CLI directly — no MCP server, no mcp_server imports — so the grader is
independent of the system under test. Emits exactly one JSON line on
stdout (facts only; pass/fail lives in rubric.py on the host).

Modes:
  inspect       — load an OSM, dump model facts (+ optional baseline OSM)
  apply_measure — stage an authored measure + seed OSM, run
                  `openstudio run --measures_only`, dump facts of run/in.osm
  ems_sim       — copy saved OSM (+ sibling files/), inject weather, a
                  Jan 1-14 run period and a thermostat-setpoint output
                  variable, run EnergyPlus, dump night/day setpoint stats
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import openstudio

EPW = "/opt/comstock-measures/ChangeBuildingLocation/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw"


def _load_model(osm_path: str) -> openstudio.model.Model | None:
    vt = openstudio.osversion.VersionTranslator()
    m = vt.loadModel(openstudio.toPath(osm_path))
    return m.get() if m.is_initialized() else None


def _layer_resistance(mat) -> float | None:
    std = mat.to_StandardOpaqueMaterial()
    if std.is_initialized():
        return std.get().thermalResistance()
    massless = mat.to_MasslessOpaqueMaterial()
    if massless.is_initialized():
        return massless.get().thermalResistance()
    air = mat.to_AirGap()
    if air.is_initialized():
        return air.get().thermalResistance()
    return None


def model_facts(model) -> dict:
    """Generic fact dump — a superset so the rubric can evolve post-hoc."""
    facts = {
        "n_spaces": len(model.getSpaces()),
        "n_thermal_zones": len(model.getThermalZones()),
        "floor_area_m2": round(model.getBuilding().floorArea(), 2),
        "plant_loops": sorted(pl.nameString() for pl in model.getPlantLoops()),
    }

    loops = []
    zones_on_loops = set()
    for al in model.getAirLoopHVACs():
        served = sorted(z.nameString() for z in al.thermalZones())
        zones_on_loops.update(served)
        terminals: dict[str, int] = {}
        for comp in al.demandComponents():
            cls = comp.iddObjectType().valueDescription()
            if "AirTerminal" in cls:
                terminals[cls] = terminals.get(cls, 0) + 1
        loops.append({"name": al.nameString(), "zones_served": served,
                      "terminals": terminals})
    facts["air_loops"] = loops
    facts["n_zones_on_air_loops"] = len(zones_on_loops)

    zone_equip = []
    for z in model.getThermalZones():
        heating_order = [e.nameString() for e in z.equipmentInHeatingOrder()]
        cooling_order = [e.nameString() for e in z.equipmentInCoolingOrder()]
        classes = {e.nameString(): e.iddObjectType().valueDescription()
                   for e in z.equipment()}
        zone_equip.append({"zone": z.nameString(), "equipment_classes": classes,
                           "heating_order": heating_order,
                           "cooling_order": cooling_order})
    facts["zone_equipment"] = zone_equip

    roofs = []
    for s in model.getSurfaces():
        if s.surfaceType() != "RoofCeiling" or s.outsideBoundaryCondition() != "Outdoors":
            continue
        entry = {"surface": s.nameString(), "construction": None,
                 "layers": [], "assembly_r_si": None}
        c = s.construction()
        if c.is_initialized():
            entry["construction"] = c.get().nameString()
            layered = c.get().to_LayeredConstruction()
            if layered.is_initialized():
                total_r = 0.0
                r_known = True
                for mat in layered.get().layers():
                    r = _layer_resistance(mat)
                    entry["layers"].append(
                        {"name": mat.nameString(),
                         "class": mat.iddObjectType().valueDescription(),
                         "r_si": None if r is None else round(r, 4)})
                    if r is None:
                        r_known = False
                    else:
                        total_r += r
                if r_known:
                    entry["assembly_r_si"] = round(total_r, 4)
        roofs.append(entry)
    facts["roof_surfaces"] = roofs

    thermostats = []
    for z in model.getThermalZones():
        t = z.thermostatSetpointDualSetpoint()
        if not t.is_initialized():
            continue
        entry = {"zone": z.nameString(), "heating_schedule": None,
                 "cooling_schedule": None}
        hs = t.get().heatingSetpointTemperatureSchedule()
        if hs.is_initialized():
            entry["heating_schedule"] = hs.get().nameString()
        cs = t.get().coolingSetpointTemperatureSchedule()
        if cs.is_initialized():
            entry["cooling_schedule"] = cs.get().nameString()
        thermostats.append(entry)
    facts["thermostats"] = thermostats

    facts["python_plugins"] = sorted(
        p.nameString() for p in model.getPythonPluginInstances())
    facts["external_files"] = sorted(
        f.fileName() for f in model.getExternalFiles())
    return facts


def inspect_mode(args) -> dict:
    model = _load_model(args.osm)
    if model is None:
        return {"load_ok": False, "error": f"could not load {args.osm}"}
    out = {"load_ok": True, "model": model_facts(model)}
    if args.baseline:
        base = _load_model(args.baseline)
        out["baseline"] = ({"error": "baseline load failed"} if base is None
                           else model_facts(base))
    return out


def _run_cli(cmd: list[str], cwd: Path, timeout: int) -> dict:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed openstudio CLI argv, staged inputs
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=timeout, check=False)
        return {"rc": proc.returncode, "stderr_tail": proc.stderr[-1000:]}
    except subprocess.TimeoutExpired:
        return {"rc": -1, "stderr_tail": f"timeout after {timeout}s"}


def _measure_arguments(measure_dir: Path) -> list[dict]:
    m = openstudio.BCLMeasure.load(openstudio.toPath(str(measure_dir)))
    if not m.is_initialized():
        return [{"error": "BCLMeasure load failed"}]
    args = []
    for a in m.get().arguments():
        default = a.defaultValue()
        args.append({"name": a.name(), "required": a.required(),
                     "default": default.get() if default.is_initialized() else None})
    return args


def apply_measure_mode(args) -> dict:
    work = Path(args.work)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    src = Path(args.measure_dir)
    if not src.is_dir():
        return {"measure_ran": False, "error": f"measure dir missing: {src}"}
    facts: dict = {"measure_arguments": _measure_arguments(src)}
    shutil.copytree(src, work / "measures" / src.name)
    shutil.copy2(args.osm, work / "seed.osm")
    osw = {"seed_file": "seed.osm", "measure_paths": ["measures"],
           "run_directory": "run",
           "steps": [{"measure_dir_name": src.name, "arguments": {}}]}
    (work / "workflow.osw").write_text(json.dumps(osw))

    run = _run_cli(["openstudio", "run", "--measures_only", "-w", "workflow.osw"],
                   work, timeout=240)
    facts["cli_rc"] = run["rc"]
    facts["cli_stderr_tail"] = run["stderr_tail"]

    out_osw = work / "out.osw"
    facts["measure_ran"] = False
    if out_osw.exists():
        out = json.loads(out_osw.read_text(encoding="utf-8", errors="replace"))
        facts["completed_status"] = out.get("completed_status")
        steps = out.get("steps", [])
        if steps:
            result = steps[0].get("result", {})
            facts["runner_result"] = result.get("step_result")
            facts["runner_errors"] = list(result.get("step_errors", []))[:10]
            facts["runner_warnings_n"] = len(result.get("step_warnings", []))
        facts["measure_ran"] = facts.get("completed_status") == "Success"

    in_osm = work / "run" / "in.osm"
    if in_osm.exists():
        model = _load_model(str(in_osm))
        if model is not None:
            facts["result_model"] = model_facts(model)
    return facts


def _setpoint_stats(sql_path: Path, variable: str) -> dict:
    """Night/day stats per key for a reported variable, run-period env only.

    Rows are classified by the START of their reporting interval (minutes
    since midnight): night = [0, 360) + [1080, 1440). Warmup and sizing
    rows are excluded (issue #87: design-day rows blend into results).
    """
    con = sqlite3.connect(str(sql_path))
    try:
        rows = con.execute(
            """
            SELECT rdd.KeyValue, t.Hour, t.Minute, t.Interval, rd.Value
            FROM ReportData rd
            JOIN ReportDataDictionary rdd
              ON rd.ReportDataDictionaryIndex = rdd.ReportDataDictionaryIndex
            JOIN Time t ON rd.TimeIndex = t.TimeIndex
            WHERE rdd.Name = ?
              AND t.EnvironmentPeriodIndex IN
                  (SELECT EnvironmentPeriodIndex FROM EnvironmentPeriods
                   WHERE EnvironmentType = 3)
              AND (t.WarmupFlag IS NULL OR t.WarmupFlag = 0)
            """, (variable,)).fetchall()
    finally:
        con.close()

    per_key: dict[str, dict[str, list[float]]] = {}
    for key, hour, minute, interval, value in rows:
        # E+ Time rows mark the interval END as (Hour, Minute) with the clock
        # hour NOT decremented (18:00-18:10 -> Hour=18, Minute=10), so the
        # interval start is end minus Interval — validated against a known
        # 15.6/21.1 schedule_override plugin (one-hour shift = mean 16.058)
        start_min = hour * 60 + (minute or 0) - (interval or 0)
        bucket = "night" if (start_min < 360 or start_min >= 1080) else "day"
        per_key.setdefault(key, {"night": [], "day": []})[bucket].append(value)

    stats = {}
    for key, buckets in per_key.items():
        entry = {}
        for bucket, values in buckets.items():
            if values:
                entry[bucket] = {"mean": round(sum(values) / len(values), 3),
                                 "min": round(min(values), 3),
                                 "max": round(max(values), 3),
                                 "n": len(values)}
        stats[key] = entry
    return stats


def ems_sim_mode(args) -> dict:
    work = Path(args.work)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    src_osm = Path(args.osm)
    if not src_osm.exists():
        return {"saved": False, "error": f"saved model missing: {src_osm}"}
    facts: dict = {"saved": True}
    src_files = src_osm.parent / "files"
    if src_files.is_dir():
        shutil.copytree(src_files, work / "files")
    model = _load_model(str(src_osm))
    if model is None:
        return facts | {"load_ok": False, "error": "could not load saved model"}
    facts["load_ok"] = True
    facts["python_plugins"] = sorted(
        p.nameString() for p in model.getPythonPluginInstances())

    epw = openstudio.EpwFile(openstudio.toPath(args.epw))
    openstudio.model.WeatherFile.setWeatherFile(model, epw)
    # Ideal air loads on the COPY: the baseline fixture has no HVAC and the
    # forward translator drops thermostats for unconditioned zones — without
    # this, "Zone Thermostat Heating Setpoint Temperature" never reports.
    for zone in model.getThermalZones():
        zone.setUseIdealAirLoads(True)
    rp = model.getRunPeriod()
    rp.setBeginMonth(1)
    rp.setBeginDayOfMonth(1)
    rp.setEndMonth(1)
    rp.setEndDayOfMonth(14)
    ov = openstudio.model.OutputVariable(
        "Zone Thermostat Heating Setpoint Temperature", model)
    ov.setKeyValue("*")
    ov.setReportingFrequency("Timestep")
    model.save(openstudio.toPath(str(work / "model.osm")), True)

    osw = {"seed_file": "model.osm", "run_directory": "run"}
    (work / "workflow.osw").write_text(json.dumps(osw))
    run = _run_cli(["openstudio", "run", "-w", "workflow.osw"], work, timeout=540)
    facts["cli_rc"] = run["rc"]
    facts["cli_stderr_tail"] = run["stderr_tail"]

    sql = work / "run" / "eplusout.sql"
    facts["sim_ran"] = sql.exists() and run["rc"] == 0
    err = work / "run" / "eplusout.err"
    if err.exists():
        err_text = err.read_text(encoding="utf-8", errors="replace")
        facts["eplus_severe_n"] = err_text.count("** Severe  **")
        facts["eplus_fatal"] = "**  Fatal  **" in err_text
    if facts["sim_ran"]:
        facts["setpoint_stats"] = _setpoint_stats(
            sql, "Zone Thermostat Heating Setpoint Temperature")
        facts["schedule_value_stats"] = _setpoint_stats(sql, "Schedule Value")
    return facts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", required=True,
                    choices=["inspect", "apply_measure", "ems_sim"])
    ap.add_argument("--osm", required=True, help="model under grading")
    ap.add_argument("--baseline", help="inspect: comparison OSM (e.g. fixture)")
    ap.add_argument("--measure-dir", help="apply_measure: authored measure dir")
    ap.add_argument("--work", help="scratch dir for CLI runs")
    ap.add_argument("--epw", default=EPW)
    args = ap.parse_args()

    if args.mode == "inspect":
        facts = inspect_mode(args)
    elif args.mode == "apply_measure":
        facts = apply_measure_mode(args)
    else:
        facts = ems_sim_mode(args)
    print(json.dumps(facts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
