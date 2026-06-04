"""Per-user run dirs + run ownership + cross-user path scoping (over HTTP).

One session's runs and files must be private: another session can neither read
its run by id nor load a file under its run root.
"""
import asyncio
import uuid

import pytest
from conftest import EPW_PATH, http_server, http_session, integration_enabled, unwrap


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.mark.integration
def test_runs_and_files_are_private_per_session():
    # Regression: a global run registry + unscoped paths let any session read
    # another's runs/files. Per-user run dirs + ownership must prevent that.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s1, http_session(url) as s2:
                # --- s1 creates a model and starts a simulation ---
                cr = unwrap(await s1.call_tool("create_example_osm", {"name": _uniq("ua")}))
                assert cr["ok"] is True, cr
                osm1 = cr["osm_path"]

                rs = unwrap(await s1.call_tool(
                    "run_simulation", {"osm_path": osm1, "epw_path": EPW_PATH},
                ))
                assert rs["ok"] is True, rs
                run1 = rs["run_id"]
                try:
                    # s1 sees its own run
                    own = unwrap(await s1.call_tool("get_run_status", {"run_id": run1}))
                    assert own["ok"] is True, own
                    assert own["run"]["run_id"] == run1

                    # s2 must NOT see s1's run (ownership guard)
                    other = unwrap(await s2.call_tool("get_run_status", {"run_id": run1}))
                    assert other["ok"] is False, f"s2 must not access s1's run: {other}"
                    assert "unknown run_id" in other["error"].lower(), other

                    # s2 must NOT load a file under s1's run root (path scoping)
                    ld = unwrap(await s2.call_tool("load_osm_model", {"osm_path": osm1}))
                    assert ld["ok"] is False, f"s2 must not read s1's file: {ld}"
                    assert "not allowed" in ld["error"].lower(), ld
                finally:
                    await s1.call_tool("cancel_run", {"run_id": run1})

        asyncio.run(_run())
