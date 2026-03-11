"""Model management operations — create, load, inspect, convert OSM files."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import openstudio

from mcp_server import model_manager
from mcp_server.config import INPUT_ROOT, RUN_ROOT, is_path_allowed
from mcp_server.skills.model_management.baseline_model import create_baseline_model
from mcp_server.stdout_suppression import suppress_openstudio_warnings


def _safe_name(s: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in (s or "")).strip("_") or "example_model"


def _os_path(p: Path):
    """Return an OpenStudio Path object for a filesystem Path."""
    return openstudio.path(str(p))


def create_example_osm(name: str | None = None, out_dir: str | None = None) -> dict[str, Any]:
    """Create the built-in OpenStudio example model and save it as an OSM."""
    safe = _safe_name(name or "example_model")
    base_dir = Path(out_dir) if out_dir else (RUN_ROOT / "examples")
    base_dir = base_dir.resolve()

    if not is_path_allowed(base_dir):
        return {"ok": False, "error": f"Output directory is not allowed: {base_dir}"}

    model_dir = (base_dir / safe).resolve()
    if not is_path_allowed(model_dir):
        return {"ok": False, "error": f"Output directory is not allowed after resolution: {model_dir}"}

    osm_path = model_dir / "example_model.osm"

    try:
        model_dir.mkdir(parents=True, exist_ok=True)

        with suppress_openstudio_warnings():
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
        with suppress_openstudio_warnings():
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


def save_osm_model(osm_path: str | None = None) -> dict[str, Any]:
    """Save the currently loaded model to disk.

    Args:
        osm_path: Optional path to save to. If None, saves to the original load path.

    Returns:
        Dict with ok=True and saved path on success, ok=False with error on failure
    """
    # Check if a model is loaded
    current_model = model_manager.get_model_if_loaded()
    if current_model is None:
        return {"ok": False, "error": "No model loaded. Call load_osm_model first."}

    # Determine save path
    if osm_path is not None:
        p = Path(osm_path).resolve()
    else:
        current_path = model_manager.get_model_path()
        if current_path is None:
            return {"ok": False, "error": "No save path specified and no original path available."}
        p = current_path.resolve()

    # Validate path
    if not is_path_allowed(p):
        return {"ok": False, "error": f"Save path is not allowed: {p}"}

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

        return {
            "ok": True,
            "osm_path": str(saved_path),
            "message": f"Model saved successfully to {saved_path}",
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to save model: {e}", "osm_path": str(p)}


def list_files(
    directory: str | None = None,
    pattern: str = "*",
    max_depth: int | None = None,
) -> dict[str, Any]:
    """List files and directories in mounted directories.

    Do not call list_files more than once for the same directory.

    Args:
        directory: Specific directory to list. If None, scans both /inputs and /runs.
        pattern: Glob pattern to filter files (e.g. "*.epw", "*.osm"). Default "*".
        max_depth: Max directory depth (1 = top-level only, None = unlimited).

    Returns:
        Dict with ok=True, total count, and file/directory list.
    """
    import fnmatch

    # Determine which directories to scan
    if directory:
        scan_dirs = [Path(directory).resolve()]
        for d in scan_dirs:
            if not is_path_allowed(d):
                return {"ok": False, "error": f"Directory not allowed: {d}"}
    else:
        scan_dirs = [INPUT_ROOT, RUN_ROOT]

    items: list[dict[str, Any]] = []
    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue
        for root, dirs, filenames in os.walk(scan_dir):
            root_path = Path(root)
            # Calculate current depth relative to scan_dir
            try:
                depth = len(root_path.resolve().relative_to(scan_dir.resolve()).parts)
            except ValueError:
                depth = 0

            # Enforce max_depth
            if max_depth is not None and depth >= max_depth:
                dirs.clear()  # prevent os.walk from descending further
                # Still process files at this level
                if depth > max_depth:
                    continue

            # Skip measure internals (resources/, tests/) but keep 1 level into measures/
            rel = str(root_path.resolve().relative_to(scan_dir.resolve())).replace("\\", "/")
            if "/resources/" in rel or "/tests/" in rel:
                dirs.clear()
                continue

            # Add directories at this level (only when no pattern filter)
            if pattern == "*":
                for dname in dirs:
                    items.append({
                        "name": dname,
                        "path": str(root_path / dname),
                        "type": "dir",
                    })

            # Add files
            for fname in filenames:
                if pattern != "*" and not fnmatch.fnmatch(fname, pattern):
                    continue
                items.append({
                    "name": fname,
                    "path": str(root_path / fname),
                    "type": "file",
                })

    items.sort(key=lambda f: f["name"])
    return {"ok": True, "total": len(items), "items": items}


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
    base_dir = Path(out_dir) if out_dir else (RUN_ROOT / "examples")
    base_dir = base_dir.resolve()

    if not is_path_allowed(base_dir):
        return {"ok": False, "error": f"Output directory not allowed: {base_dir}"}

    model_dir = (base_dir / safe).resolve()
    if not is_path_allowed(model_dir):
        return {"ok": False, "error": f"Output directory not allowed: {model_dir}"}

    osm_path = model_dir / "baseline_model.osm"

    try:
        model_dir.mkdir(parents=True, exist_ok=True)

        with suppress_openstudio_warnings():
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
