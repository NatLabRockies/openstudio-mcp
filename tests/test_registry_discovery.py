"""Registry-derived discovery surfaces: tool-catalog resource + router (F1, F2).

The tool_catalog resource was a hand-maintained static dict (130 of the
registered tools, claiming completeness) and the router's keyword groups
missed four registration tags entirely — those tools were unreachable via
recommend_tools. Both surfaces must derive from the live registration
collector so they cannot drift.
"""
import asyncio
import json

import pytest
from conftest import integration_enabled, server_params, unwrap
from doc_contract_lib import load_tool_registry
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from test_skill_registration import EXPECTED_TOOLS

# ---------------------------------------------------------------------------
# Unit: router coverage (AST registry — no imports of openstudio)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_every_registration_tag_has_router_keywords():
    # Regression: tags analysis/files/meta/space_types had no keyword group —
    # recommend_tools could never route to their tools (F2)
    from mcp_server.skills.tool_router.operations import GROUP_KEYWORDS

    tags = {t for sig in load_tool_registry().values() for t in sig.tags}
    missing = sorted(tags - set(GROUP_KEYWORDS))
    assert not missing, (
        f"registration tags with no router keyword group (their tools are "
        f"unreachable via recommend_tools): {missing}"
    )
    empty = sorted(g for g, kw in GROUP_KEYWORDS.items() if not kw)
    assert not empty, f"keyword groups with no keywords: {empty}"


@pytest.mark.unit
def test_every_tool_reachable_via_router():
    # Regression: 30+ tools carried only unrouted tags — recommend_tools
    # could never surface them (F2). Every tool needs >= 1 routed tag.
    from mcp_server.skills.tool_router.operations import GROUP_KEYWORDS

    unreachable = sorted(
        sig.name for sig in load_tool_registry().values()
        if not (sig.tags & set(GROUP_KEYWORDS))
    )
    assert not unreachable, (
        f"tools unreachable via recommend_tools (no routed tag): {unreachable}"
    )


@pytest.mark.unit
def test_router_docstring_has_no_tool_count():
    # Regression: recommend_tools docstring said "instead of all 140" — counts
    # drift; doctrine is "150+", never exact counts in tool text (F2)
    import re
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1]
        / "mcp_server" / "skills" / "tool_router" / "tools.py"
    ).read_text(encoding="utf-8")
    m = re.search(r"all \d+", text)
    assert m is None, f"hardcoded tool count in router docstring: '{m.group()}'"


# ---------------------------------------------------------------------------
# Unit: collector on synthetic registrations (no openstudio)
# ---------------------------------------------------------------------------


class _FakeMCP:
    def __init__(self):
        self.registered = {}

    def tool(self, name=None, tags=None, **kwargs):
        def decorator(fn):
            self.registered[name or fn.__name__] = fn
            return fn
        return decorator

    def prompt(self, **kw):
        return lambda fn: fn

    def resource(self, *a, **kw):
        return lambda fn: fn


@pytest.mark.unit
def test_collector_captures_descriptors_and_delegates():
    # Validates: the collecting facade records name/package/tags/first-line
    # description while still registering the function on the real MCP —
    # no monkeypatching of the shared FastMCP instance (F1 design)
    from mcp_server.tool_registry import (
        CollectingMCP,
        descriptors,
        reset_descriptors,
    )

    reset_descriptors()
    fake = _FakeMCP()
    facade = CollectingMCP(fake, "synth_pkg")

    @facade.tool(name="synth_tool", tags={"files"})
    def synth_tool(x: str):
        """First line description.

        Second line ignored.
        """
        return x

    assert "synth_tool" in fake.registered, "delegation to real MCP broken"
    d = descriptors()["synth_tool"]
    assert d.package == "synth_pkg"
    assert d.tags == frozenset({"files"})
    assert d.description == "First line description."
    reset_descriptors()


