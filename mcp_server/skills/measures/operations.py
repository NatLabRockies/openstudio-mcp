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

from mcp_server.model_manager import get_model, load_model
from mcp_server.stdout_suppression import suppress_openstudio_warnings


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
        with suppress_openstudio_warnings():
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


def apply_measure(
    measure_dir: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply an OpenStudio model measure to the in-memory model.

    Uses the OSW runner approach:
    1. Save current model to a temp OSM
    2. Copy measure into run dir
    3. Build a minimal OSW with the measure step
    4. Run `openstudio run -w temp.osw`
    5. Reload the resulting model

    Args:
        measure_dir: Path to the measure directory
        arguments: Optional dict of argument_name -> value overrides
    """
    try:
        model = get_model()
        measure_path = Path(measure_dir)
        if not measure_path.is_dir():
            return {"ok": False, "error": f"Measure directory not found: {measure_dir}"}

        # Check measure.rb exists
        measure_rb = measure_path / "measure.rb"
        if not measure_rb.is_file():
            return {"ok": False, "error": f"No measure.rb found in {measure_dir}"}

        # Create temp directory for the run
        run_id = uuid.uuid4().hex[:12]
        runs_dir = Path(os.environ.get("MCP_RUNS_DIR", "/runs"))
        run_dir = runs_dir / f"measure_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Save current model to temp OSM
        temp_osm = run_dir / "in.osm"
        with suppress_openstudio_warnings():
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
        with suppress_openstudio_warnings():
            epw_file = model.weatherFile()
            if epw_file.is_initialized():
                epw_path = epw_file.get().path()
                if epw_path.is_initialized():
                    epw_str = str(epw_path.get())
                    epw_resolved = Path(epw_str)
                    if epw_resolved.is_file():
                        file_paths.append(str(epw_resolved.parent))

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
        osw_path = run_dir / "workflow.osw"
        osw_path.write_text(json.dumps(osw, indent=2), encoding="utf-8")

        # Run openstudio
        cmd = ["openstudio", "run", "--measures_only", "-w", str(osw_path)]
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

        # Find the output model — OpenStudio puts it in run/in.osm
        output_osm = run_dir / "run" / "in.osm"
        if not output_osm.is_file():
            # Try the original location
            output_osm = temp_osm
        if not output_osm.is_file():
            return {"ok": False, "error": "Output OSM not found after measure run"}

        # Reload model
        with suppress_openstudio_warnings():
            load_model(output_osm)

        return {
            "ok": True,
            "measure_dir": str(measure_path),
            "run_dir": str(run_dir),
            "arguments_applied": measure_args,
        }

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Measure run timed out (5 min)"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to apply measure: {e}"}
