"""Model management operations — create, load, inspect, convert OSM files."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import openstudio

from mcp_server import model_manager
from mcp_server.config import INPUT_ROOT, RUN_ROOT, is_path_allowed, user_run_root
from mcp_server.model_save import save_model_confined
from mcp_server.resources import (
    companion_files_dir,
    copy_resources,
    legacy_files_dir,
    legacy_migrated,
    mark_legacy_migrated,
    resource_dir_issue,
    resource_sources,
)
from mcp_server.skills.model_management.baseline_model import create_baseline_model
from mcp_server.workspace_files import persist_pending_files


def _safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in (s or "")).strip("_") or "example_model"


def _os_path(p: Path):
    """Return an OpenStudio Path object for a filesystem Path."""
    return openstudio.path(str(p))


def create_example_osm(name: str | None = None, out_dir: str | None = None) -> dict[str, Any]:
    """Create the built-in OpenStudio example model and save it as an OSM."""
    safe = _safe_name(name or "example_model")
    base_dir = Path(out_dir) if out_dir else (user_run_root() / "examples")
    base_dir = base_dir.resolve()

    if not is_path_allowed(base_dir, write=True):
        return {"ok": False, "error": f"Output directory is not allowed: {base_dir}"}

    model_dir = (base_dir / safe).resolve()
    if not is_path_allowed(model_dir, write=True):
        return {"ok": False, "error": f"Output directory is not allowed after resolution: {model_dir}"}

    osm_path = model_dir / "example_model.osm"

    try:
        model = openstudio.model.exampleModel()
        try:
            save_model_confined(model, osm_path)  # staged, then copied by descriptor (#190)
        except (OSError, ValueError, RuntimeError) as e:
            return {"ok": False, "error": f"Could not save the example model to {osm_path}: {e}"}

        # Auto-load so query tools work immediately
        model_manager.load_model(osm_path)

        return {
            "ok": True,
            "osm_path": str(osm_path),
            "out_dir": str(model_dir),
            "name": safe,
            "model_loaded": True,
            "openstudio_version": str(openstudio.openStudioVersion()),
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to create/save example model: {e}", "osm_path": str(osm_path)}


def _vector_size(v) -> int:
    """Return size of an OpenStudio Vector-like container."""
    try:
        return int(v.size())
    except Exception:
        return len(v)


def inspect_osm_summary(osm_path: str) -> dict[str, Any]:
    """Load an OSM and return a simple summary (spaces, zones, space types, floor area)."""
    p = Path(osm_path)

    if not is_path_allowed(p.resolve()):
        return {"ok": False, "error": f"OSM path is not allowed: {p}"}

    if not p.exists():
        return {"ok": False, "error": f"OSM not found: {p}", "osm_path": str(p)}

    try:
        vt = openstudio.osversion.VersionTranslator()
        loaded = vt.loadModel(_os_path(p))

        if not loaded.is_initialized():
            return {"ok": False, "error": f"Failed to load OSM: {p}", "osm_path": str(p)}

        model = loaded.get()
        building = model.getBuilding()
        try:
            building_name = building.nameString()
        except Exception:
            building_name = str(building.name())

        spaces = model.getSpaces()
        zones = model.getThermalZones()
        sts = model.getSpaceTypes()

        floor_area_m2 = 0.0
        try:
            for sp in spaces:
                try:
                    floor_area_m2 += float(sp.floorArea())
                except Exception:
                    pass
        except Exception:
            floor_area_m2 = 0.0

        space_type_names: list[str] = []
        try:
            for st in sts:
                try:
                    space_type_names.append(st.nameString())
                except Exception:
                    space_type_names.append(str(st.name()))
        except Exception:
            space_type_names = []

        return {
            "ok": True,
            "osm_path": str(p),
            "building_name": building_name,
            "spaces": _vector_size(spaces),
            "thermal_zones": _vector_size(zones),
            "space_types_count": _vector_size(sts),
            "space_types": space_type_names,
            "floor_area_m2": floor_area_m2,
            "openstudio_version": str(openstudio.openStudioVersion()),
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to inspect OSM: {e}", "osm_path": str(p)}


def load_osm_model(osm_path: str, version_translate: bool = True) -> dict[str, Any]:
    """Load an OSM file and set it as the current model for query tools.

    Args:
        osm_path: Path to the OSM file to load
        version_translate: Whether to use VersionTranslator (default True)

    Returns:
        Dict with ok=True and model summary on success, ok=False with error on failure
    """
    p = Path(osm_path).resolve()

    if not is_path_allowed(p):
        return {"ok": False, "error": f"OSM path is not allowed: {p}"}

    if not p.exists():
        return {"ok": False, "error": f"OSM file not found: {p}"}

    try:
        model = model_manager.load_model(p, version_translate=version_translate)

        # Get basic info about loaded model
        building = model.getBuilding()
        try:
            building_name = building.nameString()
        except Exception:
            building_name = str(building.name())

        spaces = model.getSpaces()
        zones = model.getThermalZones()

        return {
            "ok": True,
            "osm_path": str(p),
            "building_name": building_name,
            "spaces": _vector_size(spaces),
            "thermal_zones": _vector_size(zones),
            "openstudio_version": str(openstudio.openStudioVersion()),
            "message": f"Model loaded successfully: {building_name}",
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to load OSM: {e}", "osm_path": str(p)}


def _resolve_save_name(save_name: str) -> Path | None:
    """Server-resolved save-as target for a bare name, or None if invalid.

    Accepts a basename only (no separators, drives, traversal, or hidden
    names), normalizes the .osm suffix, and resolves under the caller's
    private run root — no user key or writable-root knowledge is client input.
    """
    if (
        not save_name
        or any(c in save_name for c in "/\\:")
        or save_name in (".", "..")
        or save_name.startswith(".")
        or Path(save_name).name != save_name
    ):
        return None
    name = save_name if save_name.endswith(".osm") else f"{save_name}.osm"
    return (user_run_root() / "models" / name).resolve()


def save_osm_model(
    osm_path: str | None = None,
    save_name: str | None = None,
) -> dict[str, Any]:
    """Save the currently loaded model to disk.

    Args:
        osm_path: Optional explicit path to save to. If None, saves to the
            original load path.
        save_name: Optional bare name — the server resolves the path inside
            the caller's private run area (client-neutral save-as).

    Returns:
        Dict with ok=True and saved path on success, ok=False with error on failure
    """
    # Check if a model is loaded. The generation pins the save-as rebind below
    # to this model; the source path is read before the save so the companion
    # files/ copy still knows where the model came from after the rebind.
    try:
        _model, generation = model_manager.get_model_with_generation()
    except RuntimeError:
        return {"ok": False, "error": "No model loaded. Call load_osm_model first."}
    source_path = model_manager.get_model_path()

    if osm_path is not None and save_name is not None:
        return {
            "ok": False,
            "error": "Pass either osm_path or save_name, not both.",
        }

    # Determine save path
    if save_name is not None:
        p = _resolve_save_name(save_name)
        if p is None:
            return {
                "ok": False,
                "error": (
                    f"Invalid save_name '{save_name}': must be a bare file "
                    "name (no separators, drives, or leading dots); "
                    ".osm is appended automatically."
                ),
            }
    elif osm_path is not None:
        p = Path(osm_path).resolve()
    else:
        if source_path is None:
            return {
                "ok": False,
                "error": "No save destination: this model has no file yet. Pass "
                         "save_name=<name> to save into your run area (or osm_path).",
            }
        p = source_path.resolve()

    # Validate path
    if not is_path_allowed(p, write=True):
        return {
            "ok": False,
            "error": f"Save path is not allowed: {p}. "
                     "Pass save_name=<name> to save into your run area.",
        }

    # Ensure parent directory exists
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"ok": False, "error": f"Failed to create parent directory: {e}"}

    # Save the model. The session io lock serializes this with apply_measure's
    # adoption of generated files, so the workspace is never carried away while
    # it is still being filled, nor persisted twice by concurrent saves.
    try:
        with model_manager.session_io_lock():
            saved_path = model_manager.save_model(p)

            if not p.exists():
                return {"ok": False, "error": f"Save appeared to succeed but file not found: {p}"}

            result: dict[str, Any] = {
                "ok": True,
                "osm_path": str(saved_path),
                "message": f"Model saved successfully to {saved_path}",
            }

            # Resources go with the model into its companion folder
            # (<model>/files/, the Application's layout). Newest first: what
            # the session holds but no dir has yet (files a measure generated,
            # resources created while the model had no file), then the source
            # model's own companion folder (save-as), then a legacy sibling
            # files/ from before the companion folder (migrated forward, never
            # overwriting). Both ends are tenant-writable, so every dir is
            # checked for links before anything is read or written.
            dst_files = companion_files_dir(p)
            issue = resource_dir_issue(dst_files, write=True)
            if issue:
                return {
                    "ok": False,
                    "error": f"Model saved to {saved_path}, but its companion folder cannot be "
                             f"used ({issue}); resources were NOT written",
                    "osm_path": str(saved_path),
                }
            try:
                sources = [] if source_path is None else resource_sources(source_path)
            except ValueError as e:
                return {
                    "ok": False,
                    "error": f"Model saved to {saved_path}, but its resources were NOT carried: {e}",
                    "osm_path": str(saved_path),
                }
            # 1. The source model's resources. A save-as replaces what an older
            #    model at the destination left there (the OSM is now this
            #    model, so its resources must be too); a bare save never
            #    overwrites the companion folder with the legacy copy.
            save_as = source_path is None or p != source_path.resolve()
            try:
                carried = copy_resources(sources, dst_files, overwrite=save_as)
            except ValueError as e:
                return {
                    "ok": False,
                    "error": f"Model saved to {saved_path}, but its resources were NOT carried: {e}",
                    "osm_path": str(saved_path),
                }
            legacy = None if source_path is None else legacy_files_dir(source_path)
            consulted_legacy = legacy is not None and legacy in sources
            migrated = [name for name, index in carried["copied"] if consulted_legacy and sources[index] == legacy]
            if migrated:
                result["migrated_files"] = migrated
                result["message"] += (
                    f"; {len(migrated)} resource file(s) copied from the older sibling files/ "
                    "dir into the model's companion folder"
                )
            failed_regular = [(name, why) for name, why in carried["skipped"] if why != "not a regular file"]
            source_migrated = source_path is not None and legacy_migrated(source_path)
            if (consulted_legacy or source_migrated) and not failed_regular:
                # Complete: from now on the companion folder is the whole truth.
                # A save-as carries that state, otherwise the copy would start
                # consulting the source's legacy dir again.
                try:
                    mark_legacy_migrated(p)
                except ValueError as e:
                    return {
                        "ok": False,
                        "error": f"Model saved to {saved_path}, resources written, but the migration "
                                 f"marker could not be written: {e}",
                        "osm_path": str(saved_path),
                    }
            if carried["replaced"]:
                result["replaced_files"] = list(carried["replaced"])
            if carried["skipped"]:
                result["skipped_files"] = [f"{name} ({why})" for name, why in carried["skipped"]]
            # 2. Last, so it wins: what the session holds but no dir has yet.
            #    Pinned to this save's generation: a workspace that now belongs
            #    to a model loaded meanwhile is left alone.
            pending = model_manager.pending_files_dir_if_exists(expected_generation=generation)
            if pending is not None:
                persisted, replaced, skipped = persist_pending_files(pending, dst_files)
                if persisted:
                    result["persisted_files"] = persisted
                if replaced:
                    result.setdefault("replaced_files", []).extend(
                        name for name in replaced if name not in result.get("replaced_files", [])
                    )
                if skipped:
                    result.setdefault("skipped_files", []).extend(skipped)
            if dst_files.is_dir():
                result["files_dir"] = str(dst_files)

            # Application Save As semantics: the saved file becomes the session
            # path, but only once the model and its resources are all there, and
            # only for the model this save was made from.
            if (source_path is None or p != source_path.resolve()) and model_manager.rebind_path(p, generation):
                result["message"] += "; the session now points at this file"

            return result
    except Exception as e:
        return {"ok": False, "error": f"Failed to save model: {e}", "osm_path": str(p)}


def list_files(
    directory: str | None = None,
    pattern: str = "*",
    max_depth: int = 3,
    max_results: int = 10,
) -> dict[str, Any]:
    """List files in /inputs and /runs only.

    Args:
        directory: Directory to list (must be under /inputs or /runs).
                   If None, scans both /inputs and /runs.
        pattern: Glob pattern to filter files (e.g. "*.osm"). Default "*".
        max_depth: Max directory depth (1 = top-level only). Default 3, which
            reaches a model's resources at <dir>/<model>/files/.
        max_results: Max items to return (default 10, None = unlimited).

    Returns:
        Dict with ok=True, count, and file list.
    """
    import fnmatch

    _allowed_roots = [INPUT_ROOT, user_run_root()]

    # Determine which directories to scan
    if directory:
        d = Path(directory).resolve()
        # A bare "/runs" request means the caller's own run area (per-user scoping)
        if d == RUN_ROOT:
            d = user_run_root()
        # Restrict to /inputs and /runs only
        if not any(str(d).startswith(str(root)) or d == root for root in _allowed_roots):
            return {"ok": False, "error": f"Directory not allowed: {d}. list_files is restricted to /inputs and /runs."}
        scan_dirs = [d]
    else:
        scan_dirs = _allowed_roots

    items: list[dict[str, Any]] = []
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for root, dirs, filenames in os.walk(scan_dir):
            root_path = Path(root)
            try:
                depth = len(root_path.resolve().relative_to(scan_dir.resolve()).parts)
            except ValueError:
                depth = 0

            # Enforce max_depth
            if depth >= max_depth:
                dirs.clear()
                if depth > max_depth:
                    continue

            # Add files only (no directories)
            for fname in filenames:
                if pattern != "*" and not fnmatch.fnmatch(fname, pattern):
                    continue
                items.append({
                    "name": fname,
                    "path": str(root_path / fname),
                    "type": "file",
                })
                # Early exit once max_results collected
                if max_results is not None and len(items) >= max_results:
                    break
            if max_results is not None and len(items) >= max_results:
                break
        if max_results is not None and len(items) >= max_results:
            break

    items.sort(key=lambda f: f["name"])
    total = len(items)
    resp: dict[str, Any] = {"ok": True}
    if max_results is not None and total > max_results:
        items = items[:max_results]
        resp["truncated"] = True
    resp["count"] = len(items)
    resp["items"] = items
    return resp


def create_baseline_osm(
    name: str | None = None,
    out_dir: str | None = None,
    num_floors: int = 2,
    floor_to_floor_height: float = 4.0,
    perimeter_zone_depth: float = 3.0,
    ashrae_sys_num: str | None = None,
    wwr: float | None = None,
) -> dict[str, Any]:
    """Create a baseline 10-zone commercial building model and save as OSM."""
    safe = _safe_name(name or "baseline_model")
    base_dir = Path(out_dir) if out_dir else (user_run_root() / "examples")
    base_dir = base_dir.resolve()

    if not is_path_allowed(base_dir, write=True):
        return {"ok": False, "error": f"Output directory not allowed: {base_dir}"}

    model_dir = (base_dir / safe).resolve()
    if not is_path_allowed(model_dir, write=True):
        return {"ok": False, "error": f"Output directory not allowed: {model_dir}"}

    osm_path = model_dir / "baseline_model.osm"

    try:
        model_dir.mkdir(parents=True, exist_ok=True)

        model, info = create_baseline_model(
            name=safe,
            num_floors=num_floors,
            floor_to_floor_height=floor_to_floor_height,
            perimeter_zone_depth=perimeter_zone_depth,
            ashrae_sys_num=ashrae_sys_num,
            wwr=wwr,
        )
        try:
            save_model_confined(model, osm_path)  # staged, then copied by descriptor (#190)
        except (OSError, ValueError, RuntimeError) as e:
            return {"ok": False, "error": f"Could not save the baseline model to {osm_path}: {e}"}

        # Auto-load so query tools work immediately
        model_manager.load_model(osm_path)

        return {
            "ok": True,
            "osm_path": str(osm_path),
            "out_dir": str(model_dir),
            "name": safe,
            "model_loaded": True,
            **info,
            "openstudio_version": str(openstudio.openStudioVersion()),
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to create baseline model: {e}", "osm_path": str(osm_path)}
