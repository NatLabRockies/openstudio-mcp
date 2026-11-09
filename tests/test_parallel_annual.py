"""parallel-annual skill (issue #247): bundled time-segment measures + stitch_segment_results.

Runs the skill's recipe end to end through the MCP tools on a short run period
(Jan-Feb, 3 segments) so CI stays fast: sizing run, hard-size, segment OSWs,
segment runs, one-segment reference, stitch with reference check.
"""
import asyncio
import subprocess
import uuid
from pathlib import Path

import pytest
from conftest import EPW_PATH, integration_enabled, poll_until_done, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

MEASURES = {
    "hard_size_from_sizing_sql": "Hard Size From Sizing SQL",
    "set_run_period_and_save": "Set Run Period And Save",
    "set_warmup_days": "Set Warmup Days",
    "write_segment_osws": "Write Segment OSWs",
    "segment_results_summary": "Segment Results Summary",
}
COMMON = "/opt/common-measures"
FIXTURE = "/repo/tests/assets/SystemD_baseline.osm"


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _call(s, tool: str, args: dict) -> dict:
    r = unwrap(await s.call_tool(tool, args))
    assert r.get("ok") is True, f"{tool} failed: {r}"
    return r


async def _run_and_wait(s, tool: str, args: dict) -> str:
    run_id = (await _call(s, tool, args))["run_id"]
    status = await poll_until_done(s, run_id)
    assert status["run"]["status"] == "success", f"{tool} run {run_id} did not succeed: {status}"
    return run_id


@pytest.mark.integration
def test_parallel_measures_listed_without_setup():
    # Validates: the five bundled measures are discoverable by list_common_measures and
    # find_measure out of the box (Dockerfile copies them into COMMON_MEASURES_DIR)
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                listed = await _call(s, "list_common_measures", {"category": "parallel"})
                assert {m["name"] for m in listed["measures"]} == set(MEASURES)
                for name, display in MEASURES.items():
                    found = await _call(s, "find_measure", {"query": display, "download_if_bcl_match": False})
                    assert found["source"] == "local", f"{display}: {found}"
                    assert found["measure_dir"] == f"{COMMON}/{name}", f"{display}: {found['measure_dir']}"

    asyncio.run(_run())


@pytest.mark.integration
@pytest.mark.parametrize("name", sorted(MEASURES))
def test_bundled_measure_unit_tests_pass(name):
    # Validates: each bundled measure's Ruby unit tests pass on the image's OpenStudio
    if not integration_enabled():
        pytest.skip("integration disabled")
    test_rb = Path(COMMON) / name / "tests" / f"{name}_test.rb"
    cmd = ["openstudio", str(test_rb)]  # the image's CLI runs the minitest file
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)  # noqa: S603 - fixed argv
    assert proc.returncode == 0, f"{name} minitest failed:\n{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}"
    assert " 0 failures, 0 errors" in proc.stdout, proc.stdout[-2000:]


@pytest.mark.integration
def test_segments_stitch_within_tenth_of_a_percent_of_reference():
    # Validates: the skill's recipe (hard-size, seasonal lead-in segments, stitch) reproduces the
    # single-run electricity total within 0.1% and covers every day exactly once (issue #247)
    if not integration_enabled():
        pytest.skip("integration disabled")
    name = _unique("pa")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # --- Arrange: Jan-Feb model, sizing run ---
                await _call(s, "load_osm_model", {"osm_path": FIXTURE})
                await _call(s, "set_run_period", {"begin_month": 1, "begin_day": 1, "end_month": 2, "end_day": 28})
                await _call(s, "set_simulation_control", {
                    "run_for_weather_file": False, "do_zone_sizing": True,
                    "do_system_sizing": True, "do_plant_sizing": True,
                })
                sizing_osm = (await _call(s, "save_osm_model", {"save_name": f"{name}_sizing"}))["osm_path"]
                sizing_run = await _run_and_wait(s, "run_simulation", {"osm_path": sizing_osm, "epw_path": EPW_PATH})
                await _call(s, "set_simulation_control", {"run_for_weather_file": True})

                # --- Act: hard-size from the SQL staged in the model's files/ folder ---
                arts = await _call(s, "get_run_artifacts", {"run_id": sizing_run})
                run_children = next(a["children"] for a in arts["artifacts"] if a["name"] == "run")
                sql = next(c["path"] for c in run_children if c["name"] == "eplusout.sql")
                hs_osm = (await _call(s, "save_osm_model", {"save_name": f"{name}_hardsize"}))["osm_path"]
                files_dir = str(Path(hs_osm).with_suffix("") / "files")  # the model's companion files/ folder
                await _call(s, "copy_file", {"file_path": sql, "destination": files_dir})
                hs = await _call(s, "apply_measure", {
                    "measure_dir": f"{COMMON}/hard_size_from_sizing_sql", "arguments": {"sql_path": "eplusout.sql"},
                })
                assert "Hard-sized" in hs["runner_messages"]["final_condition"], hs["runner_messages"]
                seed = (await _call(s, "save_osm_model", {"save_name": f"{name}_hardsized"}))["osm_path"]

                async def write(count: int) -> str:
                    res = await _call(s, "apply_measure", {
                        "measure_dir": f"{COMMON}/write_segment_osws",
                        "arguments": {"seed_osm_path": seed, "weather_file": EPW_PATH, "number_of_segments": count},
                    })
                    return str(Path(res["run_dir"]) / "segments")

                seg_dir, ref_dir = await write(3), await write(1)
                seg_runs = [
                    await _run_and_wait(s, "run_osw", {
                        "osw_path": f"{seg_dir}/segment_{k:02d}/segment_{k:02d}.osw", "name": f"{name}_seg{k}",
                    })
                    for k in (1, 2, 3)
                ]
                ref_run = await _run_and_wait(s, "run_osw", {
                    "osw_path": f"{ref_dir}/segment_01/segment_01.osw", "name": f"{name}_ref",
                })
                stitched = await _call(s, "stitch_segment_results", {"run_ids": seg_runs, "reference_run_id": ref_run})

                # --- Assert ---
                assert (stitched["kept_days"], stitched["first_day"], stitched["last_day"]) == (59, "01-01", "02-28")
                assert set(stitched["monthly_end_uses_kwh"]) == {"01", "02"}
                check = stitched["reference_check"]
                assert abs(check["annual_electricity_error_pct"]) < 0.1, check
                assert [d["day"] for d in check["first_kept_day_error_pct"]] == ["01-20", "02-09"]
                assert stitched["annual_end_uses_kwh"]["Electricity"]["Total"] == pytest.approx(
                    stitched["annual_electricity_kwh"], rel=1e-9)

                bad = unwrap(await s.call_tool("stitch_segment_results", {"run_ids": seg_runs[:1] + seg_runs[2:]}))
                assert bad["ok"] is False and bad["missing_days"][0] == "01-20", bad

    asyncio.run(_run())
