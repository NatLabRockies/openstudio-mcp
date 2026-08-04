"""Weather-reference resolution for measure OSW runs.

`openstudio run --measures_only` validates the seed model's weather
reference during workflow Initialization even though no weather data is
read. Models conventionally store OS:WeatherFile Url as a bare filename
(resolved at run time against search paths), which the OSW runner cannot
resolve without help. Resolution tiers:

1. Url resolves as-is -> add its parent dir to OSW file_paths
2. Basename found in known weather dirs -> stage the EPW into the run's
   files/ dir and set OSW weather_file (same mechanics as run_osw)
3. Unfindable -> strip OS:WeatherFile from the temp seed OSM; the caller
   restores it on the reloaded model (unless the measure set a new one)
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.config import is_path_allowed
from mcp_server.skills.weather.operations import find_epw_by_name


def resolve_osw_weather(model: Any, run_dir: Path, temp_osm: Path) -> dict[str, Any]:
    """Make the temp seed's weather reference survivable by the OSW runner.

    Returns dict with:
      file_paths: directory strings for the OSW file_paths key
      weather_file: OSW weather_file value (relative to run_dir), or None
      stripped_idf: IdfObject snapshot of a stripped OS:WeatherFile, or None
    """
    out: dict[str, Any] = {"file_paths": [], "weather_file": None, "stripped_idf": None}
    wf = model.weatherFile()
    if not wf.is_initialized():
        return out
    url = wf.get().path()
    if not url.is_initialized():
        return out
    epw = Path(str(url.get()))

    # Tier 1: url already resolves (absolute path still valid on this
    # machine). Stage it into the run dir instead of granting the parent via
    # file_paths: the confined subprocess reads only its own run dir, so an
    # absolute url into another run's files/ or /inputs is unreadable there
    # even though the server resolves it (issue #104 class; surfaced again in
    # issue #97 as a bogus "Windows path length" error from the standards
    # sizing-run rescue). Gated: the url is caller-controlled model content —
    # never point the root server's copy at a path outside allowed roots.
    if epw.is_file() and is_path_allowed(epw):
        out["weather_file"] = stage_epw_into_run(epw.resolve(), run_dir)
        return out

    # Tier 2: bare/stale name — look in known weather dirs, stage like run_osw
    found = find_epw_by_name(epw.name)
    if found is not None:
        files_dir = run_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(found), str(files_dir / found.name))
        out["weather_file"] = f"files/{found.name}"
        return out

    # Tier 3: nowhere to be found — measures_only never reads weather data,
    # so drop the reference from the seed and let the caller restore it
    out["stripped_idf"] = strip_weather_from_seed(temp_osm)
    return out


def stage_epw_into_run(epw_src: Path, run_dir: Path) -> str:
    """Copy an EPW plus companion .ddy/.stat into run_dir/files.

    The confined measure subprocess can read only its own run dir — the
    sandbox deliberately denies shared roots like /inputs (issue #104) — so
    a referenced weather file must be staged, never passed by original path.
    Companions travel too: ChangeBuildingLocation reads the .ddy (design
    days) and .stat (climate zone) from the EPW's directory.

    Returns the OSW-relative reference ('files/<name>').
    """
    files_dir = run_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(epw_src), str(files_dir / epw_src.name))
    for ext in (".ddy", ".stat"):
        companion = epw_src.with_suffix(ext)
        # Companions are derived paths that never went through is_path_allowed
        # (the EPW itself did, resolved). A tenant can write its own run dir,
        # so a planted leaf symlink (x.ddy -> /etc/shadow) would make the root
        # server copy the target into the tenant-readable run dir — skip links.
        if companion.is_symlink() or not companion.is_file():
            continue
        shutil.copy2(str(companion), str(files_dir / companion.name))
    return f"files/{epw_src.name}"


def strip_weather_from_seed(temp_osm: Path) -> Any | None:
    """Remove OS:WeatherFile from a saved seed OSM; return its IdfObject.

    Returns None if the seed can't be loaded or has no weather file.
    """
    loaded = openstudio.model.Model.load(openstudio.toPath(str(temp_osm)))
    if not loaded.is_initialized():
        return None
    seed = loaded.get()
    wf = seed.weatherFile()
    if not wf.is_initialized():
        return None
    snapshot = wf.get().idfObject()
    wf.get().remove()
    seed.save(openstudio.toPath(str(temp_osm)), True)
    return snapshot
