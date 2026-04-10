"""Regression test for issue #42: stdout suppression race condition.

The global FastMCP middleware held os.dup2() on fd 1 (stdout→stderr) for
the entire tool call. FastMCP dispatches sync tools via
anyio.to_thread.run_sync, so two tools CAN run concurrently. When Thread A
held the redirect, Thread B's JSON-RPC response goes to stderr and the
client receives nothing → MCP error -32001 timeout.

This test fires a slow tool (create_baseline_osm, several seconds) and a
fast tool (get_server_status, near-instant) concurrently. On buggy code,
get_server_status's response is lost → timeout. After the fix, both return.
"""
import asyncio
import pytest

from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_concurrent_tool_calls_both_respond():
    # Regression: issue #42 — concurrent tool calls lost responses due to
    # global stdout suppression middleware redirecting fd 1 for entire tool duration.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # --- Arrange ---
                # Fire slow tool first
                baseline_task = asyncio.create_task(
                    session.call_tool("create_baseline_osm", {
                        "name": "concurrent_race_test", "num_floors": 1,
                    })
                )
                # Small delay so baseline_osm enters its execution window
                await asyncio.sleep(0.5)

                # --- Act ---
                # Fire fast tool while slow tool holds middleware fd redirect
                status_task = asyncio.create_task(
                    session.call_tool("get_server_status", {})
                )

                # --- Assert ---
                # 30s timeout: get_server_status should return in <1s.
                # If it times out, the race condition is present — the response
                # went to stderr and the client never received it.
                try:
                    baseline_res, status_res = await asyncio.wait_for(
                        asyncio.gather(baseline_task, status_task),
                        timeout=30,
                    )
                except asyncio.TimeoutError:
                    pytest.fail(
                        "Concurrent tool call timed out — stdout suppression race "
                        "condition is present (issue #42). get_server_status response "
                        "was likely written to stderr while create_baseline_osm held "
                        "the fd 1 redirect."
                    )

                baseline = unwrap(baseline_res)
                status = unwrap(status_res)

                assert baseline.get("ok") is True, f"create_baseline_osm failed: {baseline}"
                assert status.get("ok") is True, f"get_server_status failed: {status}"
                assert "run_root" in status, f"status missing expected keys: {status}"

    asyncio.run(_run())


@pytest.mark.integration
def test_concurrent_fast_tools_both_respond():
    # Regression: issue #42 — even two fast tools can race if both enter
    # the middleware's fd redirect window simultaneously.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Fire two fast tools concurrently
                task_a = asyncio.create_task(
                    session.call_tool("get_server_status", {})
                )
                task_b = asyncio.create_task(
                    session.call_tool("get_server_status", {})
                )

                try:
                    res_a, res_b = await asyncio.wait_for(
                        asyncio.gather(task_a, task_b),
                        timeout=15,
                    )
                except asyncio.TimeoutError:
                    pytest.fail(
                        "Concurrent fast tool calls timed out — stdout suppression "
                        "race condition (issue #42)."
                    )

                a = unwrap(res_a)
                b = unwrap(res_b)

                assert a.get("ok") is True, f"First get_server_status failed: {a}"
                assert b.get("ok") is True, f"Second get_server_status failed: {b}"

    asyncio.run(_run())
