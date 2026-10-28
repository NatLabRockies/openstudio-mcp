"""Integration: get_run_status poll hint + server-side wait over HTTP (issue #200).

Real EnergyPlus runs, real waits (kept to a few seconds; runs are cancelled so
no test needs a full simulation). Nothing is mocked.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
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
    # Validates: wait_seconds=2 on a running sim holds the call at least 2 s and returns
    # the run still non-terminal with wait_exhausted=True. The upper bound is a watchdog
    # that distinguishes a 2 s wait from the 50 s cap on a loaded runner; exact deadline
    # accounting is pinned by the unit tests
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
                assert 2.0 <= held < 15.0, f"wait_seconds=2 held the call for {held:.2f}s"

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
                assert held < 10.0, f"terminal run must not be waited on (cap 50 s), held {held:.2f}s"

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
                assert held < 15.0, f"wait must return within a few ticks of cancel (cap 30 s), held {held:.2f}s"
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
                assert held < 10.0, f"unknown/foreign lookups must not wait (cap 50 s), held {held:.2f}s"

        asyncio.run(_run())


def _wait_exit_line(log: Path, run_id: str, budget: float) -> tuple[str | None, float]:
    """Poll the server log for the waiter's exit line; return (reason, seconds waited)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < budget:
        text = log.read_text(encoding="utf-8", errors="replace")
        m = re.search(rf"\[run_wait\] run={re.escape(run_id)} reason=(\w+) active=0", text)
        if m:
            return m.group(1), time.monotonic() - t0
        time.sleep(0.25)
    return None, time.monotonic() - t0


@pytest.mark.integration
def test_abandoned_wait_is_bounded_by_cap():
    # Validates: the only bound on an abandoned held call is wait_seconds. Verified
    # 2026-10-28 (fastmcp 3.x streamable HTTP): neither a client-side task cancel
    # (notifications/cancelled), the session DELETE on client close, nor a hard TCP drop
    # cancels the in-flight handler; only server shutdown does. So a killed client's
    # waiter must exit at the cap (reason=exhausted) plus one tick, never linger past it
    _skip_unless_integration()
    token = uuid.uuid4().hex
    env = {"MCP_AUTH": "token", "MCP_TOKENS": json.dumps({token: "dropper"})}
    cap = 5
    with http_server(env) as (url, _proc):
        log = _server_log(url)

        async def _run():
            async with http_session(url, token=token) as owner:
                # Three runs at MAX_CONCURRENCY=1: the third stays queued (non-terminal)
                # for two full simulations, longer than the cap under test.
                cr = unwrap(await owner.call_tool("create_example_osm", {"name": f"drop_{uuid.uuid4().hex[:8]}"}))
                assert cr["ok"] is True, cr
                run_ids = []
                for i in range(3):
                    r = unwrap(await owner.call_tool(
                        "run_simulation",
                        {"osm_path": cr["osm_path"], "epw_path": EPW_PATH, "name": f"drop{i}"},
                    ))
                    assert r["ok"] is True, r
                    run_ids.append(r["run_id"])
                run_id = run_ids[-1]
                try:
                    client = subprocess.Popen(  # noqa: S603 - argv is our own interpreter
                        [sys.executable, "-c", _ABANDONING_CLIENT, url, token, run_id, str(cap)],
                        cwd=str(Path(__file__).parent), stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True,
                    )
                    try:
                        first = await asyncio.to_thread(client.stdout.readline)
                        assert first.strip() == "CALLING", f"client did not start: {first!r}"
                        t_call = time.monotonic()   # the request is on the wire from here
                        await asyncio.sleep(1.5)   # the call is now held server-side
                        assert client.poll() is None, "client exited before it was killed"
                        client.kill()
                        client.wait(timeout=10)
                    finally:
                        if client.poll() is None:
                            client.kill()
                    reason, _ = await asyncio.to_thread(
                        _wait_exit_line, log, run_id, cap + 5.0,
                    )
                    lifetime = time.monotonic() - t_call   # request sent -> waiter exit seen
                finally:
                    for rid in run_ids:
                        await owner.call_tool("cancel_run", {"run_id": rid})
                assert reason in ("exhausted", "cancelled"), (
                    f"waiter exit reason {reason!r} after {lifetime:.1f}s (cap {cap}s); log tail:\n"
                    + log.read_text(encoding="utf-8", errors="replace")[-2000:]
                )
                # cap + one 1 s tick + request/log-polling allowance, measured from submission
                assert lifetime <= cap + 1.0 + 3.0, (
                    f"abandoned wait outlived its cap: {lifetime:.1f}s from submission, cap {cap}s"
                )

        asyncio.run(_run())


_ABANDONING_CLIENT = """
import asyncio, sys
from conftest import http_session

url, token, run_id, cap = sys.argv[1:5]

async def main():
    async with http_session(url, token=token) as s:
        print("CALLING", flush=True)
        await s.call_tool("get_run_status", {"run_id": run_id, "wait_seconds": int(cap)})
        print("RETURNED", flush=True)

asyncio.run(main())
"""
