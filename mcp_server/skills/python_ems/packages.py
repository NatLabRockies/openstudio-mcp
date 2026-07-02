"""Per-user Python packages for EnergyPlus plugins.

pip installs wheels-only into the caller's python_packages dir (inside their
run root). Wheels-only means no sdist setup.py ever executes in the server
process. The dir reaches plugins at simulation time via PythonPlugin:SearchPaths
(FT merges it with the auto-generated entry) and a read-only Landlock grant on
the sandboxed EnergyPlus child. Quota is a hard cap: an install that lands over
it clears the dir and errors.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp_server import model_manager
from mcp_server.config import OSMCP_PKGS_QUOTA_MB, user_pkgs_root
from mcp_server.osm_helpers import parse_str_list
from mcp_server.skills.python_ems.operations import ensure_pkgs_search_path
from mcp_server.skills.python_ems.templates import validate_package_specs

_PIP_TIMEOUT_SECONDS = 600


def _dir_size_bytes(root: Path) -> int:
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())


def _installed_list(target: Path) -> list[dict[str, str]]:
    proc = subprocess.run(  # noqa: S603 - fixed pip argv, server-controlled path
        [sys.executable, "-m", "pip", "list", "--path", str(target),
         "--format", "json", "--disable-pip-version-check"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    if proc.returncode != 0:
        return []
    try:
        return [{"name": p["name"], "version": p["version"]}
                for p in json.loads(proc.stdout)]
    except (json.JSONDecodeError, KeyError):
        return []


def install_plugin_packages_op(packages: list[str] | str | None) -> dict[str, Any]:
    """pip-install packages (wheels only) into the caller's plugin package dir."""
    try:
        specs = validate_package_specs(parse_str_list(packages) or [])
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    target = user_pkgs_root()
    target.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "pip", "install",
        "--only-binary=:all:",  # never execute sdist build code
        "--no-cache-dir", "--disable-pip-version-check", "--quiet",
        "--upgrade", "--target", str(target),
        *specs,
    ]
    try:
        proc = subprocess.run(  # noqa: S603 - specs validated against _PKG_SPEC_RE
            cmd, capture_output=True, text=True,
            timeout=_PIP_TIMEOUT_SECONDS, check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False,
                "error": f"pip install timed out after {_PIP_TIMEOUT_SECONDS}s"}
    if proc.returncode != 0:
        return {
            "ok": False,
            "error": "pip install failed. Packages must ship wheels for this "
                     "platform (cp312/py3, linux) — sdists are refused by design.",
            "stderr_tail": (proc.stderr or proc.stdout or "")[-1500:],
        }

    size = _dir_size_bytes(target)
    quota_bytes = OSMCP_PKGS_QUOTA_MB * 1024 * 1024
    if quota_bytes > 0 and size > quota_bytes:
        shutil.rmtree(target, ignore_errors=True)
        return {
            "ok": False,
            "error": f"Installed packages total {size / 1048576:.0f} MB, over the "
                     f"{OSMCP_PKGS_QUOTA_MB} MB quota — package dir cleared. "
                     "Install fewer or smaller packages.",
        }

    search_path_added = False
    model = model_manager.get_model_if_loaded()
    if model is not None:
        search_path_added = ensure_pkgs_search_path(model)

    return {
        "ok": True,
        "installed": _installed_list(target),
        "packages_dir": str(target),
        "total_size_mb": round(size / 1048576, 1),
        "quota_mb": OSMCP_PKGS_QUOTA_MB,
        "search_path_added": search_path_added,
        "note": "Plugins import these inside EnergyPlus (embedded Python 3.12) "
                "via PythonPlugin:SearchPaths; create_python_plugin adds the "
                "path to any model automatically.",
    }
