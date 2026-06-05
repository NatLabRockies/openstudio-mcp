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
    # machine). resolve() so a url relative to the server cwd doesn't
    # produce a relative file_paths entry — the runner executes with
    # cwd=run_dir and would resolve it against the wrong base
    if epw.is_file():
        out["file_paths"].append(str(epw.resolve().parent))
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
