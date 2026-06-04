"""Integration: the sim queue enforces MAX_CONCURRENCY across concurrent runs.

Launches more simulations than the cap and snapshots their states — the cap
must hold and the surplus must be queued. Runs are cancelled afterward so the
test stays fast (no full EnergyPlus completion needed).
"""
import asyncio
import uuid

import pytest
from conftest import EPW_PATH, http_server, http_session, integration_enabled, unwrap


@pytest.mark.integration
def test_queue_caps_concurrent_sims():
    # Validates: with MAX_CONCURRENCY=1 (Docker default), 3 sims -> <=1 running, >=2 queued
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                cr = unwrap(await s.call_tool(
                    "create_example_osm", {"name": f"q_{uuid.uuid4().hex[:8]}"},
                ))
                assert cr["ok"] is True, cr
                osm = cr["osm_path"]

                run_ids = []
                for i in range(3):
                    r = unwrap(await s.call_tool(
                        "run_simulation",
                        {"osm_path": osm, "epw_path": EPW_PATH, "name": f"q{i}"},
                    ))
                    assert r["ok"] is True, f"run_simulation {i} failed: {r}"
                    run_ids.append(r["run_id"])

                statuses = [
                    unwrap(await s.call_tool("get_run_status", {"run_id": rid}))["run"]["status"]
                    for rid in run_ids
                ]
                running = statuses.count("running")
                queued = statuses.count("queued")
                # Cancel everything before asserting so we never leak sims on failure.
                for rid in run_ids:
                    await s.call_tool("cancel_run", {"run_id": rid})

                assert running <= 1, f"MAX_CONCURRENCY=1 must cap running at 1, got {statuses}"
                assert queued >= 2, f"3 sims at cap=1 must queue >=2, got {statuses}"

        asyncio.run(_run())
