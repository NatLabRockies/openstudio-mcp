"""Integration: get_run_status poll hint + server-side wait over HTTP (issue #200).

Real EnergyPlus runs, real waits (kept to a few seconds; runs are cancelled so
no test needs a full simulation). Nothing is mocked.
"""
import asyncio
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from conftest import EPW_PATH, http_server, http_session, integration_enabled, unwrap

TERMINAL = {"success", "failed", "cancelled", "error"}


def _skip_unless_integration():
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")


def _server_log(url: str) -> Path:
    port = urlparse(url).port
    run_root = Path(os.environ.get("OPENSTUDIO_MCP_RUN_ROOT",
                                   os.environ.get("OSMCP_RUN_ROOT", "/runs")))
    return run_root / f"_httpsrv_{port}.log"


async def _start_sim(s, label: str) -> str:
    cr = unwrap(await s.call_tool("create_example_osm", {"name": f"{label}_{uuid.uuid4().hex[:8]}"}))
    assert cr["ok"] is True, cr
    rs = unwrap(await s.call_tool(
        "run_simulation", {"osm_path": cr["osm_path"], "epw_path": EPW_PATH, "name": label},
    ))
    assert rs["ok"] is True, rs
    return rs["run_id"]


@pytest.mark.integration
def test_status_fields_running_then_cancelled():
    # Validates: a running run carries elapsed_seconds >= 0, no queue_position and the
    # 30 s first-tier hint; after cancel the hint is 0 and elapsed equals ended - started
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                run_id = await _start_sim(s, "fields")
                try:
                    res = unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))
                    assert res["ok"] is True, res
                    run = res["run"]
                    # run_osw dispatches synchronously under the cap, so the first run is running
                    assert run["status"] == "running", run
                    assert run["queue_position"] is None
                    assert run["elapsed_seconds"] >= 0.0
                    assert run["elapsed_seconds"] < 60.0
                    assert res["poll_interval_seconds"] == 30
                    assert res["wait_exhausted"] is False
                finally:
                    c = unwrap(await s.call_tool("cancel_run", {"run_id": run_id}))
                    assert c["ok"] is True, c

                res = unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))
                run = res["run"]
                assert run["status"] == "cancelled", run
                assert res["poll_interval_seconds"] == 0
                assert run["elapsed_seconds"] == pytest.approx(
                    run["ended_at"] - run["started_at"], abs=0.01,
                )

        asyncio.run(_run())


@pytest.mark.integration
def test_queued_runs_report_position_and_scaled_hint():
    # Validates: with MAX_CONCURRENCY=1 the 2nd and 3rd runs are queue_position 1 and 2
    # with hints 30 and 60 (30 s per slot), so an agent behind a queue waits proportionally
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                cr = unwrap(await s.call_tool("create_example_osm", {"name": f"qp_{uuid.uuid4().hex[:8]}"}))
                assert cr["ok"] is True, cr
                run_ids = []
                for i in range(3):
                    r = unwrap(await s.call_tool(
                        "run_simulation",
                        {"osm_path": cr["osm_path"], "epw_path": EPW_PATH, "name": f"qp{i}"},
                    ))
                    assert r["ok"] is True, r
                    run_ids.append(r["run_id"])
                try:
                    snaps = [unwrap(await s.call_tool("get_run_status", {"run_id": rid}))
                             for rid in run_ids]
                finally:
                    for rid in run_ids:
                        await s.call_tool("cancel_run", {"run_id": rid})

                queued = [(sn["run"]["queue_position"], sn["poll_interval_seconds"])
                          for sn in snaps if sn["run"]["status"] == "queued"]
                assert queued == [(1, 30), (2, 60)], (
                    f"3 sims at cap=1 must queue slots 1 and 2 with 30 s per slot, got {snaps}"
                )
                assert all(sn["run"]["elapsed_seconds"] is None
                           for sn in snaps if sn["run"]["status"] == "queued")

        asyncio.run(_run())


@pytest.mark.integration
def test_wait_seconds_exhausts_on_running_sim():
    # Validates: wait_seconds=2 on a running sim holds the call about 2 s and returns the
    # run still non-terminal with wait_exhausted=True, never overrunning by more than one
    # 1 s tick plus a snapshot
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                run_id = await _start_sim(s, "exhaust")
                try:
                    t0 = time.monotonic()
                    res = unwrap(await s.call_tool(
                        "get_run_status", {"run_id": run_id, "wait_seconds": 2},
                    ))
                    held = time.monotonic() - t0
                finally:
                    await s.call_tool("cancel_run", {"run_id": run_id})
                assert res["ok"] is True, res
                assert res["run"]["status"] == "running", res
                assert res["wait_exhausted"] is True
                assert 2.0 <= held < 4.0, f"wait_seconds=2 held the call for {held:.2f}s"

        asyncio.run(_run())


