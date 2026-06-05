"""Integration: run-retention MCP tools (cleanup_runs / pin_run / delete_run).

Drives real simulations to a terminal state, then exercises the disk-reclaim
contract end-to-end over HTTP: preview, pin-protection, and per-user-scoped delete.
"""
import asyncio
import uuid

import pytest
from conftest import (
    EPW_PATH,
    http_server,
    http_session,
    integration_enabled,
    poll_until_done,
    unwrap,
)


def _uniq(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:10]}"


@pytest.mark.integration
def test_cleanup_previews_pins_and_deletes():
    # Validates: cleanup_runs(dry_run) previews without deleting; a pinned run
    # survives a real cleanup; after unpin the same cleanup reclaims it.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                cr = unwrap(await s.call_tool("create_example_osm", {"name": _uniq("ret")}))
                assert cr["ok"] is True, cr
                rs = unwrap(await s.call_tool(
                    "run_simulation", {"osm_path": cr["osm_path"], "epw_path": EPW_PATH}))
                assert rs["ok"] is True, rs
                run_id = rs["run_id"]
                await poll_until_done(s, run_id)

                # --- preview: lists the run, deletes nothing ---
                prev = unwrap(await s.call_tool(
                    "cleanup_runs", {"older_than_days": 0, "dry_run": True}))
                assert prev["ok"] is True and prev["dry_run"] is True, prev
                assert run_id in {c["run_id"] for c in prev["candidates"]}, prev
                still = unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))
                assert still["ok"] is True, "dry_run must not delete the run"

                # --- pin, then real cleanup must SKIP the pinned run ---
                assert unwrap(await s.call_tool("pin_run", {"run_id": run_id}))["pinned"] is True
                after_pin = unwrap(await s.call_tool(
                    "cleanup_runs", {"older_than_days": 0, "dry_run": False}))
                assert run_id not in {d["run_id"] for d in after_pin["deleted"]}, after_pin
                assert unwrap(await s.call_tool(
                    "get_run_status", {"run_id": run_id}))["ok"] is True, "pinned run must survive"

                # --- unpin, then cleanup reclaims it for real ---
                assert unwrap(await s.call_tool("unpin_run", {"run_id": run_id}))["was_pinned"] is True
                final = unwrap(await s.call_tool(
                    "cleanup_runs", {"older_than_days": 0, "dry_run": False}))
                assert run_id in {d["run_id"] for d in final["deleted"]}, final
                assert final["freed_mb"] > 0, f"reclaiming a real sim must free MB: {final}"
                gone = unwrap(await s.call_tool("get_run_status", {"run_id": run_id}))
                assert gone["ok"] is False and "unknown run_id" in gone["error"].lower(), gone

        asyncio.run(_run())


@pytest.mark.integration
def test_delete_run_is_user_scoped():
    # Regression: delete_run must only touch the caller's own run — another
    # session's run_id is unknown, never deletable.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s1, http_session(url) as s2:
                cr = unwrap(await s1.call_tool("create_example_osm", {"name": _uniq("del")}))
                assert cr["ok"] is True, cr
                rs = unwrap(await s1.call_tool(
                    "run_simulation", {"osm_path": cr["osm_path"], "epw_path": EPW_PATH}))
                assert rs["ok"] is True, rs
                run_id = rs["run_id"]
                await poll_until_done(s1, run_id)

                # s2 cannot delete s1's run
                other = unwrap(await s2.call_tool("delete_run", {"run_id": run_id}))
                assert other["ok"] is False, f"s2 must not delete s1's run: {other}"
                assert "unknown run_id" in other["error"].lower(), other
                assert unwrap(await s1.call_tool(
                    "get_run_status", {"run_id": run_id}))["ok"] is True, "run must still exist"

                # s1 deletes its own run
                mine = unwrap(await s1.call_tool("delete_run", {"run_id": run_id}))
                assert mine["ok"] is True and mine["deleted"] is True, mine
                assert mine["freed_mb"] > 0, f"deleting a real sim must free MB: {mine}"
                gone = unwrap(await s1.call_tool("get_run_status", {"run_id": run_id}))
                assert gone["ok"] is False and "unknown run_id" in gone["error"].lower(), gone

        asyncio.run(_run())
