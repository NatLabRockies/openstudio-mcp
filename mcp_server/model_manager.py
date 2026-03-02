"""Shared model state for the current MCP session.

All model-querying skills call get_model() to access
the currently loaded OpenStudio model.
"""
from __future__ import annotations

import atexit
from pathlib import Path

import openstudio

from mcp_server.stdout_suppression import suppress_openstudio_warnings

_current_model: openstudio.model.Model | None = None
_current_model_path: Path | None = None


def load_model(osm_path: Path, version_translate: bool = True) -> openstudio.model.Model:
    """Load an OSM file and set it as the current model."""
    global _current_model, _current_model_path
    abs_path = str(osm_path.resolve())

    with suppress_openstudio_warnings():
        if version_translate:
            vt = openstudio.osversion.VersionTranslator()
            loaded = vt.loadModel(abs_path)
        else:
            loaded = openstudio.model.Model.load(abs_path)

        if not loaded.is_initialized():
            raise ValueError(f"Failed to load OSM: {osm_path}")
        _current_model = loaded.get()
        _current_model_path = osm_path
    return _current_model


def save_model(save_path: Path | None = None) -> Path:
    """Save current model. Returns path saved to."""
    if _current_model is None:
        raise RuntimeError("No model loaded.")
    path = save_path or _current_model_path
    if path is None:
        raise RuntimeError("No save path specified and no current path.")
    with suppress_openstudio_warnings():
        _current_model.save(str(path), True)
    return path


def get_model() -> openstudio.model.Model:
    """Get the currently loaded model, or raise."""
    if _current_model is None:
        raise RuntimeError("No model loaded. Call load_osm_model first.")
    return _current_model


def get_model_path() -> Path | None:
    """Return the file path of the currently loaded model, or None."""
    return _current_model_path


def get_model_if_loaded() -> openstudio.model.Model | None:
    """Return the current model without raising, or None if not loaded."""
    return _current_model


def clear_model() -> None:
    """Clear current model state (mainly for testing)."""
    global _current_model, _current_model_path
    _current_model = None
    _current_model_path = None


# Release SWIG Model* before interpreter shutdown to avoid
# "swig/python detected a memory leak" warning (openstudio#5421)
atexit.register(clear_model)
