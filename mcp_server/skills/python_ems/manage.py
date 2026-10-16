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
from mcp_server.resources import find_resource
from mcp_server.skills.python_ems import templates
from mcp_server.skills.python_ems.operations import (
    _MAX_SOURCE_CHARS,
    _EmsError,
    _files_context,
)
from mcp_server.util import open_nofollow_for_write, read_file_bounded

_MAX_SOURCE_BYTES = 8 * 1024 * 1024  # a plugin script returned to the caller


def _script_path_for(file_name: str) -> Path | None:
    """The plugin's script copy under the model's files/ dir, or None.

    fileName comes from the OSM, so a crafted model can smuggle path
    separators (or an absolute path) into it — only the basename is honored,
    anchored under files/, and never read through a symlink.
    """
    safe_name = Path(file_name).name
    if not safe_name:
        return None
    # Newest first: a pending file a measure just generated, then the model's
    # companion folder, then a legacy sibling files/ (the same precedence the
    # measure run uses when it stages resources).
    pending = model_manager.pending_files_dir_if_exists()
    try:
        return find_resource(
            model_manager.get_model_path(), safe_name,
            first=[pending] if pending is not None else [],
        )
    except ValueError:
        return None  # a planted link at a resource dir is not read around


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
                # Under the model's companion folder, a tenant-writable tree: read by descriptor (#190)
                try:
                    source = read_file_bounded(Path(match["script_path"]), _MAX_SOURCE_BYTES).decode(
                        "utf-8", errors="replace")
                except ValueError as e:
                    raise _EmsError(f"Plugin script could not be read: {e}") from None
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
        existing = _script_path_for(file_name) if file_name else None
        if existing is None:
            raise _EmsError(
                f"Plugin script '{file_name}' not found in the model's resources "
                "(companion folder files/, or the session's pending files). "
                "save_osm_model, then retry.")
        # The edit goes to the model's own resources dir (companion folder, or
        # the pending workspace for a model with no file yet). A pending copy
        # a measure generated is superseded and dropped; a legacy sibling
        # copy is left behind, the companion copy now wins by precedence.
        script_path = files_dir / file_name
        if script_path.is_symlink():
            raise _EmsError(
                f"Plugin script {script_path} is a symlink — refusing to "
                "write through it.")
        files_dir.mkdir(parents=True, exist_ok=True)
        with open_nofollow_for_write(script_path) as fh:
            fh.write(code)
        pending = model_manager.pending_files_dir_if_exists()
        if existing != script_path and pending is not None and existing.parent == pending:
            existing.unlink(missing_ok=True)

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
