"""Integration: the sim queue enforces MAX_CONCURRENCY across concurrent runs.

Launches more simulations than the cap and snapshots their states — the cap
must hold and the surplus must be queued. Runs are cancelled afterward so the
test stays fast (no full EnergyPlus completion needed).
"""
import asyncio
import uuid
from pathlib import Path

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


@pytest.mark.integration
def test_run_simulation_leaves_no_orphan_staging_dir():
    # Regression: run_simulation staged its OSW into a persistent /runs/<user>/sim_<id>
    # dir, then run_osw copied that into the real run dir — leaving the sim_* dir behind
    # forever (unbounded disk). Staging must be ephemeral; only the real run dir persists.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                cr = unwrap(await s.call_tool(
                    "create_example_osm", {"name": f"orphan_{uuid.uuid4().hex[:8]}"},
                ))
                assert cr["ok"] is True, cr

                rs = unwrap(await s.call_tool(
                    "run_simulation", {"osm_path": cr["osm_path"], "epw_path": EPW_PATH},
                ))
                assert rs["ok"] is True, rs
                run_dir = Path(rs["run_dir"])
                try:
                    assert run_dir.exists(), f"real run dir missing: {run_dir}"
                    assert not run_dir.name.startswith("sim_"), \
                        f"run_dir must be the real run hex dir, not a staging dir: {run_dir}"
                    # The user's run root must hold no sim_* staging leftovers.
                    orphans = sorted(p.name for p in run_dir.parent.glob("sim_*"))
                    assert orphans == [], f"orphan sim_* staging dir(s) left behind: {orphans}"
                finally:
                    await s.call_tool("cancel_run", {"run_id": rs["run_id"]})

        asyncio.run(_run())


@pytest.mark.integration
def test_sim_timeout_kills_long_run():
    # Validates: OSMCP_SIM_TIMEOUT_SECONDS caps wall-clock — a sim that exceeds it
    # is terminated and marked failed with a timeout error (runaway/DoS guard). A
    # 2s cap fires long before the example-model sim could ever finish.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none", "OSMCP_SIM_TIMEOUT_SECONDS": "2"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                cr = unwrap(await s.call_tool(
                    "create_example_osm", {"name": f"to_{uuid.uuid4().hex[:8]}"}))
                assert cr["ok"] is True, cr
                rs = unwrap(await s.call_tool(
                    "run_simulation", {"osm_path": cr["osm_path"], "epw_path": EPW_PATH}))
                assert rs["ok"] is True, rs
                run_id = rs["run_id"]

                status, err = rs["status"], ""
                for _ in range(120):  # up to 60s; the 2s cap fires far sooner
                    run = unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))["run"]
                    status, err = run["status"], (run.get("error") or "")
                    if status in ("success", "failed", "cancelled", "error"):
                        break
                    await asyncio.sleep(0.5)

                assert status == "failed", f"timed-out sim must be 'failed', got {status!r}"
                assert "cap" in err.lower() or "exceeded" in err.lower(), \
                    f"error should indicate the wall-clock timeout; got {err!r}"

        asyncio.run(_run())


@pytest.mark.integration
def test_cancelled_running_sim_stays_cancelled():
    # Regression: _refresh_status reclassified a cancelled (running) run as "failed"
    # on the next get_run_status — a killed pid reads as failure — breaking the
    # cancel contract and corrupting retention/audit (cancelled must stay terminal).
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    async def _status(s, run_id):
        return unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))["run"]["status"]

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                cr = unwrap(await s.call_tool(
                    "create_example_osm", {"name": f"cxl_{uuid.uuid4().hex[:8]}"}))
                assert cr["ok"] is True, cr
                rs = unwrap(await s.call_tool(
                    "run_simulation", {"osm_path": cr["osm_path"], "epw_path": EPW_PATH}))
                assert rs["ok"] is True, rs
                run_id = rs["run_id"]

                # Wait until the sim is actually running (pid set), not just queued.
                state = rs["status"]
                for _ in range(60):
                    state = await _status(s, run_id)
                    if state in ("running", "success", "failed"):
                        break
                    await asyncio.sleep(0.5)
                assert state == "running", f"sim never reached running (got {state!r})"

                cancelled = unwrap(await s.call_tool("cancel_run", {"run_id": run_id}))
                assert cancelled["ok"] is True, cancelled

                # Re-poll: a cancelled run must stay 'cancelled', never flip to 'failed'.
                for _ in range(3):
                    again = await _status(s, run_id)
                    assert again == "cancelled", f"cancelled run reclassified to {again!r}"
                    await asyncio.sleep(0.3)

        asyncio.run(_run())
