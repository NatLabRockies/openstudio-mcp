from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ASSETS_ROOT = Path(__file__).resolve().parent / "assets"
SEB_MODEL_ROOT = ASSETS_ROOT / "SEB_model"
OSW_DIR = SEB_MODEL_ROOT / "SEB4_baseboard"
OSW_PATH = OSW_DIR / "workflow.osw"


def _integration_enabled() -> bool:
    """
    Keep integration tests opt-in. Enable with:
      RUN_OPENSTUDIO_INTEGRATION=1
    """
    return os.environ.get("RUN_OPENSTUDIO_INTEGRATION", "").strip().lower() not in ("", "0", "false")


def _run_openstudio_workflow(workdir: Path, timeout_s: int = 60 * 30) -> subprocess.CompletedProcess:
    """
    Run: openstudio run -w <workflow.osw>
    Capture stdout/stderr for debugging.
    """
    return subprocess.run(
        ["openstudio", "run", "-w", str(workdir / "workflow.osw")],
        cwd=str(workdir),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout_s,
    )


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.integration
def test_run_seb4_baseboard_workflow(tmp_path: Path):
    if not _integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable OpenStudio integration tests.")

    if not OSW_PATH.exists():
        pytest.fail(f"Missing workflow at {OSW_PATH}")

    # Read the workflow to discover the EPW path exactly as referenced (case-sensitive on Linux)
    osw = _load_json(OSW_PATH)
    weather_ref = osw.get("weather_file")
    if not weather_ref:
        pytest.fail("workflow.osw missing required 'weather_file' field.")

    # Ensure the referenced EPW exists in the repo assets (before we copy to tmp)
    epw_repo_path = OSW_DIR / weather_ref
    if not epw_repo_path.exists():
        pytest.fail(
            f"Weather file referenced by workflow.osw cannot be found:\n"
            f"  workflow.osw weather_file: {weather_ref}\n"
            f"  expected path: {epw_repo_path}\n"
            f"Fix the filename/casing or place the EPW at that exact path.",
        )

    # Copy the entire SEB_model folder into an isolated temp directory
    seb_tmp = tmp_path / "SEB_model"
    shutil.copytree(SEB_MODEL_ROOT, seb_tmp)

    run_dir = seb_tmp / "SEB4_baseboard"
    assert (run_dir / "workflow.osw").exists()

    # Sanity check: EPW also exists in the tmp copy
    epw_tmp_path = run_dir / weather_ref
    assert epw_tmp_path.exists(), f"EPW did not copy into tmp tree: {epw_tmp_path}"

    proc = _run_openstudio_workflow(run_dir, timeout_s=60 * 30)

    assert proc.returncode == 0, (
        f"OpenStudio run failed.\ncwd: {run_dir}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}\n"
    )

    # Primary success signal: out.osw is produced and indicates Success
    out_osw = run_dir / "out.osw"
    assert out_osw.exists(), f"Expected out.osw not found at: {out_osw}"

    out = _load_json(out_osw)

    # Dump out.osw so -s shows proof of what actually ran
    print("\n===== out.osw (from integration run) =====")
    print(json.dumps(out, indent=2, sort_keys=True))
    print("===== end out.osw =====\n")

    completed = (out.get("completed_status") or "").strip()
    assert completed.lower() == "success", f"Workflow completed_status was not Success: {completed}"

    # Secondary signal: run directory exists (location comes from out.osw if present)
    run_subdir = (out.get("run_dir") or "run").strip()
    run_out = run_dir / run_subdir
    assert run_out.exists(), f"Expected run output dir not found: {run_out}"

    # Look for at least one common EnergyPlus/OpenStudio artifact (don’t overfit filenames)
    candidates = [
        run_out / "eplusout.sql",
        run_out / "eplusout.err",
        run_out / "eplusout.end",
        run_out / "in.idf",
        run_out / "in.osm",
        run_out / "run.log",
    ]
    assert any(p.exists() for p in candidates), (
        f"Run directory exists but none of the expected artifacts were found.\n"
        f"run_out: {run_out}\n"
        f"checked: {[str(p) for p in candidates]}"
    )

    # If there's an EnergyPlus err file, fail if it contains Fatal
    err = run_out / "eplusout.err"
    if err.exists():
        txt = err.read_text(errors="ignore")
        assert "fatal" not in txt.lower(), f"EnergyPlus fatal error detected in {err}:\n{txt}"
