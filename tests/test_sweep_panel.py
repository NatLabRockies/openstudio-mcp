"""Integration tests for the sweep panel tools against the real SetCOP common measure.

The panel itself (ui://sweep/panel.html) renders only in an MCP Apps host; these tests
cover the MCP contract the host relies on: the resource, the tool's ui metadata, the
server-side checks, and that the panel's `next` call works with the existing OSA tool.
"""
import asyncio
import uuid

import pytest
from conftest import integration_enabled, server_params, unwrap
from mcp import ClientSession
from mcp.client.stdio import stdio_client

SETCOP = "/opt/common-measures/SetCOPforSingleSpeedDXCoolingUnits"


def _run(body):
    async def _go():
        async with stdio_client(server_params()) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                await body(s)

    asyncio.run(_go())


@pytest.mark.integration
def test_open_measure_panel_serves_mcp_app_with_real_measure_bounds():
    # Validates: hosts get a ui:// panel tied to the tool, and its only field is cop, 2-7 W/W, default 4
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        tools = {t.name: t for t in (await s.list_tools()).tools}
        assert tools["open_measure_panel"].meta["ui"]["resourceUri"] == "ui://sweep/panel.html"
        res = await s.read_resource("ui://sweep/panel.html")
        assert res.contents[0].mimeType == "text/html;profile=mcp-app"
        assert "callServerTool" in res.contents[0].text
        out = unwrap(await s.call_tool("open_measure_panel", {"measure_dir": SETCOP}))
        assert out["ok"] is True, out
        assert out["schema"] == {"cop": {"type": "number", "units": "W/W", "min": 2.0, "max": 7.0,
                                         "default": 4.0, "label": "Rated COP"}}
        assert out["submit_tool"] == "submit_measure_sweep"
        assert "fallback" not in out, "stdio has no web server, so no browser link"

    _run(body)


@pytest.mark.integration
def test_submit_measure_sweep_rejects_cop_9_and_chains_into_osa_json():
    # Validates: the server refuses COP 9, and a valid range's `next` call is accepted by add_measure_to_osa_json
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        bad = unwrap(await s.call_tool("submit_measure_sweep", {"measure_dir": SETCOP, "values": {"cop": 9}}))
        assert bad["ok"] is False
        assert bad["errors"] == ["cop: 9 W/W outside [2.0, 7.0]"]
        good = unwrap(await s.call_tool("submit_measure_sweep", {
            "measure_dir": SETCOP, "values": {"cop": [3.0, 5.0, 3]}}))
        assert good["ok"] is True, good
        assert good["values"] == {"cop": [3.0, 5.0, 3]}
        osa = f"/runs/pytest_sweep_{uuid.uuid4().hex[:10]}.json"
        created = unwrap(await s.call_tool("openstudio_analysis_create_osa_json", {
            "output_path": osa, "analysis_name": "COP sweep"}))
        assert created["ok"] is True, created
        added = unwrap(await s.call_tool("openstudio_analysis_add_measure_to_osa_json", {
            "osa_json_path": osa, "measure_dir": SETCOP, "variables": good["next"]["variables"]}))
        assert added["ok"] is True, added
        assert added["measure_step"]["variables"][0]["maximum"] == pytest.approx(5.0)

    _run(body)


@pytest.mark.integration
def test_get_panel_result_on_stdio_reports_unknown_link():
    # Validates: with no browser links on stdio, a read-back fails cleanly instead of raising
    if not integration_enabled():
        pytest.skip("integration disabled")

    async def body(s):
        out = unwrap(await s.call_tool("get_panel_result", {"link_id": "0123456789ab"}))
        assert out == {"ok": False, "error": "unknown link"}

    _run(body)