@pytest.mark.integration
def test_wait_on_terminal_run_returns_at_once():
    # Validates: wait_seconds=50 on an already-terminal run returns immediately (no
    # sleep for a finished run) with wait_exhausted False and a 0 hint
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                run_id = await _start_sim(s, "term")
                c = unwrap(await s.call_tool("cancel_run", {"run_id": run_id}))
                assert c["ok"] is True, c
                t0 = time.monotonic()
                res = unwrap(await s.call_tool(
                    "get_run_status", {"run_id": run_id, "wait_seconds": 50},
                ))
                held = time.monotonic() - t0
                assert res["run"]["status"] == "cancelled", res
                assert res["wait_exhausted"] is False
                assert res["poll_interval_seconds"] == 0
                assert held < 2.0, f"terminal run must not be waited on, held {held:.2f}s"

        asyncio.run(_run())


@pytest.mark.integration
def test_cancel_mid_wait_returns_cancelled_promptly():
    # Validates: a held get_run_status sees cancel_run from another session within a few
    # 1 s ticks and returns status=cancelled with wait_exhausted False, and the run stays
    # cancelled on the next plain snapshot
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                run_id = await _start_sim(s, "midcancel")

                async def _cancel_later():
                    await asyncio.sleep(1.5)
                    return unwrap(await s.call_tool("cancel_run", {"run_id": run_id}))

                t0 = time.monotonic()
                waited, cancelled = await asyncio.gather(
                    s.call_tool("get_run_status", {"run_id": run_id, "wait_seconds": 30}),
                    _cancel_later(),
                )
                held = time.monotonic() - t0
                res = unwrap(waited)
                assert cancelled["ok"] is True, cancelled
                assert res["run"]["status"] == "cancelled", res
                assert res["wait_exhausted"] is False
                assert held < 6.0, f"wait must return within a few ticks of cancel, held {held:.2f}s"
                again = unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))
                assert again["run"]["status"] == "cancelled"

        asyncio.run(_run())


@pytest.mark.integration
def test_unknown_and_foreign_runs_return_without_waiting():
    # Validates: wait_seconds=50 on an unknown run id, and on another session's run,
    # returns the existing unknown-run shape at once; the wait never leaks existence
    # (or ownership) through latency
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s1, http_session(url) as s2:
                run_id = await _start_sim(s1, "foreign")
                try:
                    t0 = time.monotonic()
                    foreign = unwrap(await s2.call_tool(
                        "get_run_status", {"run_id": run_id, "wait_seconds": 50},
                    ))
                    unknown = unwrap(await s2.call_tool(
                        "get_run_status", {"run_id": "nope_" + uuid.uuid4().hex, "wait_seconds": 50},
                    ))
                    held = time.monotonic() - t0
                finally:
                    await s1.call_tool("cancel_run", {"run_id": run_id})
                for res in (foreign, unknown):
                    assert res["ok"] is False, res
                    assert "unknown run_id" in res["error"].lower(), res
                    assert "wait_exhausted" not in res
                assert held < 2.0, f"unknown/foreign lookups must not wait, held {held:.2f}s"

        asyncio.run(_run())


@pytest.mark.integration
def test_client_disconnect_mid_wait_releases_waiter():
    # Validates: when the client drops the connection during a held call the server-side
    # waiter exits (logged `[run_wait] ... active=0`) well before the requested cap, so
    # abandoned waits never pile up
    _skip_unless_integration()
    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        log = _server_log(url)

        async def _run():
            async with http_session(url) as owner:
                run_id = await _start_sim(owner, "drop")
                try:
                    async def _abandon():
                        async with http_session(url) as s:
                            # Give up on the held call after 1 s; leaving the context closes
                            # the HTTP client and drops the in-flight POST stream.
                            task = asyncio.create_task(s.call_tool(
                                "get_run_status", {"run_id": run_id, "wait_seconds": 40},
                            ))
                            await asyncio.sleep(1.0)
                            task.cancel()
                            with pytest.raises(asyncio.CancelledError):
                                await task

                    await _abandon()
                    t0 = time.monotonic()
                    exited = None
                    while time.monotonic() - t0 < 10.0:
                        text = log.read_text(encoding="utf-8", errors="replace")
                        m = re.search(rf"\[run_wait\] run={run_id} .*active=0", text)
                        if m:
                            exited = time.monotonic() - t0
                            break
                        await asyncio.sleep(0.25)
                finally:
                    await owner.call_tool("cancel_run", {"run_id": run_id})
                assert exited is not None, (
                    "waiter did not exit within 10 s of the client disconnect "
                    "(cap was 40 s); server log:\n" + log.read_text(errors="replace")[-3000:]
                )

        asyncio.run(_run())