@pytest.mark.unit
def test_collector_rejects_duplicate_names():
    # Validates: two packages registering the same MCP name fail loudly at
    # registration instead of silently shadowing each other
    from mcp_server.tool_registry import CollectingMCP, reset_descriptors

    reset_descriptors()
    facade_a = CollectingMCP(_FakeMCP(), "pkg_a")
    facade_b = CollectingMCP(_FakeMCP(), "pkg_b")

    @facade_a.tool(name="dup_tool", tags={"core"})
    def one():
        """One."""

    with pytest.raises(ValueError, match="dup_tool"):
        @facade_b.tool(name="dup_tool", tags={"core"})
        def two():
            """Two."""
    reset_descriptors()


@pytest.mark.unit
def test_router_routes_synthetic_files_tool():
    # Validates: recommend_tools builds its index from the collector — a
    # files-tagged tool is reachable via upload/transfer phrasing (F2)
    from mcp_server.skills.tool_router import operations as router_ops
    from mcp_server.tool_registry import CollectingMCP, reset_descriptors

    reset_descriptors()
    facade = CollectingMCP(_FakeMCP(), "file_transfer")

    @facade.tool(name="synthetic_upload", tags={"files"})
    def synthetic_upload():
        """Upload a local file to the server."""

    router_ops.reset_tool_index()
    try:
        res = router_ops.recommend_tools_op("upload my local model to the server")
        assert res["ok"] is True
        assert res["recommended_group"] == "files", res
        assert [t["name"] for t in res["tools"]] == ["synthetic_upload"]
    finally:
        reset_descriptors()
        router_ops.reset_tool_index()


# ---------------------------------------------------------------------------
# Integration: live catalog == live tools/list == EXPECTED_TOOLS
# ---------------------------------------------------------------------------


def _flatten_catalog(payload: dict) -> set[str]:
    names: set[str] = set()
    for tools in payload.values():
        names.update(tools if isinstance(tools, list) else tools.keys())
    return names


@pytest.mark.integration
def test_tool_catalog_matches_live_roster():
    # Regression: the static tool_catalog dict advertised 130 names while
    # claiming completeness — 60+ registered tools were invisible to catalog
    # readers (F1). Normal mode: catalog == live tools/list == EXPECTED_TOOLS.
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()

                live = {t.name for t in (await s.list_tools()).tools}
                assert live == EXPECTED_TOOLS, (
                    f"live roster drift: missing={sorted(EXPECTED_TOOLS - live)}, "
                    f"extra={sorted(live - EXPECTED_TOOLS)}"
                )

                res = await s.read_resource("openstudio://tool-catalog")
                payload = json.loads(res.contents[0].text)
                catalog = _flatten_catalog(payload)
                assert catalog == EXPECTED_TOOLS, (
                    f"tool-catalog drift: missing={sorted(EXPECTED_TOOLS - catalog)}, "
                    f"extra={sorted(catalog - EXPECTED_TOOLS)}"
                )

    asyncio.run(_run())


@pytest.mark.integration
def test_recommend_tools_routes_previously_unrouted_tags():
    # Regression: analysis/files/meta/space_types tools were unreachable via
    # recommend_tools over the live server (F2)
    if not integration_enabled():
        pytest.skip("Set RUN_OPENSTUDIO_INTEGRATION=1 to enable integration tests.")

    async def _run():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                cases = {
                    "upload my local model file to the remote server": "request_upload",
                    "run an OSAF sampling analysis sweep on openstudio server": "openstudio_analysis_submit",
                    "attribute standards space types after a gbxml import": "start_space_type_wizard",
                }
                for task, expected_tool in cases.items():
                    res = unwrap(await s.call_tool(
                        "recommend_tools", {"task_description": task}))
                    assert res["ok"] is True, res
                    names = [t["name"] for t in res["tools"]]
                    assert expected_tool in names, (
                        f"'{task}' -> group '{res['recommended_group']}' "
                        f"without {expected_tool}: {names}"
                    )

    asyncio.run(_run())
