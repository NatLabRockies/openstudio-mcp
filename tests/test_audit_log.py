"""Audit logging: every tool call and the full sim lifecycle are recorded."""
import asyncio
import json
import uuid
from pathlib import Path

import pytest
from conftest import EPW_PATH, http_server, http_session, integration_enabled, poll_until_done, unwrap


@pytest.mark.integration
def test_audit_records_tool_calls_and_sim_lifecycle():
    # Validates: AuditMiddleware logs a tool_call line per invocation, and the sim
    # dispatcher logs sim_queued/sim_launched/sim_finished — to MCP_AUDIT_FILE.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    token = uuid.uuid4().hex[:8]
    audit_path = f"/runs/audit_{token}.jsonl"
    with http_server({"MCP_AUTH": "none", "MCP_AUDIT_FILE": audit_path}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                cr = unwrap(await s.call_tool("create_example_osm", {"name": f"audit_{token}"}))
                assert cr["ok"] is True, cr
                r = unwrap(await s.call_tool(
                    "run_simulation", {"osm_path": cr["osm_path"], "epw_path": EPW_PATH}))
                assert r["ok"] is True, r
                await poll_until_done(s, r["run_id"])

        asyncio.run(_run())

        lines = [json.loads(ln) for ln in Path(audit_path).read_text().splitlines() if ln.strip()]
        events = [e["event"] for e in lines]
        tools = {e.get("tool") for e in lines if e["event"] == "tool_call"}

        # Every tool invocation is recorded.
        assert "create_example_osm" in tools, f"tool calls not audited: {tools}"
        assert "run_simulation" in tools
        # The full sim lifecycle is recorded (the background-thread events too).
        assert "sim_queued" in events, f"sim lifecycle incomplete: {sorted(set(events))}"
        assert "sim_launched" in events
        assert "sim_finished" in events

        # A tool_call line carries identity, outcome, and timing.
        tc = next(e for e in lines
                  if e["event"] == "tool_call" and e.get("tool") == "create_example_osm")
        assert tc.get("ok") is True, tc
        assert "user" in tc and "ms" in tc, tc
        fin = next(e for e in lines if e["event"] == "sim_finished")
        assert fin.get("status") in ("success", "failed"), fin
