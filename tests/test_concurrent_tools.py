"""Regression test: concurrent tool calls must not corrupt each other's responses.

Root cause (fixed): the FastMCP middleware held os.dup2() on process-global fd 1
(stdout) for the duration of each tool call. FastMCP dispatches sync tools via
anyio.to_thread.run_sync so two tools CAN run concurrently. Thread B would save
the "corrupted" fd 1 (pointing at stderr) as its saved value, then permanently
redirect stdout to stderr after Thread A restored it — causing all subsequent
tool responses to be lost.

The fix: middleware removed; suppress_openstudio_warnings() now wraps only
specific OpenStudio SDK callsites (model.save, VersionTranslator.loadModel,
BCLMeasure(), DesignDay(), etc.). threading.RLock ensures two worker threads
cannot interleave their fd redirects; same-thread nested calls are safe.

NOTE: This test verifies the middleware-removal fix by confirming both concurrent
calls succeed. The sleep(0.5) races get_server_status against the long
create_baseline_model() build phase (which has no suppression after a78070e),
not the narrow model.save() window. The RLock mechanism is separately covered by
the nested-entry path exercised in create_baseline_osm → set_constructions.
"""
import asyncio
import pytest

from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client


@pytest.mark.integration
def test_concurrent_tool_calls_both_respond():
    # Regression: concurrent long-running tool + trivial tool must both return responses.
    # Previously, create_baseline_osm held fd 1 → stderr the entire time; when
    # get_server_status completed concurrently, its response was written to stderr
    # and the client received nothing (timeout / MCP error -32001).
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable MCP integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # Fire both requests concurrently — create_baseline_osm is slow
                # (several seconds), get_server_status is near-instant.  Before
                # the fix, get_server_status's response was silently dropped.
                baseline_task = asyncio.create_task(
                    session.call_tool("create_baseline_osm", {"name": "concurrent_test", "num_floors": 1})
                )
                # Small delay so baseline_osm gets into its fd-redirect window
                await asyncio.sleep(0.5)
                status_task = asyncio.create_task(
                    session.call_tool("get_server_status", {})
                )

                baseline_res, status_res = await asyncio.wait_for(
                    asyncio.gather(baseline_task, status_task),
                    timeout=120,
                )

                baseline = unwrap(baseline_res)
                status = unwrap(status_res)

                # Both must succeed — if either is missing, the race is back
                assert isinstance(baseline, dict), f"baseline result is not a dict: {baseline_res!r}"
                assert isinstance(status, dict), f"status result is not a dict: {status_res!r}"
                assert baseline.get("ok") is True, f"create_baseline_osm failed: {baseline}"
                assert status.get("ok") is True, f"get_server_status failed: {status}"
                assert "run_root" in status, f"get_server_status missing expected keys: {status}"

    asyncio.run(_run())
