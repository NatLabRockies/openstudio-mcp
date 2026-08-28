"""Client-neutral model saving (save_name) + skill support-file delivery.

Plan findings C3 + F4: served skills taught literal /runs/... writes that the
HTTP identity layer denies (each HTTP user owns RUN_ROOT/<user_key>, not
/runs), and advertised supporting files (ecm-catalog.md) with no fetch path.

save_osm_model(save_name=...) is the server-resolved save-as: basename in,
server picks the caller-private path, response returns the real osm_path.
get_skill_file(skill_name, filename) is the sole support-file retrieval
affordance.
"""
import asyncio
import uuid

import pytest
from conftest import (
    http_server,
    http_session,
    integration_enabled,
    server_params,
    unwrap,
)
from doc_contract_lib import load_tool_registry
from mcp import ClientSession
from mcp.client.stdio import stdio_client

# Read-only shared asset (under /repo, a shared read root in the container)
READONLY_OSM = "/repo/tests/assets/baseline_model_constructions.osm"


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


# ---------------------------------------------------------------------------
# Unit: tool contracts (AST — no imports)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_save_osm_model_exposes_save_name():
    # Regression: served skills wrote literal /runs/<name>.osm — denied for
    # HTTP users whose writable root is /runs/<user_key> (C3). save_name is
    # the client-neutral affordance; the server resolves the real path.
    registry = load_tool_registry()
    assert "save_name" in registry["save_osm_model"].params, (
        "save_osm_model must accept save_name (server-resolved save-as)"
    )


@pytest.mark.unit
def test_get_skill_file_registered():
    # Regression: get_skill advertised supporting_files (ecm-catalog.md) with
    # no documented fetch path (F4) — get_skill_file is the retrieval tool
    registry = load_tool_registry()
    assert "get_skill_file" in registry, "get_skill_file tool must exist"
    sig = registry["get_skill_file"]
    assert set(sig.required) == {"skill_name", "filename"}, sig


# ---------------------------------------------------------------------------
# Integration: HTTP identity — save_name lands in the caller's private root
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_save_name_scopes_to_caller_and_isolates_users():
    # Regression: with identity-scoped roots, a no-arg save of a model loaded
    # from a read-only shared root is denied and literal /runs paths are not
    # a user's writable area — save_name must resolve inside the caller's
    # run root and stay invisible to other principals (C3)
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    with http_server({"MCP_AUTH": "none"}) as (url, _proc):
        async def _run():
            async with http_session(url) as s1, http_session(url) as s2:
                ld = unwrap(await s1.call_tool("load_osm_model",
                                               {"osm_path": READONLY_OSM}))
                assert ld["ok"] is True, ld

                # No-arg save resolves to the read-only original path — denied
                denied = unwrap(await s1.call_tool("save_osm_model", {}))
                assert denied["ok"] is False, denied
                assert "not allowed" in denied["error"].lower(), denied

                # Server-resolved save-as
                saved = unwrap(await s1.call_tool("save_osm_model",
                                                  {"save_name": "baseline"}))
                assert saved["ok"] is True, saved
                path = saved["osm_path"]
                assert path.endswith("/models/baseline.osm"), path
                assert path != "/runs/models/baseline.osm", (
                    "HTTP user's save must land under /runs/<user_key>/, "
                    f"not the shared /runs root: {path}"
                )

                # The returned path feeds back into the caller's own tools
                reload_own = unwrap(await s1.call_tool("load_osm_model",
                                                       {"osm_path": path}))
                assert reload_own["ok"] is True, reload_own

                # Another principal can neither read nor overwrite it
                other_read = unwrap(await s2.call_tool("load_osm_model",
                                                       {"osm_path": path}))
                assert other_read["ok"] is False, other_read
                assert "not allowed" in other_read["error"].lower(), other_read

                ld2 = unwrap(await s2.call_tool("load_osm_model",
                                                {"osm_path": READONLY_OSM}))
                assert ld2["ok"] is True, ld2
                s2_saved = unwrap(await s2.call_tool("save_osm_model",
                                                     {"save_name": "baseline"}))
                assert s2_saved["ok"] is True, s2_saved
                assert s2_saved["osm_path"] != path, (
                    "two principals saving the same save_name must get "
                    "distinct private paths"
                )

                # Separator/traversal names are rejected with a clear error
                for bad in ("../escape", "a/b", "..", "C:evil"):
                    res = unwrap(await s1.call_tool("save_osm_model",
                                                    {"save_name": bad}))
                    assert res["ok"] is False, (bad, res)
                    assert "save_name" in res["error"], (bad, res)

                # Mutual exclusion with osm_path
                both = unwrap(await s1.call_tool("save_osm_model", {
                    "save_name": "x", "osm_path": "/runs/x.osm",
                }))
                assert both["ok"] is False, both

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Integration: get_skill_file serves the advertised support file
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_get_skill_file_serves_ecm_catalog():
    # Regression: retrofit advertised ecm-catalog.md with no fetch path (F4);
    # get_skill lists it in supporting_files and get_skill_file returns it
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                skill = unwrap(await s.call_tool("get_skill",
                                                 {"name": "retrofit"}))
                assert skill["ok"] is True, skill
                assert skill["supporting_files"] == ["ecm-catalog.md"], skill

                res = unwrap(await s.call_tool("get_skill_file", {
                    "skill_name": "retrofit", "filename": "ecm-catalog.md",
                }))
                assert res["ok"] is True, res
                assert res["filename"] == "ecm-catalog.md"
                assert "## Envelope" in res["content"], (
                    "ecm-catalog content missing expected ECM category"
                )

                # Traversal and non-support files are refused
                for bad in ("../retrofit/ecm-catalog.md", "/etc/passwd",
                            "SKILL.md", "eval.md", ".hidden.md"):
                    denied = unwrap(await s.call_tool("get_skill_file", {
                        "skill_name": "retrofit", "filename": bad,
                    }))
                    assert denied["ok"] is False, (bad, denied)

    asyncio.run(_run())
