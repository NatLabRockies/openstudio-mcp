"""EMS actuator discovery via a hidden sizing-only EnergyPlus run.

Valid actuator (component type, control type, key) triples are model-dependent
and only EnergyPlus can enumerate them (eplusout.edd). A sizing-only run of the
loaded model takes ~1-2 s, so discovery is synchronous; the throwaway run dir
never appears in the run list and is deleted after parsing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from typing import Any

import openstudio

from mcp_server import model_manager, sandbox
from mcp_server.config import OSCLI_GEM_PATH, OSCLI_GEMFILE, user_run_root
from mcp_server.skills.python_ems.edd_parser import parse_edd

_DISCOVERY_TIMEOUT_SECONDS = 300


def _matches(value: str, needle: str | None) -> bool:
    return needle is None or needle.strip().lower() in value.lower()


def list_ems_actuators_op(
    component_type: str | None = None,
    control_type: str | None = None,
    key: str | None = None,
    include_internal_variables: bool = False,
    max_results: int = 50,
) -> dict[str, Any]:
    """Run a sizing-only sim of the loaded model and parse its .edd dictionary."""
    model = model_manager.get_model_if_loaded()
    if model is None:
        return {"ok": False, "error": "No model loaded. Call load_osm_model first."}
    if len(model.getDesignDays()) == 0:
        return {
            "ok": False,
            "error": "Model has no design days; the discovery run is sizing-only. "
                     "Use add_design_day or change_building_location first.",
        }

    work = user_run_root() / f"_ems_discovery_{uuid.uuid4().hex[:8]}"
    try:
        work.mkdir(parents=True, exist_ok=True)
        osm_path = work / "in.osm"
        # Snapshot the session model; all mutations below happen on a fresh copy.
        model.save(str(osm_path), True)
        loaded = openstudio.model.Model.load(str(osm_path))
        if not loaded.is_initialized():
            return {"ok": False, "error": "Failed to reload model snapshot for discovery."}
        copy = loaded.get()

        sim_control = copy.getSimulationControl()
        sim_control.setRunSimulationforSizingPeriods(True)
        sim_control.setRunSimulationforWeatherFileRunPeriods(False)
        output_ems = copy.getOutputEnergyManagementSystem()
        output_ems.setActuatorAvailabilityDictionaryReporting("Verbose")
        output_ems.setInternalVariableAvailabilityDictionaryReporting("Verbose")
        # Discovery must not depend on plugin health — a broken plugin would
        # abort the run before the .edd is complete.
        for instance in copy.getPythonPluginInstances():
            instance.remove()
        copy.save(str(osm_path), True)

        (work / "workflow.osw").write_text(
            json.dumps({"seed_file": "in.osm", "file_paths": [],
                        "measure_paths": [], "steps": []}, indent=2),
            encoding="utf-8",
        )
        cmd = [
            "openstudio",
            "--bundle", OSCLI_GEMFILE,
            "--bundle_path", OSCLI_GEM_PATH,
            "--bundle_without", "native_ext",
            "run", "-w", str(work / "workflow.osw"),
        ]
        env = sandbox.build_env(work)
        sandbox.prepare_workdir(work)
        proc = subprocess.run(  # noqa: S603 - trusted cmd on server-staged files
            sandbox.wrap_cmd(cmd, work),
            cwd=str(work), env=env,
            capture_output=True, text=True,
            timeout=_DISCOVERY_TIMEOUT_SECONDS, check=False,
        )

        edd_path = work / "run" / "eplusout.edd"
        if not edd_path.exists():
            err_path = work / "run" / "eplusout.err"
            tail = (err_path.read_text(errors="replace")[-1500:]
                    if err_path.exists() else (proc.stdout or "")[-1500:])
            return {
                "ok": False,
                "error": "Discovery run produced no eplusout.edd",
                "exit_code": proc.returncode,
                "log_tail": tail,
            }
        parsed = parse_edd(edd_path.read_text(errors="replace"))
    except subprocess.TimeoutExpired:
        return {"ok": False,
                "error": f"Discovery run timed out after {_DISCOVERY_TIMEOUT_SECONDS}s"}
    except Exception as e:
        return {"ok": False, "error": f"Actuator discovery failed: {e}"}
    finally:
        shutil.rmtree(work, ignore_errors=True)

    actuators = [
        a for a in parsed["actuators"]
        if _matches(a["component_type"], component_type)
        and _matches(a["control_type"], control_type)
        and _matches(a["actuator_key"], key)
    ]
    total = len(actuators)
    limit = max_results if max_results and max_results > 0 else total
    result: dict[str, Any] = {
        "ok": True,
        "total_actuators": total,
        "count": min(total, limit),
        "actuators": actuators[:limit],
        "note": "EnergyPlus reports names uppercase; get_actuator_handle "
                "matching in plugins is case-insensitive.",
    }
    if total > limit:
        result["truncated"] = True
    if include_internal_variables:
        internal = [v for v in parsed["internal_variables"]
                    if _matches(v["key"], key) and _matches(v["type"], component_type)]
        result["total_internal_variables"] = len(internal)
        result["internal_variables"] = internal[:limit]
    return result
