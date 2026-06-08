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
import zipfile
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlparse
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any

import openstudio

from mcp_server.config import (
    BCL_MEASURES_DIR,
    COMMON_MEASURES_DIR,
    COMSTOCK_MEASURES_DIR,
    CUSTOM_MEASURES_DIR,
    INPUT_ROOT,
    MEASURES_DIR,
    OSCLI_GEM_PATH,
    OSCLI_GEMFILE,
    RUN_ROOT,
    is_path_allowed,
    user_run_root,
)
from mcp_server.model_manager import get_model, load_model
from mcp_server.skills.measures.osw_weather import resolve_osw_weather
from mcp_server.util import create_run_dir, resolve_run_dir


MEASURE_DOWNLOAD_HOSTS = {"bcl.nrel.gov", "bcl.nlr.gov", "github.com", "raw.githubusercontent.com"}


class _BCLDownloadLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.download_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href") or ""
        if "/api/download?" in href:
            self.download_links.append(href)


def _is_measure_dir(path: Path) -> bool:
    return path.is_dir() and ((path / "measure.rb").is_file() or (path / "measure.py").is_file())


def _measure_entry(path: Path, source: str) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": path.name,
        "measure_dir": str(path),
        "source": source,
        "has_measure_xml": (path / "measure.xml").is_file(),
    }
    try:
        bcl = openstudio.BCLMeasure(openstudio.toPath(str(path)))
        entry["display_name"] = bcl.name()
        entry["description"] = bcl.description()[:300]
        entry["measure_type"] = bcl.measureType().valueName()
        entry["num_arguments"] = len(bcl.arguments())
    except Exception:
        entry["display_name"] = path.name
        entry["description"] = ""
        entry["measure_type"] = None
        entry["num_arguments"] = -1
    return entry


def _iter_measure_dirs(root: Path, max_depth: int) -> list[Path]:
    if _is_measure_dir(root):
        return [root]
    found = []
    base_depth = len(root.parts)
    for path in root.rglob("*"):
        if len(path.parts) - base_depth > max_depth:
            continue
        if _is_measure_dir(path):
            found.append(path)
    return found


def _safe_extract_zip(zip_path: Path, output_dir: Path) -> list[Path]:
    extracted = []
    output_root = output_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (output_root / member.filename).resolve()
            if not (str(target).startswith(str(output_root) + os.sep) or target == output_root):
                raise ValueError(f"ZIP member would extract outside destination: {member.filename}")
        archive.extractall(output_root)
        extracted = [(output_root / member.filename).resolve() for member in archive.infolist()]
    return extracted


def _guess_download_name(url: str, fallback: str = "downloaded_measure.zip") -> str:
    name = Path(unquote(urlparse(url).path)).name
    return name or fallback


def _read_url(url: str, timeout_seconds: int) -> tuple[bytes, str]:
    req = Request(url, headers={"User-Agent": "openstudio-mcp/measure-downloader"}, method="GET")
    with urlopen(req, timeout=timeout_seconds) as resp:
        headers = getattr(resp, "headers", {})
        content_type = headers.get("Content-Type", "") if headers else ""
        return resp.read(), content_type


def _looks_like_html(payload: bytes, content_type: str) -> bool:
    head = payload[:500].lstrip().lower()
    return "html" in content_type.lower() or head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _resolve_bcl_content_download(url: str, payload: bytes) -> str | None:
    parsed = urlparse(url)
    if parsed.hostname not in {"bcl.nrel.gov", "bcl.nlr.gov"}:
        return None
    parser = _BCLDownloadLinkParser()
    parser.feed(payload.decode("utf-8", errors="replace"))
    if not parser.download_links:
        return None
    return urljoin(url, parser.download_links[0])


def list_local_measures(
    root_dir: str | None = None,
    max_depth: int = 3,
    max_results: int = 200,
) -> dict[str, Any]:
    """List measures in mounted/user/bundled measure directories."""
    try:
        if root_dir:
            roots = [(Path(root_dir).expanduser().resolve(), "requested")]
        else:
            roots = [
                (CUSTOM_MEASURES_DIR.resolve(), "custom"),
                (MEASURES_DIR.resolve(), "measures"),
                ((INPUT_ROOT / "measures").resolve(), "inputs"),
                ((RUN_ROOT / "custom_measures").resolve(), "legacy_custom"),
                (COMMON_MEASURES_DIR.resolve(), "common"),
                (COMSTOCK_MEASURES_DIR.resolve(), "comstock"),
                (BCL_MEASURES_DIR.resolve(), "bcl"),
                ((INPUT_ROOT / "measures" / "bcl").resolve(), "legacy_bcl"),
            ]

        results = []
        seen = set()
        for root, source in roots:
            if not root.is_dir():
                continue
            if not is_path_allowed(root):
                return {"ok": False, "error": f"Directory not allowed: {root}"}
            for measure_dir in _iter_measure_dirs(root, max_depth=max_depth):
                resolved = measure_dir.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                results.append(_measure_entry(resolved, source))
                if len(results) >= max_results:
                    return {"ok": True, "count": len(results), "truncated": True, "measures": results}

        return {"ok": True, "count": len(results), "truncated": False, "measures": results}
    except Exception as e:
        return {"ok": False, "error": f"Failed to list local measures: {e}"}


