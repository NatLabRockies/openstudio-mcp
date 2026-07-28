"""Per-session model isolation over HTTP.

Two client sessions share ONE server process. Each must keep its own loaded
model. This is the core multi-user guarantee — and the test that fails against
the old global ``_current_model`` singleton.
"""
import asyncio
import uuid

import pytest
from conftest import (
    create_and_load,
    create_baseline_and_load,
    http_server,
    http_session,
    integration_enabled,
    unwrap,
)


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.mark.integration
def test_two_http_sessions_keep_independent_models():
    # Regression: with the global _current_model singleton, session 2 loading a
    # model overwrote session 1's. Session-keyed state must keep them separate.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    n1, n2 = _uniq("u1"), _uniq("u2")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            # --- Arrange: two sessions, one process ---
            async with http_session(url) as s1, http_session(url) as s2:
                # --- Act ---
                z1_initial = sorted(await create_and_load(s1, n1))      # example model in s1
                z2 = sorted(await create_baseline_and_load(s2, n2))     # 10-zone baseline in s2

                after = unwrap(await s1.call_tool("list_thermal_zones", {"max_results": 0}))
                z1_after = sorted(z["name"] for z in after["thermal_zones"])

                # --- Assert ---
                assert z1_after == z1_initial, (
                    f"session 1's model was stomped by session 2: "
                    f"{z1_after} != {z1_initial}"
                )
                assert z1_after != z2, "two sessions must hold different models"
                assert len(z2) == 10, f"baseline must have 10 zones, got {len(z2)}"

        asyncio.run(_run())


@pytest.mark.integration
def test_two_http_sessions_keep_independent_wizard_state():
    # Regression: model_manager.get_session_extra() is a per-session dict
    # (added for the space-type wizard) sitting alongside the model in the
    # same _SessionState. If it were ever made global, one session's wizard
    # would leak into another's.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    n1, n2 = _uniq("w1"), _uniq("w2")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s1, http_session(url) as s2:
                await create_baseline_and_load(s1, n1)
                await create_baseline_and_load(s2, n2)

                start1 = unwrap(await s1.call_tool("start_space_type_wizard", {}))
                assert start1["ok"] is True, start1

                status2 = unwrap(await s2.call_tool("get_space_type_wizard_status", {}))
                assert status2["ok"] is False, (
                    f"session 2 saw session 1's wizard state: {status2}"
                )

                status1 = unwrap(await s1.call_tool("get_space_type_wizard_status", {}))
                assert status1["ok"] is True, status1
                assert status1["remaining_count"] == 10

        asyncio.run(_run())
