"""gbXML -> OpenStudio model translation.

Runs the NatLabRockies/gbxml-to-openstudio measure gem's model-building steps
(ChangeBuildingLocation -> gbxml_import -> gbxml_import_advanced ->
gbxml_import_hvac -> set_simulation_control -> gbxml_postprocess) through the
`openstudio` CLI with `--measures_only`, so EnergyPlus never runs — only the
ModelMeasures that build the OSM from the gbXML do. The workflow's two
ReportingMeasure steps (openstudio_results, systems_analysis_report_generator)
are intentionally omitted: they need simulation output that `--measures_only`
never produces, so including them would just be dead weight in the OSW.
"""
from __future__ import annotations

import itertools
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import openstudio

from mcp_server import model_manager, sandbox
from mcp_server.config import (
    GBXML_MEASURES_DIR,
    GBXML_SEED_OSM,
    OSCLI_GEM_PATH,
    OSCLI_GEMFILE,
    is_path_allowed,
    user_run_root,
)
from mcp_server.model_manager import get_model
from mcp_server.skills.geometry.operations import match_surfaces
from mcp_server.skills.measures.runner_messages import parse_all_step_messages
from mcp_server.util import create_run_dir, reject_escaping_symlinks

# Same measure set the upstream "Annual Building Energy Simulation.osw" uses
# for model building, minus the two ReportingMeasure steps at the end (see
# module docstring). ChangeBuildingLocation (added separately, first) always
# runs: gbxml_import_advanced reads the model's WeatherFile while building
# schedules and errors out without one, even though nothing gets simulated.
GBXML_MODEL_MEASURES = (
    "gbxml_import",
    "gbxml_import_advanced",
    "gbxml_import_hvac",
    "set_simulation_control",
    "gbxml_postprocess",
)

# Defaults lifted verbatim from the upstream workflow's set_simulation_control
# step — sane sizing/timestep settings for a model that may later be simulated,
# even though --measures_only itself never runs EnergyPlus. Values are already
# OSW-argument strings (lowercase booleans), not Python literals.
SET_SIMULATION_CONTROL_ARGS: dict[str, str] = {
    "cooling_sizing_factor": "1.0",
    "do_plant_sizing": "true",
    "do_system_sizing": "true",
    "do_zone_sizing": "true",
    "end_date": "12/31",
    "heating_sizing_factor": "1.0",
    "loads_convergence_tolerance": "0.1",
    "max_warmup_days": "25",
    "min_warmup_days": "6",
    "sim_for_run_period": "true",
    "sim_for_sizing": "true",
    "solar_distribution": "FullExterior",
    "start_date": "01/01",
    "temp_convergence_tolerance": "0.5",
    "timesteps_per_hour": "4",
    "max_hvac_iterations": "8",
}

GBXML_EXTENSIONS = {".xml", ".gbxml"}


def _os_path(p: Path):
    """Return an OpenStudio Path object for a filesystem Path."""
    return openstudio.path(str(p))


