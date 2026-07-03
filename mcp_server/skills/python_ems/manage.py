"""Inspect and edit existing Python plugin instances.

Split from operations.py (creation) by responsibility: these ops read/modify
plugins that already exist in the model. The files/ copy created by
ExternalFile is the runtime source of truth, so edit rewrites that copy after
re-validating the source against the instance's class contract.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import openstudio

from mcp_server import model_manager
from mcp_server.skills.python_ems import templates
from mcp_server.skills.python_ems.operations import (
    _MAX_SOURCE_CHARS,
    _EmsError,
    _files_context,
)


def _script_path_for(file_name: str) -> Path | None:
    """The plugin's script copy under the model's files/ dir, or None.

    fileName comes from the OSM, so a crafted model can smuggle path
    separators (or an absolute path) into it — only the basename is honored,
    anchored under files/, and never read through a symlink.
    """
    safe_name = Path(file_name).name
    osm_path = model_manager.get_model_path()
    if not safe_name or osm_path is None:
        return None
    candidate = osm_path.resolve().parent / "files" / safe_name
    if candidate.is_file() and not candidate.is_symlink():
        return candidate
    return None


def _instance_by_name(model, name: str):
    for instance in model.getPythonPluginInstances():
        if instance.nameString().lower() == (name or "").strip().lower():
            return instance
    available = [i.nameString() for i in model.getPythonPluginInstances()]
    raise _EmsError(f"Python plugin '{name}' not found. Available: {available}")


def get_python_plugin_op(name: str | None = None) -> dict[str, Any]:
    """List Python plugin instances (no name) or detail one incl. script source."""
    try:
        model = model_manager.get_model_if_loaded()
        if model is None:
            raise _EmsError("No model loaded. Call load_osm_model first.")

        instances: list[dict[str, Any]] = []
        for instance in model.getPythonPluginInstances():
            file_name = instance.externalFile().fileName()
            script = _script_path_for(file_name)
            instances.append({
                "name": instance.nameString(),
                "class_name": instance.pluginClassName(),
                "module_name": Path(file_name).stem,
                "script_path": str(script) if script else None,
                "run_during_warmup": bool(instance.runDuringWarmupDays()),
            })

        globals_declared = [v.nameString() for v in model.getPythonPluginVariables()]
        output_variables = []
        for plugin_output in model.getPythonPluginOutputVariables():
            units_opt = plugin_output.units()
            output_variables.append({
                "name": plugin_output.nameString(),
                "global": plugin_output.pythonPluginVariable().nameString(),
                "type_of_data": plugin_output.typeofDatainVariable(),
                "update_frequency": plugin_output.updateFrequency(),
                "units": units_opt.get() if units_opt.is_initialized() else "",
            })
        trend_variables = [
            {"name": trend.nameString(),
             "global": trend.pythonPluginVariable().nameString(),
             "timesteps_logged": trend.numberofTimestepstobeLogged()}
            for trend in model.getPythonPluginTrendVariables()
        ]
        search_paths = [
            openstudio.toString(p)
            for p in model.getPythonPluginSearchPaths().searchPaths()
        ]

        result: dict[str, Any] = {
            "ok": True,
            "count": len(instances),
            "plugins": instances,
            "global_variables": globals_declared,
            "output_variables": output_variables,
            "trend_variables": trend_variables,
            "search_paths": search_paths,
        }

        if name:
            match = next(
                (i for i in instances if i["name"].lower() == name.strip().lower()), None)
            if match is None:
                available = [i["name"] for i in instances]
                return {"ok": False,
                        "error": f"Python plugin '{name}' not found. Available: {available}"}
            result["plugin"] = match
            if match["script_path"]:
                source = Path(match["script_path"]).read_text(
                    encoding="utf-8", errors="replace")
                if len(source) > _MAX_SOURCE_CHARS:
                    source = source[:_MAX_SOURCE_CHARS] + "\n# ... truncated ..."
                result["source"] = source
            else:
                result["source"] = None
        return result
    except _EmsError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"get_python_plugin failed: {e}"}


def edit_python_plugin_op(name: str, code: str) -> dict[str, Any]:
    """Replace a plugin's script source; validation failure leaves it untouched."""
    try:
        model, _osm_dir, files_dir = _files_context()
        instance = _instance_by_name(model, name)
        plugin_class = instance.pluginClassName()

        if not code or not code.strip():
            raise _EmsError("code is required")
        if len(code) > _MAX_SOURCE_CHARS:
            raise _EmsError(
                f"code is {len(code)} chars — max {_MAX_SOURCE_CHARS}. "
                "Trim comments or split the logic across plugins.")
        validation = templates.validate_plugin_source(code, plugin_class)
        if not validation["ok"]:
            return {
                "ok": False,
                "error": f"Plugin source failed validation (class '{plugin_class}' "
                         "must keep its name — the instance references it)",
                "details": validation["errors"],
            }

        # fileName comes from the OSM: honor only its basename so a crafted
        # value ("../x.py", absolute path) can never write outside files/.
        file_name = Path(instance.externalFile().fileName()).name
        script_path = files_dir / file_name
        if not file_name or not script_path.exists():
            raise _EmsError(
                f"Plugin script not found at {script_path} — the model's files/ "
                "dir is missing. save_osm_model, then retry.")
        if script_path.is_symlink():
            raise _EmsError(
                f"Plugin script {script_path} is a symlink — refusing to "
                "write through it.")
        script_path.write_text(code, encoding="utf-8")

        return {
            "ok": True,
            "plugin_instance": instance.nameString(),
            "class_name": plugin_class,
            "script_path": str(script_path),
            "callbacks": validation["callbacks"],
            "message": "Script updated. save_osm_model + run_simulation to apply.",
        }
    except _EmsError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"edit_python_plugin failed: {e}"}
