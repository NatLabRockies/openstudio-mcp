"""Model management operations — create, load, inspect, convert OSM files."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import openstudio

from mcp_server import model_manager
from mcp_server.config import INPUT_ROOT, RUN_ROOT, is_path_allowed, user_run_root
from mcp_server.skills.model_management.baseline_model import create_baseline_model
from mcp_server.util import reject_escaping_symlinks


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
        model_dir.mkdir(parents=True, exist_ok=True)

        model = openstudio.model.exampleModel()
        ok = model.save(_os_path(osm_path), True)

        if ok is False:
            return {"ok": False, "error": "model.save(...) returned False."}
        if not osm_path.exists():
            return {"ok": False, "error": f"model.save(...) did not create expected file: {osm_path}"}

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

    # Save the model
    try:
        saved_path = model_manager.save_model(p)

        if not p.exists():
            return {"ok": False, "error": f"Save appeared to succeed but file not found: {p}"}

        result: dict[str, Any] = {
            "ok": True,
            "osm_path": str(saved_path),
            "message": f"Model saved successfully to {saved_path}",
        }

        # Carry the model's companion files/ dir (ExternalFile resources, e.g.
        # Python EMS plugin scripts) so a save-as stays runnable from its new
        # location — the OSM stores only bare file names resolved via files/.
        dst_files = p.parent / "files"
        if source_path is not None:
            src_files = source_path.resolve().parent / "files"
            if src_files.is_dir() and src_files != dst_files.resolve():
                # Same guard as run_simulation staging: copytree FOLLOWS
                # symlinks, so a link planted in files/ would copy arbitrary
                # host files into the new location.
                sym_err = reject_escaping_symlinks(src_files)
                if sym_err:
                    return {
                        "ok": False,
                        "error": f"Model saved to {saved_path}, but its files/ "
                                 f"dir was NOT copied: {sym_err}",
                        "osm_path": str(saved_path),
                    }
                shutil.copytree(str(src_files), str(dst_files), dirs_exist_ok=True)
                result["files_dir"] = str(dst_files)

        # Resources the session holds but the model dir does not yet: files a
        # measure generated, or resources created while the model had no file.
        # Persisted on save like the Application copies its document temp dir.
        pending = model_manager.pending_files_dir_if_exists()
        if pending is not None:
            persisted = _persist_pending_files(pending, dst_files)
            if persisted:
                result["files_dir"] = str(dst_files)
                result["persisted_files"] = persisted

        # Application Save As semantics: the saved file becomes the session
        # path, but only once the model and its resources are all there, and
        # only for the model this save was made from.
        if source_path is None or p != source_path.resolve():
            if model_manager.rebind_path(p, generation):
                result["message"] += "; the session now points at this file"

        return result
    except Exception as e:
        return {"ok": False, "error": f"Failed to save model: {e}", "osm_path": str(p)}


def _persist_pending_files(pending: Path, dst_files: Path) -> list[str]:
    """Move the session workspace's files into the saved model's files/ dir.

    Regular files only (a link or dir planted in generated_files is left
    behind); a same-named existing file is replaced, since the generated file
    is the model's newest truth (what the Application's copy-back does).
    """
    names: list[str] = []
    for src in sorted(pending.iterdir()):
        if src.is_symlink() or not src.is_file():
            continue
        dst_files.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst_files / src.name))
        src.unlink()
        names.append(src.name)
    return names


def list_files(
    directory: str | None = None,
    pattern: str = "*",
    max_depth: int = 2,
    max_results: int = 10,
) -> dict[str, Any]:
    """List files in /inputs and /runs only.

    Args:
        directory: Directory to list (must be under /inputs or /runs).
                   If None, scans both /inputs and /runs.
        pattern: Glob pattern to filter files (e.g. "*.osm"). Default "*".
        max_depth: Max directory depth (1 = top-level only). Default 2.
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
        ok = model.save(str(osm_path), True)

        if ok is False:
            return {"ok": False, "error": "model.save() returned False."}
        if not osm_path.exists():
            return {"ok": False, "error": f"model.save() did not create file: {osm_path}"}

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
