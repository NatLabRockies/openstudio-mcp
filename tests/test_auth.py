"""Token auth over HTTP.

MCP_AUTH=token must reject missing/invalid bearer tokens and accept valid ones.
The authenticated principal (client_id) also scopes the caller's run dir.
"""
import asyncio
import uuid

import pytest
from conftest import http_server, http_session, integration_enabled, unwrap


def _uniq(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:8]}"


@pytest.mark.integration
def test_http_token_auth_accepts_valid_rejects_invalid():
    # Validates: token auth rejects missing/invalid bearer tokens, accepts valid
    # ones, and the authenticated principal (client_id) scopes the run dir.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    tokens = '{"good-secret-abc": "alice"}'
    with http_server({"MCP_AUTH": "token", "MCP_TOKENS": tokens}) as (url, _proc):
        async def _run():
            # Valid token works, and the principal "alice" scopes the run dir.
            async with http_session(url, token="good-secret-abc") as s:  # noqa: S106 - test token
                res = unwrap(await s.call_tool("create_example_osm", {"name": _uniq("authok")}))
                assert res["ok"] is True, res
                assert "/alice/" in res["out_dir"], \
                    f"run dir must be scoped to the authenticated principal: {res['out_dir']}"

            # Missing token: rejected (connection/handshake fails).
            missing_rejected = False
            try:
                async with http_session(url) as s:
                    await s.call_tool("create_example_osm", {"name": "x"})
            except Exception:
                missing_rejected = True
            assert missing_rejected, "connection without a token must be rejected"

            # Invalid token: rejected.
            bad_rejected = False
            try:
                async with http_session(url, token="wrong-token") as s:  # noqa: S106 - test token
                    await s.call_tool("create_example_osm", {"name": "x"})
            except Exception:
                bad_rejected = True
            assert bad_rejected, "connection with an invalid token must be rejected"

        asyncio.run(_run())