def import_gbxml_op(
    gbxml_path: str,
    epw_path: str,
    osm_path: str | None = None,
    run_name: str | None = None,
) -> dict[str, Any]:
    """Translate a gbXML file into an OpenStudio model with location embedded.

    Args:
        gbxml_path: Path to the source gbXML file (e.g. under /inputs).
        epw_path: Path to the project's own EPW file (e.g. under /inputs). Its
            companion .stat and .ddy files (same directory, same stem) must sit
            alongside it — ChangeBuildingLocation requires the .stat, and this
            is also how the resulting .osm gets its real project location
            embedded rather than an arbitrary placeholder.
        osm_path: Where to save the resulting .osm. Defaults to a run directory.
        run_name: Optional label for the run directory.
    """
    try:
        gbxml_src = Path(gbxml_path)
        if not gbxml_src.is_file():
            return {"ok": False, "error": f"gbXML file not found: {gbxml_path}"}
        if gbxml_src.suffix.lower() not in GBXML_EXTENSIONS:
            return {"ok": False, "error": f"Not a gbXML file (expected .xml/.gbxml): {gbxml_path}"}
        if not is_path_allowed(gbxml_src):
            return {"ok": False, "error": f"gbXML path not allowed: {gbxml_path}"}

        if not GBXML_MEASURES_DIR.is_dir():
            return {"ok": False, "error": f"gbXML measures not found: {GBXML_MEASURES_DIR}"}
        if not GBXML_SEED_OSM.is_file():
            return {"ok": False, "error": f"gbXML seed model not found: {GBXML_SEED_OSM}"}

        epw_src = Path(epw_path)
        if not epw_src.is_file():
            return {"ok": False, "error": f"EPW file not found: {epw_path}"}
        if epw_src.suffix.lower() != ".epw":
            return {"ok": False, "error": f"Not an EPW file (expected .epw): {epw_path}"}
        if not is_path_allowed(epw_src):
            return {"ok": False, "error": f"EPW path not allowed: {epw_path}"}
        stat_src = epw_src.with_suffix(".stat")
        if not stat_src.is_file():
            return {"ok": False, "error": f"Missing companion .stat file next to EPW: {stat_src}"}
        ddy_src = epw_src.with_suffix(".ddy")
        if not ddy_src.is_file():
            return {"ok": False, "error": f"Missing companion .ddy file next to EPW: {ddy_src}"}

        if osm_path:
            osm_out = Path(osm_path)
            if not is_path_allowed(osm_out, write=True):
                return {"ok": False, "error": f"osm_path not allowed: {osm_path}"}
        else:
            osm_out = None  # resolved to a run-dir default once run_dir exists

        _run_id, run_dir = create_run_dir(user_run_root(), "gbxml_import", run_name or gbxml_src.stem)

        # Stage the gbXML + seed model + user-supplied weather file.
        gbxmls_dir = run_dir / "gbxmls"
        gbxmls_dir.mkdir(parents=True, exist_ok=True)
        gbxml_name = gbxml_src.name
        shutil.copy2(str(gbxml_src), str(gbxmls_dir / gbxml_name))

        seeds_dir = run_dir / "seeds"
        seeds_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(GBXML_SEED_OSM), str(seeds_dir / "seed_empty.osm"))

        # ChangeBuildingLocation needs the EPW's companion .stat (design-day
        # stats) and .ddy (design days) files alongside it, not just the .epw.
        weather_dir = run_dir / "weather"
        weather_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(epw_src), str(weather_dir / epw_src.name))
        shutil.copy2(str(stat_src), str(weather_dir / stat_src.name))
        shutil.copy2(str(ddy_src), str(weather_dir / ddy_src.name))
        file_paths = ["gbxmls", "seeds", "weather"]

        # Stage each needed measure into the run dir so the confined subprocess
        # only ever reads run_dir (never GBXML_MEASURES_DIR directly) — same
        # convention apply_measure() uses for bundled/user measures.
        measures_dir = run_dir / "measures"
        measures_dir.mkdir(parents=True, exist_ok=True)
        needed_measures = ["ChangeBuildingLocation", *GBXML_MODEL_MEASURES]
        for measure_name in needed_measures:
            src = GBXML_MEASURES_DIR / measure_name
            if not src.is_dir():
                return {"ok": False, "error": f"gbXML measure not found: {measure_name} (in {GBXML_MEASURES_DIR})"}
            err = reject_escaping_symlinks(src)
            if err:
                return {"ok": False, "error": err}
            shutil.copytree(str(src), str(measures_dir / measure_name), dirs_exist_ok=True, symlinks=True)

        steps: list[dict[str, Any]] = [{
            "measure_dir_name": "ChangeBuildingLocation",
            "arguments": {"weather_file_name": epw_src.name},
        }]
        for measure_name in ("gbxml_import", "gbxml_import_advanced", "gbxml_import_hvac"):
            steps.append({
                "measure_dir_name": measure_name,
                "arguments": {"gbxml_file_name": gbxml_name},
            })
        steps.append({
            "measure_dir_name": "set_simulation_control",
            "arguments": dict(SET_SIMULATION_CONTROL_ARGS),
        })
        steps.append({"measure_dir_name": "gbxml_postprocess"})

        osw = {
            "seed_file": "seed_empty.osm",
            "file_paths": file_paths,
            "measure_paths": [str(measures_dir)],
            "steps": steps,
        }
        osw_path = run_dir / "workflow.osw"
        osw_path.write_text(json.dumps(osw, indent=2), encoding="utf-8")

        cmd = [
            "openstudio",
            "--bundle", OSCLI_GEMFILE,
            "--bundle_path", OSCLI_GEM_PATH,
            "--bundle_without", "native_ext",
            "run", "--measures_only", "-w", str(osw_path),
        ]
        log_path = run_dir / "openstudio.log"
        run_env = sandbox.build_env(run_dir)
        sandbox.prepare_workdir(run_dir)
        with open(log_path, "w", encoding="utf-8") as log_f:
            proc = subprocess.run(
                sandbox.wrap_cmd(cmd, run_dir),
                cwd=str(run_dir),
                stdout=log_f,
                stderr=subprocess.STDOUT,
                env=run_env,
                timeout=300,  # 5 minute timeout
                check=False,
            )

        if proc.returncode != 0:
            log_lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(log_lines[-50:])
            return {
                "ok": False,
                "error": f"gbXML import failed (exit code {proc.returncode})",
                "log_tail": tail,
                "run_dir": str(run_dir),
            }

        out_osw_path = run_dir / "out.osw"
        step_messages = parse_all_step_messages(out_osw_path)

        completed_status = None
        any_step_failed = False
        if out_osw_path.is_file():
            try:
                out_osw = json.loads(out_osw_path.read_text(encoding="utf-8", errors="replace"))
                completed_status = out_osw.get("completed_status")
                any_step_failed = any(
                    (s.get("result") or {}).get("step_result") == "Fail"
                    for s in out_osw.get("steps", [])
                )
            except Exception:
                pass

        ok = completed_status == "Success" and not any_step_failed
        if not ok:
            result: dict[str, Any] = {
                "ok": False,
                "error": f"gbXML import workflow did not complete successfully (completed_status={completed_status!r})",
                "run_dir": str(run_dir),
            }
            if step_messages:
                result["step_messages"] = step_messages
            return result

        output_osm = run_dir / "run" / "in.osm"
        if not output_osm.is_file():
            return {"ok": False, "error": "Output OSM not found after gbXML import", "run_dir": str(run_dir)}

        model_result = openstudio.model.Model.load(str(output_osm))
        if not model_result.is_initialized():
            return {"ok": False, "error": f"Could not load translated model: {output_osm}", "run_dir": str(run_dir)}
        model = model_result.get()

        final_osm_path = osm_out if osm_out is not None else (run_dir / f"{gbxml_src.stem}.osm")
        final_osm_path.parent.mkdir(parents=True, exist_ok=True)
        if not model.save(_os_path(final_osm_path), True):
            return {"ok": False, "error": f"Failed to save model to {final_osm_path}", "run_dir": str(run_dir)}

        model_manager.load_model(final_osm_path)

        result = {
            "ok": True,
            "osm_path": str(final_osm_path),
            "run_dir": str(run_dir),
        }
        if step_messages:
            result["total_errors"] = step_messages.get("total_errors", 0)
            result["total_warnings"] = step_messages.get("total_warnings", 0)
            result["step_messages"] = step_messages
        return result

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "gbXML import timed out (5 min)"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to import gbXML: {e}"}


