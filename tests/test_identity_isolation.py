"""Real HTTP and subprocess checks for principal and queued-run isolation."""
import asyncio
import json
import os
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import psutil
import pytest
from conftest import http_server, http_session, integration_enabled, unwrap

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    not integration_enabled(), reason="Set RUN_OPENSTUDIO_INTEGRATION=1",
)]


@pytest.mark.parametrize("audit", ["on", "off"])
@pytest.mark.parametrize("auth", ["jwt", "token"])
def test_unusable_principal_returns_error(auth, audit):
    # Regression: JWTs without identity claims shared unknown's storage and privileges,
    # and refusing them before AuditMiddleware ran left no audit trail of the attempt.
    from fastmcp.server.auth.providers.jwt import RSAKeyPair

    from mcp_server.config import RUN_ROOT

    audit_path = RUN_ROOT / f"audit_{uuid.uuid4().hex[:8]}.jsonl"
    env = {"MCP_AUTH": auth, "MCP_AUDIT": audit, "MCP_AUDIT_FILE": str(audit_path)}
    if auth == "jwt":
        import jwt

        keys = RSAKeyPair.generate()
        token = jwt.encode({
            "iss": "https://issuer.test", "aud": "openstudio-mcp",
            "exp": int(time.time()) + 300,
        }, keys.private_key.get_secret_value(), algorithm="RS256")
        env.update({
            "MCP_JWT_PUBLIC_KEY": keys.public_key,
            "MCP_JWT_ISSUER": "https://issuer.test",
            "MCP_JWT_AUDIENCE": "openstudio-mcp",
        })
    else:
        token = uuid.uuid4().hex
        env["MCP_TOKENS"] = json.dumps({token: "unknown"})

    with http_server(env) as (url, _proc):
        async def run():
            async with http_session(url, token=token) as session:
                result = unwrap(await session.call_tool("create_example_osm", {
                    "name": "rejected_" + uuid.uuid4().hex[:8],
                }))
                assert result == {
                    "ok": False,
                    "error": "Authenticated token has no usable principal",
                }
        asyncio.run(run())

    if audit == "off":
        assert not audit_path.exists()
        return
    lines = [json.loads(ln) for ln in audit_path.read_text().splitlines() if ln.strip()]
    assert [(e["event"], e.get("tool"), e.get("error")) for e in lines] == [
        ("principal_rejected", "create_example_osm", "Authenticated token has no usable principal"),
    ], lines


@pytest.mark.parametrize(("principal", "key"), [
    ("local", "local~25bf8e1a2393f1108d37029b3df5593236c755742ec93465bbafa9b290bddcf6"),
    ("examples", "examples~c590b3c924c35c2f241746522284e4709df490d73a38aaa7d6de4ed1eac2f546"),
])
def test_reserved_principal_isolated_over_http(principal, key):
    # Regression: reserved principals must neither own local storage nor read peer models.
    from mcp_server.config import RUN_ROOT

    own_token, peer_token = uuid.uuid4().hex, uuid.uuid4().hex
    env = {"MCP_AUTH": "token", "MCP_TOKENS": json.dumps({
        own_token: principal, peer_token: "identity_peer",
    })}
    with http_server(env) as (url, _proc):
        async def run():
            async with http_session(url, token=own_token) as own:
                async with http_session(url, token=peer_token) as peer:
                    name = "identity_" + uuid.uuid4().hex[:8]
                    created = unwrap(await own.call_tool("create_example_osm", {"name": name}))
                    assert created["ok"] is True, created
                    assert Path(created["out_dir"]) == RUN_ROOT / key / "examples" / name
                    other = unwrap(await peer.call_tool("create_example_osm", {"name": name}))
                    assert other["ok"] is True, other
                    denied = unwrap(await own.call_tool("load_osm_model", {"osm_path": other["osm_path"]}))
                    assert denied["ok"] is False, denied
                    assert "not allowed" in denied["error"].lower()
        asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink test")
