"""run_idf end to end (issue #246): one translation, a later segment run from its in.idf.

The model's lighting runs on a Schedule:File, so the IDF run only succeeds if the CSV in the
first run's dir resolves inside the sandbox (EnergyPlus treats a missing one as fatal)."""
import asyncio
import uuid
from pathlib import Path

import pytest
from conftest import EPW_PATH, integration_enabled, poll_until_done, server_params, setup_example, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from test_apply_measure_run_id import RUBY_REPORTING_BODY

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    not integration_enabled(), reason="Set RUN_OPENSTUDIO_INTEGRATION=1",
)]

GENERATED_MEASURE_DIR = "/repo/tests/assets/measures/write_generated_file"


async def _simulate_segment(s, name: str, begin: tuple[int, int], end: tuple[int, int]) -> dict:
    rp = unwrap(await s.call_tool("set_run_period", {
        "begin_month": begin[0], "begin_day": begin[1], "end_month": end[0], "end_day": end[1],
    }))
    assert rp["ok"] is True, rp
    saved = unwrap(await s.call_tool("save_osm_model", {"save_name": name}))
    assert saved["ok"] is True, saved
    run = unwrap(await s.call_tool("run_simulation", {"osm_path": saved["osm_path"], "epw_path": EPW_PATH}))
    assert run["ok"] is True, run
    status = await poll_until_done(s, run["run_id"])
    assert status["run"]["status"] == "success", status
    return run


def test_idf_segment_matches_osm_segment_and_works_with_run_tools():
    # Validates: a segment run from an earlier run's in.idf (RunPeriod overridden) gives the
    # same end uses as simulating that segment from the OSM, its Schedule:File CSV resolves in
    # the sandbox, and the run is visible to get_run_artifacts and apply_measure(run_id)
    name = f"pytest_runidf_{uuid.uuid4().hex[:8]}"

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, name)
                applied = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": GENERATED_MEASURE_DIR, "arguments": {"file_name": "schedule.csv"},
                }))
                assert applied["ok"] is True, applied

                first = await _simulate_segment(s, f"{name}_jan", (1, 1), (1, 7))
                osm_seg = await _simulate_segment(s, f"{name}_mar", (3, 10), (3, 16))

                idf = Path(first["run_dir"]) / "run" / "in.idf"
                started = unwrap(await s.call_tool("run_idf", {
                    "idf_path": str(idf), "epw_path": EPW_PATH, "name": f"{name}_mar_idf",
                    "begin_month": 3, "begin_day": 10, "end_month": 3, "end_day": 16,
                }))
                assert started["ok"] is True, started
                assert started["idf_path"] == str(Path(started["run_dir"]) / "run" / "in.idf")
                assert len(started["schedule_file_dirs"]) == 1, started
                assert started["schedule_file_dirs"][0].startswith(first["run_dir"] + "/"), started
                status = await poll_until_done(s, started["run_id"])
                assert status["run"]["status"] == "success", status

                eu_osm = unwrap(await s.call_tool("extract_end_use_breakdown", {"run_id": osm_seg["run_id"]}))
                eu_idf = unwrap(await s.call_tool("extract_end_use_breakdown", {"run_id": started["run_id"]}))
                assert eu_osm["ok"] is True and eu_idf["ok"] is True, (eu_osm, eu_idf)
                assert sum(eu_osm["totals"].values()) > 0, eu_osm
                assert eu_idf["totals"] == pytest.approx(eu_osm["totals"], rel=1e-6)

                art = unwrap(await s.call_tool("get_run_artifacts", {"run_id": started["run_id"]}))
                assert art["ok"] is True, art
                run_children = next(a["children"] for a in art["artifacts"] if a["name"] == "run")
                assert {"eplusout.sql", "eplusout.err", "in.idf"} <= {c["name"] for c in run_children}

                create = unwrap(await s.call_tool("create_measure", {
                    "name": f"{name}_report", "description": "reads the run_idf SQL",
                    "run_body": RUBY_REPORTING_BODY, "language": "Ruby",
                    "measure_type": "ReportingMeasure",
                }))
                assert create["ok"] is True, create
                rep = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": create["measure_dir"], "run_id": started["run_id"],
                }))
                assert rep["ok"] is True, rep
                msgs = rep.get("runner_messages") or {}
                assert msgs.get("final_condition") == "Report complete", rep
                assert any("Total Site Energy" in m for m in msgs.get("info") or []), rep

    asyncio.run(_run())