# ---- Geometry validation ----

# gbXML/Revit exports commonly carry sub-millimeter float noise on otherwise-identical
# vertices; 1cm is tight enough to catch real duplicate geometry, loose enough to tolerate it.
PLANE_TOLERANCE = 0.01
# Minimum true overlap area to report — filters out coplanar surfaces that merely share
# an edge (e.g. adjacent wall segments split at a window), not actual duplicate geometry.
MIN_OVERLAP_AREA_M2 = 0.01
# Keep the response small — same cap style as runner_messages.py's MESSAGE_LIMITS.
MAX_REPORTED_ISSUES = 20


def _clockwise(points: openstudio.Point3dVector) -> openstudio.Point3dVector:
    """Normalize a planar polygon (z~0, as produced by Transformation.alignFace) to the
    winding order openstudio.intersects()/intersect() require — they silently return
    False/empty for correctly-overlapping polygons given the "wrong" (counterclockwise,
    by this SDK's convention) winding, with no error raised. Same reverse-if-z>0 pattern
    already used for floor-print orientation in create_space_from_floor_print above."""
    normal = openstudio.getOutwardNormal(points)
    if normal.is_initialized() and normal.get().z() > 0:
        return openstudio.reverse(points)
    return points


def _overlap_area_m2(face1: openstudio.Point3dVector, face2: openstudio.Point3dVector) -> float:
    """True overlap area between two same-plane, clockwise-normalized polygons.

    openstudio.intersects() alone is too loose for this purpose — it returns True even
    for polygons that merely share an edge (touching, zero actual overlap area), which
    would false-positive on legitimate adjacent same-plane wall segments (e.g. split at
    a window). openstudio.intersect() is the authoritative check: it returns an
    uninitialized result when there's no true overlap area; otherwise IntersectionResult
    .area1()/.area2() are just the two input polygons' own total areas (not the overlap),
    so the actual overlap area is polygon1's area minus the summed area of its
    newPolygons1() remainder (the part of polygon1 left over after removing the overlap).
    """
    opt = openstudio.intersect(face1, face2, PLANE_TOLERANCE)
    if not opt.is_initialized():
        return 0.0
    orig_area = openstudio.getArea(face1)
    if not orig_area.is_initialized():
        return 0.0
    remainder = 0.0
    for poly_points in opt.get().newPolygons1():
        pv = openstudio.Point3dVector()
        for pt in poly_points:
            pv.append(pt)
        area = openstudio.getArea(pv)
        remainder += area.get() if area.is_initialized() else 0.0
    return max(orig_area.get() - remainder, 0.0)


