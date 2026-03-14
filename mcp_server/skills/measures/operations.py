"""Measure operations — list arguments and apply measures.

Uses the OSW-based approach: save model → build OSW with measure step →
run `openstudio run -w` → reload resulting model. This avoids Ruby script
execution complexity and uses the well-tested OSW runner.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.config import OSCLI_GEM_PATH, OSCLI_GEMFILE, RUN_ROOT
from mcp_server.model_manager import get_model, load_model
from mcp_server.util import resolve_run_dir


def list_measure_arguments(measure_dir: str) -> dict[str, Any]:
    """List a measure's arguments with names, types, defaults, and choices.

    Args:
        measure_dir: Path to the measure directory (contains measure.rb)
    """
    try:
        measure_path = Path(measure_dir)
        if not measure_path.is_dir():
            return {"ok": False, "error": f"Measure directory not found: {measure_dir}"}

        # Load BCLMeasure to read metadata
        bcl = openstudio.BCLMeasure(openstudio.toPath(str(measure_path)))

        # Extract arguments from the measure XML
        args = []
        for arg in bcl.arguments():
            arg_info: dict[str, Any] = {
                "name": arg.name(),
                "display_name": arg.displayName(),
            }
            # type() may return string or enum depending on OS version
            try:
                arg_info["type"] = arg.type()
            except Exception:
                pass
            # Default value — attribute name varies by OS version
            try:
                dv = arg.defaultValue()
                if dv is not None:
                    arg_info["default_value"] = str(dv)
            except Exception:
                pass
            # Required
            try:
                arg_info["required"] = arg.required()
            except Exception:
                pass
            # Choice values
            try:
                choices = arg.choiceValues()
                if choices:
                    arg_info["choices"] = [str(c) for c in choices]
            except Exception:
                pass

            args.append(arg_info)

        return {
            "ok": True,
            "measure_name": bcl.name(),
            "measure_type": bcl.measureType().valueName(),
            "description": bcl.description(),
            "arguments": args,
        }

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list measure arguments: {e}"}


def _parse_runner_messages(out_osw_path: Path) -> dict[str, Any] | None:
    """Extract runner messages from out.osw step results.

    Returns dict with result, initial_condition, final_condition,
    info, warnings, errors — or None on parse failure.
    """
    try:
        if not out_osw_path.is_file():
            return None
        osw = json.loads(out_osw_path.read_text(encoding="utf-8", errors="replace"))
        steps = osw.get("steps", [])
        if not steps:
            return None
        step = steps[0]
        result = step.get("result", {})
        msgs: dict[str, Any] = {
            "result": result.get("step_result", ""),
        }
        for key in ("step_initial_condition", "step_final_condition"):
            val = result.get(key)
            if val:
                # Strip "step_" prefix for cleaner output
                msgs[key.replace("step_", "")] = val
        for key, osw_key in [("info", "step_info"), ("warnings", "step_warnings"), ("errors", "step_errors")]:
            items = result.get(osw_key, [])
            if items:
                msgs[key] = items
        return msgs
    except Exception:
        return None


def apply_measure(
    measure_dir: str,
    arguments: dict[str, Any] | None = None,
    run_id: str | None = None,
    use_bundle: bool = True,
) -> dict[str, Any]:
    """Apply an OpenStudio measure to the in-memory model.

    For ModelMeasures (default): saves model → builds OSW → runs
    `openstudio run --measures_only` → reloads model.

    For ReportingMeasures (when run_id provided): copies simulation
    artifacts (SQL, IDF) from a completed run into the measure dir,
    then runs `openstudio run --postprocess_only` so only reporting
    measures execute against the existing results.

    Args:
        measure_dir: Path to the measure directory
        arguments: Optional dict of argument_name -> value overrides
        run_id: Optional completed simulation run_id (for reporting measures)
    """
    try:
        model = get_model()
        measure_path = Path(measure_dir)
        if not measure_path.is_dir():
            return {"ok": False, "error": f"Measure directory not found: {measure_dir}"}

        # Check measure script exists (Ruby or Python)
        has_rb = (measure_path / "measure.rb").is_file()
        has_py = (measure_path / "measure.py").is_file()
        if not has_rb and not has_py:
            return {"ok": False, "error": f"No measure.rb or measure.py found in {measure_dir}"}

        # Create temp directory for the run
        measure_run_id = uuid.uuid4().hex[:12]
        runs_dir = Path(os.environ.get("MCP_RUNS_DIR", "/runs"))
        run_dir = runs_dir / f"measure_{measure_run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save current model to temp OSM
        temp_osm = run_dir / "in.osm"
        model.save(str(temp_osm), True)

        # Copy measure into run dir so OSW can reference it by relative path
        measures_dir = run_dir / "measures"
        measures_dir.mkdir(exist_ok=True)
        local_measure = measures_dir / measure_path.name
        shutil.copytree(str(measure_path), str(local_measure), dirs_exist_ok=True)

        # Build measure step arguments
        measure_args = {}
        if arguments:
            measure_args = {k: str(v) for k, v in arguments.items()}

        # Collect file_paths for the OSW — include weather file directory
        # so the runner can find EPW files referenced by the model
        file_paths = []
        epw_file = model.weatherFile()
        if epw_file.is_initialized():
            epw_path = epw_file.get().path()
            if epw_path.is_initialized():
                epw_str = str(epw_path.get())
                epw_resolved = Path(epw_str)
                if epw_resolved.is_file():
                    file_paths.append(str(epw_resolved.parent))

        # Also add directories of any EPW paths passed as arguments
        # (e.g. ChangeBuildingLocation's weather_file_name argument).
        # Set weather_file in OSW so the runner can resolve the model's
        # weather reference even if the original EPW path is stale.
        osw_weather_file = None
        if arguments:
            for v in arguments.values():
                v_str = str(v)
                if v_str.endswith(".epw") and Path(v_str).is_file():
                    parent = str(Path(v_str).parent)
                    if parent not in file_paths:
                        file_paths.append(parent)
                    osw_weather_file = v_str

        # Build minimal OSW — use relative path to local copy
        osw = {
            "seed_file": str(temp_osm),
            "file_paths": file_paths,
            "measure_paths": [str(measures_dir)],
            "steps": [
                {
                    "measure_dir_name": measure_path.name,
                    "arguments": measure_args,
                },
            ],
        }
        # If an EPW was found in arguments, set it in the OSW so the runner
        # doesn't fail trying to resolve a stale weather reference from the model
        if osw_weather_file:
            osw["weather_file"] = osw_weather_file

        osw_path = run_dir / "workflow.osw"
        osw_path.write_text(json.dumps(osw, indent=2), encoding="utf-8")

        # Determine run mode: --postprocess_only for reporting measures,
        # --measures_only for model/energyplus measures
        postprocess = False
        if run_id:
            try:
                sim_dir = resolve_run_dir(RUN_ROOT, run_id)
            except FileNotFoundError:
                return {"ok": False, "error": f"Simulation run not found: {run_id}"}
            sql_src = sim_dir / "run" / "eplusout.sql"
            if not sql_src.is_file():
                return {"ok": False, "error": f"No eplusout.sql in run {run_id} — simulation may not have completed"}
            # Stage simulation artifacts so the reporting measure can find them.
            # The OSW runner expects run/eplusout.sql, run/in.osm, run/in.idf
            ep_run = run_dir / "run"
            ep_run.mkdir(exist_ok=True)
            shutil.copy2(str(sql_src), str(ep_run / "eplusout.sql"))
            osm_src = sim_dir / "run" / "in.osm"
            if osm_src.is_file():
                shutil.copy2(str(osm_src), str(ep_run / "in.osm"))
            idf_src = sim_dir / "run" / "in.idf"
            if idf_src.is_file():
                shutil.copy2(str(idf_src), str(ep_run / "in.idf"))
            postprocess = True

        run_flag = "--postprocess_only" if postprocess else "--measures_only"
        cmd = ["openstudio"]
        if use_bundle:
            cmd += ["--bundle", OSCLI_GEMFILE,
                    "--bundle_path", OSCLI_GEM_PATH,
                    "--bundle_without", "native_ext"]
        cmd += ["run", run_flag, "-w", str(osw_path)]
        log_path = run_dir / "openstudio.log"
        with open(log_path, "w", encoding="utf-8") as log_f:
            proc = subprocess.run(
                cmd,
                cwd=str(run_dir),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                env=os.environ.copy(),
                timeout=300,  # 5 minute timeout
                check=False,
            )

        if proc.returncode != 0:
            # Read last 50 lines of log for error details
            log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(log_lines[-50:])
            return {
                "ok": False,
                "error": f"Measure run failed (exit code {proc.returncode})",
                "log_tail": tail,
            }

        # Parse runner messages from out.osw
        runner_messages = _parse_runner_messages(run_dir / "out.osw")

        # For reporting measures, don't reload model — just return artifacts
        if postprocess:
            result = {
                "ok": True,
                "measure_dir": str(measure_path),
                "run_dir": str(run_dir),
                "arguments_applied": measure_args,
            }
            if runner_messages:
                result["runner_messages"] = runner_messages
            return result

        # Find the output model — OpenStudio puts it in run/in.osm
        output_osm = run_dir / "run" / "in.osm"
        if not output_osm.is_file():
            # Try the original location
            output_osm = temp_osm
        if not output_osm.is_file():
            return {"ok": False, "error": "Output OSM not found after measure run"}

        # Reload model
        load_model(output_osm)

        result = {
            "ok": True,
            "measure_dir": str(measure_path),
            "run_dir": str(run_dir),
            "arguments_applied": measure_args,
        }
        if runner_messages:
            result["runner_messages"] = runner_messages
        return result

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Measure run timed out (5 min)"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to apply measure: {e}"}