@pytest.mark.parametrize("target", ["outside", "peer"])
def test_symlinked_tenant_root_returns_error(target):
    # Regression: refusing a tampered run root must return ok:false over MCP, not raise.
    from mcp_server.config import RUN_ROOT

    with tempfile.TemporaryDirectory(prefix="root_guard_", dir=RUN_ROOT) as temp:
        root = Path(temp) / "tenants"
        root.mkdir()
        destination = Path(temp) / "outside" if target == "outside" else root / "bob"
        destination.mkdir()
        (root / "alice").symlink_to(destination, target_is_directory=True)
        token = uuid.uuid4().hex
        env = {
            "MCP_AUTH": "token", "MCP_TOKENS": json.dumps({token: "alice"}),
            "OPENSTUDIO_MCP_RUN_ROOT": str(root),
        }
        with http_server(env) as (url, _proc):
            async def run():
                async with http_session(url, token=token) as session:
                    response = await session.call_tool("create_example_osm", {"name": "blocked"})
                    assert response.isError is False
                    assert unwrap(response) == {"ok": False, "error": "invalid user key: 'alice'"}
                    assert list(destination.iterdir()) == []
            asyncio.run(run())


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink test")
@pytest.mark.parametrize("target", ["peer", "self"])
def test_signed_download_refuses_retargeted_tenant_root(target):
    # Regression: the signed GET route runs outside IdentityGuard, so a tenant root
    # refused after the URL was minted (peer symlink, or a loop that makes resolve()
    # raise) surfaced as HTTP 500 instead of a 403.
    from mcp_server.config import RUN_ROOT

    with tempfile.TemporaryDirectory(prefix="root_guard_", dir=RUN_ROOT) as temp:
        root = Path(temp) / "tenants"
        root.mkdir()
        token = uuid.uuid4().hex
        env = {
            "MCP_AUTH": "token", "MCP_TOKENS": json.dumps({token: "alice"}),
            "OPENSTUDIO_MCP_RUN_ROOT": str(root),
        }
        with http_server(env) as (url, _proc):
            async def run():
                async with http_session(url, token=token) as session:
                    created = unwrap(await session.call_tool("create_example_osm", {"name": "dl"}))
                    assert created["ok"] is True, created
                    return unwrap(await session.call_tool(
                        "request_download", {"path": created["osm_path"]}))
            dl = asyncio.run(run())
            assert dl["ok"] is True, dl
            (root / "alice").rename(root / "bob")
            (root / "alice").symlink_to(root / ("bob" if target == "peer" else "alice"),
                                        target_is_directory=True)
            response = httpx.get(dl["download_url"], timeout=30)
            assert response.status_code == 403, response.text
            assert response.json() == {"ok": False, "error": "invalid user key: 'alice'"}


@pytest.mark.skipif(os.name != "posix", reason="Linux sandbox ownership")
@pytest.mark.parametrize("caller", [None, "alice"])
def test_dispatch_uses_each_run_owner(caller):
    # Regression: request/daemon dispatch chowned and launched peer runs as the caller/LOCAL.
    from mcp.server.auth.middleware.auth_context import auth_context_var
    from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
    from mcp.server.auth.provider import AccessToken

    from mcp_server import identity, sandbox
    from mcp_server.config import RUN_ROOT
    from mcp_server.skills.simulation import operations as ops

    if os.geteuid() != 0 or not sandbox.enabled():
        pytest.skip("Requires root and an enabled sandbox in Docker")

    user = AuthenticatedUser(AccessToken(token=uuid.uuid4().hex, client_id=caller, scopes=[])) if caller else None
    context = auth_context_var.set(user)
    try:
        assert identity.user_key() == (caller or "local")
        # Ordinary queued records and real OpenStudio subprocesses; no mocked dispatch.
        with tempfile.TemporaryDirectory(prefix="owner_test_", dir=RUN_ROOT) as temp:
            Path(temp).chmod(0o755)
            for owner, expected_uid in [("alice", 39801), ("bob", 4712)]:
                work = Path(temp) / owner
                work.mkdir()
                osw = work / "in.osw"
                osw.write_text('{"steps": []}', encoding="utf-8")
                run_id = "owner_" + uuid.uuid4().hex[:12]
                rec = ops.RunRecord(
                    run_id=run_id, user_key=owner, name="owner", status="queued",
                    created_at=time.time(), started_at=None, ended_at=None, pid=None,
                    run_dir=work, osw_path=osw, epw_path=None, exit_code=None, error=None,
                )
                ops._RUNS[run_id] = rec
                ops._enqueue(run_id)
                try:
                    ops._dispatch_once()
                    assert rec.status == "running"
                    assert work.stat().st_uid == expected_uid
                    assert osw.stat().st_uid == expected_uid
                    process = psutil.Process(rec.pid)
                    deadline = time.monotonic() + 10
                    while process.uids().effective == 0 and time.monotonic() < deadline:
                        time.sleep(0.02)
                    assert tuple(process.uids()) == (expected_uid,) * 3
                    assert tuple(process.gids()) == (expected_uid,) * 3
                finally:
                    if rec.pid is not None:
                        ops._kill_process_group(rec.pid)
                    ops._RUNS.pop(run_id, None)
                    if run_id in ops._queue:
                        ops._queue.remove(run_id)
    finally:
        auth_context_var.reset(context)
