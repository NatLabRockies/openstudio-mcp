"""run_simulation records what it simulated (OSM, effective EPW, resource set) in run_record.json,
and the OSAF seed preflight reuses that run only while the seed's identity still equals it
(#198, second half). The unit tier covers the matching rules; this proves the two sides agree
on a real model whose Schedule:File CSV lives in its companion folder."""
import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

import pytest
from conftest import EPW_PATH, integration_enabled, server_params, setup_example, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    not integration_enabled(), reason="Set RUN_OPENSTUDIO_INTEGRATION=1",
)]

GENERATED_MEASURE_DIR = "/repo/tests/assets/measures/write_generated_file"
CSV = "schedule.csv"


async def _wait_done(s, run_id: str, timeout: float = 900.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))
        assert status["ok"] is True, status
        if status["run"]["status"] in ("success", "failed", "cancelled"):
            return status["run"]
        await asyncio.sleep(5)
    pytest.fail(f"run {run_id} did not finish within {timeout}s")


def test_preflight_reuses_a_run_only_while_the_seed_identity_holds():
    # Regression: the preflight matched a completed run on the OSM and EPW hashes it rehashed
    # from the run dir, so a run made before a resource edit was reused as QA/QC evidence for
    # the edited model; run_simulation now records the hashes of what it staged (the model's own
    # EPW included, which the preflight ignored when no weather_file was passed) and one changed
    # resource byte makes the preflight start a new run
    name = f"pytest_seedid_{uuid.uuid4().hex[:8]}"

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await setup_example(s, name)
                # the model declares its own weather (portable bare-name url): run_simulation
                # and the preflight must both resolve and hash that EPW without an override
                loc = unwrap(await s.call_tool("change_building_location", {"weather_file": EPW_PATH}))
                assert loc["ok"] is True, loc
                rp = unwrap(await s.call_tool("set_run_period", {
                    "begin_month": 1, "begin_day": 1, "end_month": 1, "end_day": 2,
                }))
                assert rp["ok"] is True, rp
                applied = unwrap(await s.call_tool("apply_measure", {
                    "measure_dir": GENERATED_MEASURE_DIR, "arguments": {"file_name": CSV},
                }))
                assert applied["ok"] is True, applied
                saved = unwrap(await s.call_tool("save_osm_model", {"save_name": name}))
                assert saved["ok"] is True, saved
                osm = Path(saved["osm_path"])
                csv = osm.parent / name / "files" / CSV
                assert csv.is_file(), f"the generated CSV must be in the companion folder, saw {saved}"

                started = unwrap(await s.call_tool("run_simulation", {"osm_path": str(osm)}))
                assert started["ok"] is True, started
                assert started["epw_path"] is not None, "the example model's own EPW is staged"
                run = await _wait_done(s, started["run_id"])
                assert run["status"] == "success", run

                record = json.loads((Path(started["run_dir"]) / "run_record.json").read_text(encoding="utf-8"))
                assert record["seed_sha256"] == hashlib.sha256(osm.read_bytes()).hexdigest()
                assert record["weather_sha256"] == hashlib.sha256(Path(started["epw_path"]).read_bytes()).hexdigest()
                assert isinstance(record["resources_sha256"], str) and len(record["resources_sha256"]) == 64

                manifest = Path(started["run_dir"]).parent / f"{name}_seed_qaqc.json"
                first = unwrap(await s.call_tool("openstudio_analysis_preflight_seed", {
                    "seed_path": str(osm), "manifest_path": str(manifest),
                }))
                assert first["ok"] is True and first["ready"] is True, first
                assert first["reused"] is True and first["run_id"] == started["run_id"], first
                written = json.loads(manifest.read_text(encoding="utf-8"))
                assert written["resource_files"] == [CSV]
                assert written["resources_sha256"] == record["resources_sha256"], \
                    "the preflight's digest of the companion folder equals the run's digest of its staged files/"
                assert written["weather_sha256"] == record["weather_sha256"]
                assert written["weather_file"] is not None

                csv.write_bytes(csv.read_bytes() + b"0,0,0\n")
                second = unwrap(await s.call_tool("openstudio_analysis_preflight_seed", {
                    "seed_path": str(osm), "manifest_path": str(manifest),
                }))
                assert second["ok"] is True and second["ready"] is False, second
                assert second["reused"] is False and second["run_id"] != started["run_id"], second
                cancelled = unwrap(await s.call_tool("cancel_run", {"run_id": second["run_id"]}))
                assert cancelled["ok"] is True, cancelled

    asyncio.run(_run())
