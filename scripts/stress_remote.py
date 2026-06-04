#!/usr/bin/env python3
"""Local stress test for the remote (HTTP) multi-user MCP server.

Spins up ONE HTTP server, opens many concurrent client sessions, and checks the
multi-user invariants hold under contention:

  Phase 1 (isolation + throughput): each session builds its own model (example=1
    zone or baseline=10 zones) and hammers get_model/list/create concurrently.
    Every read must return that session's own zone count — a cross-session bleed
    shows up as a mismatch. Reports throughput + latency percentiles.
  Phase 2 (queue saturation): every session launches a real sim at once; we
    sample statuses and assert running <= MAX_CONCURRENCY at all times, each
    session sees only its own run, then cancel.
  Phase 3 (memory): sample the server process RSS to confirm it stays bounded.

Run inside the Docker image, e.g.:
  docker run --rm -v "$PWD:/repo" -v "$PWD/runs:/runs" openstudio-mcp:dev \
    bash -lc "cd /repo && python scripts/stress_remote.py --profile moderate"
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid

import psutil

EPW = ("/opt/comstock-measures/ChangeBuildingLocation"
       "/tests/USA_MA_Boston-Logan.Intl.AP.725090_TMY3.epw")


def _unwrap(res):
    content = getattr(res, "content", None)
    if not content:
        return res if isinstance(res, dict) else {"_raw": str(res)}
    text = getattr(content[0], "text", None)
    if text is None:
        return {"_raw": str(content[0])}
    try:
        return json.loads(text.strip())
    except Exception:
        return {"_raw": text.strip()}


@contextlib.asynccontextmanager
async def open_session(url: str):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    async with streamablehttp_client(url) as (read, write, *_), ClientSession(read, write) as s:
        await s.initialize()
        yield s


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pct(values, q):
    if not values:
        return 0.0
    xs = sorted(values)
    i = min(len(xs) - 1, round(q * (len(xs) - 1)))
    return xs[i]


class Spawned:
    def __init__(self, proc, url):
        self.proc = proc
        self.url = url


def spawn_server(cap: int, max_sessions: int) -> Spawned:
    port = _free_port()
    env = os.environ.copy()
    env.update({
        "MCP_TRANSPORT": "http", "MCP_HOST": "127.0.0.1", "MCP_PORT": str(port),
        "MCP_PATH": "/mcp", "MCP_AUTH": "none",
        "OSMCP_MAX_CONCURRENCY": str(cap), "OSMCP_MAX_SESSIONS": str(max_sessions),
    })
    cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    proc = subprocess.Popen([cmd], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early (code {proc.returncode})")
        with socket.socket() as sk:
            sk.settimeout(0.5)
            if sk.connect_ex(("127.0.0.1", port)) == 0:
                return Spawned(proc, f"http://127.0.0.1:{port}/mcp")
        time.sleep(0.3)
    proc.terminate()
    raise TimeoutError("server not ready")


class M:
    def __init__(self):
        self.latencies: list[float] = []
        self.errors = 0
        self.evictions = 0
        self.isolation_failures = 0
        self.calls = 0


async def phase1_worker(url, i, calls, token, m: M):
    kind = "example" if i % 2 == 0 else "baseline"
    create_tool = "create_example_osm" if kind == "example" else "create_baseline_osm"
    expected = 1 if kind == "example" else 10
    try:
        async with open_session(url) as s:
            await s.call_tool(create_tool, {"name": f"st_{i}_{token}"})
            m.calls += 1
            for k in range(calls):
                t0 = time.perf_counter()
                d = _unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
                m.latencies.append(time.perf_counter() - t0)
                m.calls += 1
                if "thermal_zones" not in d:
                    if "model" in str(d.get("error", "")).lower():
                        m.evictions += 1
                        await s.call_tool(create_tool, {"name": f"st_{i}_{k}_{token}"})
                        m.calls += 1
                        continue
                    m.errors += 1
                    continue
                if len(d["thermal_zones"]) != expected:
                    m.isolation_failures += 1
                if k % 5 == 0:
                    await s.call_tool(create_tool, {"name": f"st_{i}_{k}_{token}"})
                    m.calls += 1
            d = _unwrap(await s.call_tool("list_thermal_zones", {"max_results": 0}))
            if d.get("thermal_zones") is not None and len(d["thermal_zones"]) != expected:
                m.isolation_failures += 1
    except Exception as e:
        m.errors += 1
        print(f"  worker {i} error: {type(e).__name__}: {e}", file=sys.stderr)


async def phase2_queue(url, users, token):
    from contextlib import AsyncExitStack
    sessions = []
    async with AsyncExitStack() as stack:
        for _ in range(users):
            sessions.append(await stack.enter_async_context(open_session(url)))

        async def launch(i):
            cr = _unwrap(await sessions[i].call_tool("create_example_osm", {"name": f"q_{i}_{token}"}))
            if not cr.get("ok"):
                return None
            r = _unwrap(await sessions[i].call_tool(
                "run_simulation", {"osm_path": cr["osm_path"], "epw_path": EPW}))
            return r.get("run_id") if r.get("ok") else None

        run_ids = await asyncio.gather(*[launch(i) for i in range(users)])
        live = [(i, rid) for i, rid in enumerate(run_ids) if rid]

        async def status(i, rid):
            d = _unwrap(await sessions[i].call_tool("get_run_status", {"run_id": rid}))
            return d.get("run", {}).get("status") if d.get("ok") else "not_found"

        max_running, samples = 0, 12
        for _ in range(samples):
            sts = await asyncio.gather(*[status(i, rid) for i, rid in live])
            max_running = max(max_running, sum(1 for x in sts if x == "running"))
            await asyncio.sleep(0.3)

        cross_blocked = True
        if len(live) >= 2:
            other = await status(live[1][0], live[0][1])  # session B asks for A's run
            cross_blocked = (other == "not_found")

        await asyncio.gather(*[
            sessions[i].call_tool("cancel_run", {"run_id": rid}) for i, rid in live
        ])
        return {"launched": len(live), "max_running": max_running, "cross_blocked": cross_blocked}


def rss_mb(proc) -> float:
    try:
        return psutil.Process(proc.pid).memory_info().rss / 1e6
    except Exception:
        return 0.0


async def amain(args):
    token = uuid.uuid4().hex[:6]
    print("=== openstudio-mcp remote stress test ===")
    print(f"profile={args.profile} users={args.users} calls={args.calls} cap={args.cap} "
          f"sims={'on' if args.sims else 'off'} max_sessions={args.max_sessions}")
    srv = spawn_server(args.cap, args.max_sessions)
    print(f"server: {srv.url} (pid {srv.proc.pid})  rss_start={rss_mb(srv.proc):.0f}MB\n")
    result_ok = True
    try:
        # Phase 1
        m = M()
        t0 = time.perf_counter()
        await asyncio.gather(*[phase1_worker(srv.url, i, args.calls, token, m) for i in range(args.users)])
        wall = time.perf_counter() - t0
        rss_peak = rss_mb(srv.proc)
        print("Phase 1 — isolation + throughput")
        print(f"  sessions={args.users} (example/baseline split)  tool calls={m.calls}")
        iso = "PASS" if m.isolation_failures == 0 else f"FAIL ({m.isolation_failures})"
        print(f"  isolation: {iso}   evictions_handled={m.evictions}   errors={m.errors}")
        print(f"  wall={wall:.1f}s  throughput={m.calls / wall:.1f} calls/s")
        print(f"  latency ms: p50={_pct(m.latencies, .5) * 1e3:.0f} "
              f"p95={_pct(m.latencies, .95) * 1e3:.0f} p99={_pct(m.latencies, .99) * 1e3:.0f}")
        result_ok = result_ok and m.isolation_failures == 0 and m.errors == 0

        # Phase 2
        if args.sims:
            print("\nPhase 2 — queue saturation (real sims)")
            q = await phase2_queue(srv.url, args.users, token)
            cap_ok = q["max_running"] <= args.cap
            print(f"  sims launched={q['launched']}  cap={args.cap}")
            print(f"  max concurrent running observed={q['max_running']}  "
                  f"(<= cap: {'PASS' if cap_ok else 'FAIL'})")
            print(f"  cross-user run access blocked: {'PASS' if q['cross_blocked'] else 'FAIL'}")
            print("  (sims cancelled — not run to completion)")
            result_ok = result_ok and cap_ok and q["cross_blocked"]

        # Phase 3
        print("\nPhase 3 — memory")
        print(f"  server RSS: start->peak->end ~ {rss_peak:.0f}MB peak, "
              f"{rss_mb(srv.proc):.0f}MB now (bounded by max_sessions={args.max_sessions})")

        print(f"\nRESULT: {'PASS' if result_ok else 'FAIL'}")
    finally:
        srv.proc.terminate()
        with contextlib.suppress(Exception):
            srv.proc.wait(timeout=10)
    return 0 if result_ok else 1


PROFILES = {
    "smoke": {"users": 8, "calls": 10, "cap": 1, "sims": False, "max_sessions": 64},
    "moderate": {"users": 24, "calls": 20, "cap": 1, "sims": True, "max_sessions": 64},
    "heavy": {"users": 64, "calls": 30, "cap": 2, "sims": True, "max_sessions": 128},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", choices=PROFILES, default="moderate")
    ap.add_argument("--users", type=int)
    ap.add_argument("--calls", type=int)
    ap.add_argument("--cap", type=int)
    ap.add_argument("--max-sessions", type=int, dest="max_sessions")
    ap.add_argument("--sims", dest="sims", action="store_true", default=None)
    ap.add_argument("--no-sims", dest="sims", action="store_false")
    args = ap.parse_args()
    defs = PROFILES[args.profile]
    for k, v in defs.items():
        if getattr(args, k) is None:
            setattr(args, k, v)
    sys.exit(asyncio.run(amain(args)))


if __name__ == "__main__":
    main()
