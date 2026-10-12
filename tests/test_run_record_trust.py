"""Over MCP: nothing a tenant writes into its own run_record.json or run dir can reach another
tenant's run, and a forged pid is never signalled (run-record trust, #179 sibling)."""
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid

import pytest
from conftest import http_server, http_session, integration_enabled, unwrap

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    not integration_enabled(), reason="Set RUN_OPENSTUDIO_INTEGRATION=1",
)]


def _record(path, **override) -> dict:
    run_dir = path
    data = {
        "run_id": run_dir.name, "user_key": run_dir.parent.name, "name": "x", "status": "failed",
        "created_at": 1.0, "started_at": 1.5, "ended_at": 2.0, "pid": None,
        "run_dir": str(run_dir), "osw_path": str(run_dir / "workflow.osw"), "epw_path": None,
        "exit_code": 1, "error": None,
    }
    data.update(override)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run_record.json").write_text(json.dumps(data), encoding="utf-8")
    return data


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlinks/processes")
def test_forged_run_record_cannot_reach_sibling_tenant_or_kill_stranger():
    # Regression: a record forged by alice's sandboxed measure (run_dir -> bob's run, pid ->
    # any process) made get_run_logs/get_run_status read and rewrite bob's run and let
    # cancel_run kill the pid as root; a symlinked record was followed too
    from mcp_server.config import RUN_ROOT

    tag = uuid.uuid4().hex[:8]
    alice_token, bob_token = uuid.uuid4().hex, uuid.uuid4().hex
    bob_run = RUN_ROOT / "bob" / f"run_victim_{tag}"
    victim_record = json.dumps(_record(bob_run, status="success"))
    (bob_run / "openstudio.log").write_text("BOBLOG\n", encoding="utf-8")
    forged = RUN_ROOT / "alice" / f"run_forged_{tag}"
    linked = RUN_ROOT / "alice" / f"run_linked_{tag}"
    stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], cwd="/")  # noqa: S603 - fixed argv
    try:
        time.sleep(0.2)
        _record(forged, run_dir=str(bob_run), status="running", pid=stranger.pid)
        linked.mkdir(parents=True)
        (linked / "run_record.json").symlink_to(bob_run / "run_record.json")
        env = {"MCP_AUTH": "token", "MCP_TOKENS": json.dumps({alice_token: "alice", bob_token: "bob"})}
        with http_server(env) as (url, _proc):
            async def run():
                async with http_session(url, token=alice_token) as alice:
                    logs = unwrap(await alice.call_tool("get_run_logs", {"run_id": forged.name, "tail": 5}))
                    assert logs["ok"] is True, logs
                    assert logs["text"] == "" and "BOBLOG" not in json.dumps(logs)
                    status = unwrap(await alice.call_tool("get_run_status", {"run_id": forged.name}))
                    assert status["ok"] is True, status
                    assert status["run"]["run_dir"] == str(forged)
                    assert status["run"]["pid"] is None
                    cancelled = unwrap(await alice.call_tool("cancel_run", {"run_id": forged.name}))
                    assert cancelled == {"ok": True, "run_id": forged.name, "cancelled": True}
                    via_link = unwrap(await alice.call_tool("get_run_status", {"run_id": linked.name}))
                    assert via_link["ok"] is False and "Unknown run_id" in via_link["error"], via_link
            asyncio.run(run())
        assert stranger.poll() is None, "cancel_run must not signal a pid that is not the run's own"
        assert (bob_run / "run_record.json").read_text(encoding="utf-8") == victim_record
        assert (bob_run / "openstudio.log").read_text(encoding="utf-8") == "BOBLOG\n"
    finally:
        stranger.kill()
