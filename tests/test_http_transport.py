"""Streamable-HTTP transport smoke test.

Validates the server can run under HTTP transport (the remote/multi-user
path) and serve a real tool round-trip, not just stdio.
"""
import asyncio
import uuid

import pytest
from conftest import http_server, http_session, integration_enabled, unwrap


@pytest.mark.integration
def test_http_server_boots_and_serves_tool():
    # Validates: server runs under streamable-HTTP transport and a real tool
    # round-trips over HTTP (proves remote transport works end to end).
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s:
                res = unwrap(await s.call_tool(
                    "create_example_osm", {"name": f"http_smoke_{uuid.uuid4().hex[:8]}"},
                ))
                assert res["ok"] is True, f"create_example_osm over HTTP failed: {res}"
                assert res["osm_path"].endswith(".osm"), res["osm_path"]

        asyncio.run(_run())