def _surface_overlaps(space: openstudio.model.Space) -> list[dict[str, Any]]:
    """Same-space coincident-plane surfaces that also have true 2D overlap area.

    These are true duplicate/overlapping geometry — match_surfaces() cannot fix
    them, since OpenStudio's own intersectSurfaces()/matchSurfaces() explicitly
    skip surface pairs within the same space (they only reconcile shared walls
    between adjacent spaces).
    """
    surfaces = list(space.surfaces())
    planes: list[Any] = []
    for s in surfaces:
        try:
            planes.append(s.plane())
        except Exception:
            planes.append(None)  # degenerate surface; caught separately by isEnclosedVolume

    issues: list[dict[str, Any]] = []
    for (i, s1), (j, s2) in itertools.combinations(enumerate(surfaces), 2):
        p1, p2 = planes[i], planes[j]
        if p1 is None or p2 is None:
            continue
        same = p1.equal(p2, PLANE_TOLERANCE)
        mirrored = p1.reverseEqual(p2, PLANE_TOLERANCE)
        if not (same or mirrored):
            continue
        transform = openstudio.Transformation.alignFace(s1.vertices()).inverse()
        face1 = _clockwise(transform * s1.vertices())
        face2 = _clockwise(transform * s2.vertices())
        overlap_area = _overlap_area_m2(face1, face2)
        if overlap_area <= MIN_OVERLAP_AREA_M2:
            continue
        issues.append({
            "surface_1": s1.nameString(),
            "surface_2": s2.nameString(),
            "overlap_area_m2": round(overlap_area, 4),
            "same_orientation": bool(same),
        })
    return issues


def validate_gbxml_geometry_op() -> dict[str, Any]:
    """Fix cross-space shared walls, then report same-space overlaps + non-enclosed spaces."""
    try:
        model = get_model()
        match_result = match_surfaces()  # mutates: fixes the common cross-space case first
        if not match_result.get("ok"):
            return {"ok": False, "error": "match_surfaces() failed before geometry validation"}

        overlaps: list[dict[str, Any]] = []
        non_enclosed: list[dict[str, Any]] = []
        for space in model.getSpaces():
            name = space.nameString()
            for issue in _surface_overlaps(space):
                issue["space"] = name
                overlaps.append(issue)
            if not space.isEnclosedVolume():
                surfaces = space.surfaces()
                non_enclosed.append({
                    "space": name,
                    "floor_area_m2": float(space.floorArea()),
                    "has_floor": any(s.surfaceType() == "Floor" for s in surfaces),
                    "has_roofceiling": any(s.surfaceType() == "RoofCeiling" for s in surfaces),
                })

        result = {
            "ok": not overlaps and not non_enclosed,
            "cross_space_surfaces_matched": match_result["matched_surfaces"],
            "space_count": len(model.getSpaces()),
            "surface_count": len(model.getSurfaces()),
            "overlapping_surfaces_count": len(overlaps),
            "overlapping_surfaces": overlaps[:MAX_REPORTED_ISSUES],
            "non_enclosed_spaces_count": len(non_enclosed),
            "non_enclosed_spaces": non_enclosed[:MAX_REPORTED_ISSUES],
        }
        if len(overlaps) > MAX_REPORTED_ISSUES:
            result["overlapping_surfaces_truncated"] = True
        if len(non_enclosed) > MAX_REPORTED_ISSUES:
            result["non_enclosed_spaces_truncated"] = True
        return result
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to validate geometry: {e}"}