def download_measure_archive(
    url: str,
    output_dir: str | None = None,
    measure_name: str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    """Download and safely extract a measure ZIP into a writable measure directory."""
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            return {"ok": False, "error": "Only HTTPS measure downloads are allowed."}
        if parsed.hostname not in MEASURE_DOWNLOAD_HOSTS:
            allowed = ", ".join(sorted(MEASURE_DOWNLOAD_HOSTS))
            return {"ok": False, "error": f"Download host not allowed: {parsed.hostname}. Allowed: {allowed}"}

        destination_root = Path(output_dir).expanduser().resolve() if output_dir else BCL_MEASURES_DIR.resolve()
        if not is_path_allowed(destination_root):
            return {"ok": False, "error": f"Output directory not allowed: {destination_root}"}
        destination_root.mkdir(parents=True, exist_ok=True)

        download_url = url
        payload, content_type = _read_url(download_url, timeout_seconds)
        if _looks_like_html(payload, content_type):
            resolved_url = _resolve_bcl_content_download(download_url, payload)
            if resolved_url:
                download_url = resolved_url
                payload, content_type = _read_url(download_url, timeout_seconds)

        archive_name = _guess_download_name(download_url)
        archive_path = destination_root / archive_name
        archive_path.write_bytes(payload)

        extract_root = destination_root / (measure_name or archive_path.stem)
        extract_root.mkdir(parents=True, exist_ok=True)
        _safe_extract_zip(archive_path, extract_root)

        measures = list_local_measures(root_dir=str(extract_root), max_depth=4)
        if not measures.get("ok"):
            return measures
        if measures.get("count", 0) == 0:
            return {
                "ok": False,
                "error": "Downloaded archive did not contain a measure directory with measure.rb or measure.py.",
                "archive_path": str(archive_path),
                "extract_dir": str(extract_root),
            }
        return {
            "ok": True,
            "download_url": download_url,
            "archive_path": str(archive_path),
            "extract_dir": str(extract_root),
            "count": measures["count"],
            "measures": measures["measures"],
        }
    except zipfile.BadZipFile:
        return {"ok": False, "error": "Downloaded file is not a valid ZIP archive."}
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return {"ok": False, "error": f"Download failed with HTTP {e.code}: {detail[:500]}"}
    except URLError as e:
        return {"ok": False, "error": f"Could not download measure archive: {e.reason}"}
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to download measure archive: {e}"}


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


def _parse_runner_messages(out_osw_path: Path) -> dict[str, Any] | None:
    """Extract runner messages from out.osw step results.

    Returns dict with result, initial_condition, final_condition,
    info, warnings, errors — or None on parse failure.
    """
    try:
        if not out_osw_path.is_file():
            return None
        osw = json.loads(out_osw_path.read_text(encoding="utf-8", errors="replace"))
        steps = osw.get("steps", [])
        if not steps:
            return None
        step = steps[0]
        result = step.get("result", {})
        msgs: dict[str, Any] = {
            "result": result.get("step_result", ""),
        }
        for key in ("step_initial_condition", "step_final_condition"):
            val = result.get(key)
            if val:
                # Strip "step_" prefix for cleaner output
                msgs[key.replace("step_", "")] = val
        for key, osw_key in [("info", "step_info"), ("warnings", "step_warnings"), ("errors", "step_errors")]:
            items = result.get(osw_key, [])
            if items:
                msgs[key] = items
        return msgs
    except Exception:
        return None


def apply_measure(
    measure_dir: str,
    arguments: dict[str, Any] | None = None,
    run_id: str | None = None,
    use_bundle: bool = True,
) -> dict[str, Any]:
    """Apply an OpenStudio measure to the in-memory model.

    For ModelMeasures (default): saves model → builds OSW → runs
    `openstudio run --measures_only` → reloads model.

    For ReportingMeasures (when run_id provided): copies simulation
    artifacts (SQL, IDF) from a completed run into the measure dir,
    then runs `openstudio run --postprocess_only` so only reporting
    measures execute against the existing results.

    Args:
        measure_dir: Path to the measure directory
        arguments: Optional dict of argument_name -> value overrides
        run_id: Optional completed simulation run_id (for reporting measures)
    """
    try:
        model = get_model()
        measure_path = Path(measure_dir)
        if not measure_path.is_dir():
            return {"ok": False, "error": f"Measure directory not found: {measure_dir}"}

        # Check measure script exists (Ruby or Python)
        has_rb = (measure_path / "measure.rb").is_file()
        has_py = (measure_path / "measure.py").is_file()
        if not has_rb and not has_py:
            return {"ok": False, "error": f"No measure.rb or measure.py found in {measure_dir}"}

        # Create temp directory for the run
        _measure_run_id, run_dir = create_run_dir(user_run_root(), "measure", measure_path.name)

        # Save current model to temp OSM
        temp_osm = run_dir / "in.osm"
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

        # Resolve the model's weather reference so the OSW runner's
        # Initialization state doesn't abort on a bare/stale EPW url —
        # the runner validates weather even for --measures_only.
        # Tiers: resolvable url -> file_paths; basename in known weather
        # dirs -> staged into files/; unfindable -> stripped from seed
        # (snapshot restored onto the reloaded model below)
        weather = resolve_osw_weather(model, run_dir, temp_osm)
        file_paths = weather["file_paths"]
        osw_weather_file = weather["weather_file"]

        # Also add directories of any EPW paths passed as arguments
        # (e.g. ChangeBuildingLocation's weather_file_name argument).
        # An explicit argument EPW overrides model-based resolution.
        if arguments:
            for v in arguments.values():
                v_str = str(v)
                if v_str.endswith(".epw") and Path(v_str).is_file():
                    parent = str(Path(v_str).parent)
                    if parent not in file_paths:
                        file_paths.append(parent)
                    osw_weather_file = v_str

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
        # If an EPW was found in arguments, set it in the OSW so the runner
        # doesn't fail trying to resolve a stale weather reference from the model
        if osw_weather_file:
            osw["weather_file"] = osw_weather_file

        osw_path = run_dir / "workflow.osw"
        osw_path.write_text(json.dumps(osw, indent=2), encoding="utf-8")

        # Determine run mode: --postprocess_only for reporting measures,
        # --measures_only for model/energyplus measures
        postprocess = False
        if run_id:
            try:
                sim_dir = resolve_run_dir(user_run_root(), run_id)
            except FileNotFoundError:
                return {"ok": False, "error": f"Simulation run not found: {run_id}"}
            sql_src = sim_dir / "run" / "eplusout.sql"
            if not sql_src.is_file():
                return {"ok": False, "error": f"No eplusout.sql in run {run_id} — simulation may not have completed"}
            # Stage simulation artifacts so the reporting measure can find them.
            # The OSW runner expects run/eplusout.sql, run/in.osm, run/in.idf
            ep_run = run_dir / "run"
            ep_run.mkdir(exist_ok=True)
            shutil.copy2(str(sql_src), str(ep_run / "eplusout.sql"))
            osm_src = sim_dir / "run" / "in.osm"
            if osm_src.is_file():
                shutil.copy2(str(osm_src), str(ep_run / "in.osm"))
            idf_src = sim_dir / "run" / "in.idf"
            if idf_src.is_file():
                shutil.copy2(str(idf_src), str(ep_run / "in.idf"))
            postprocess = True

        run_flag = "--postprocess_only" if postprocess else "--measures_only"
        cmd = ["openstudio"]
        if use_bundle:
            cmd += ["--bundle", OSCLI_GEMFILE,
                    "--bundle_path", OSCLI_GEM_PATH,
                    "--bundle_without", "native_ext"]
        cmd += ["run", run_flag, "-w", str(osw_path)]
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

        # Parse runner messages from out.osw
        runner_messages = _parse_runner_messages(run_dir / "out.osw")

        # For reporting measures, don't reload model — just return artifacts
        if postprocess:
            result = {
                "ok": True,
                "measure_dir": str(measure_path),
                "run_dir": str(run_dir),
                "arguments_applied": measure_args,
            }
            if runner_messages:
                result["runner_messages"] = runner_messages
            return result

        # Find the output model — OpenStudio puts it in run/in.osm
        output_osm = run_dir / "run" / "in.osm"
        if not output_osm.is_file():
            # Try the original location
            output_osm = temp_osm
        if not output_osm.is_file():
            return {"ok": False, "error": "Output OSM not found after measure run"}

        # Reload model
        load_model(output_osm)

        result = {
            "ok": True,
            "measure_dir": str(measure_path),
            "run_dir": str(run_dir),
            "arguments_applied": measure_args,
        }

        # If weather was stripped from the seed, restore the original
        # reference — unless the measure set a new one (e.g.
        # ChangeBuildingLocation)
        if weather["stripped_idf"] is not None:
            reloaded = get_model()
            if reloaded.weatherFile().is_initialized():
                result["weather_note"] = (
                    "model weather reference was unresolvable; measure set a new weather file"
                )
            else:
                reloaded.addObject(weather["stripped_idf"])
                result["weather_note"] = (
                    "model weather reference was unresolvable; removed for the "
                    "measures_only run and restored afterward"
                )

        if runner_messages:
            result["runner_messages"] = runner_messages
        return result

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Measure run timed out (5 min)"}
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to apply measure: {e}"}
