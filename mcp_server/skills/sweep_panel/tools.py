"""MCP tools for the sweep panel (MCP Apps ui:// resource, plus a signed link on HTTP)."""
from __future__ import annotations

from typing import Any

from fastmcp.apps import UI_MIME_TYPE, AppConfig

from mcp_server.skills.sweep_panel.operations import (
    PANEL_HTML,
    get_panel_result_op,
    open_measure_panel_op,
    submit_measure_sweep_op,
)
from mcp_server.skills.sweep_panel.routes import page_route, schema_route, submit_route

PANEL_URI = "ui://sweep/panel.html"


def register(mcp):
    @mcp.resource(PANEL_URI, mime_type=UI_MIME_TYPE, app=AppConfig(prefers_border=True))
    def sweep_panel_resource() -> str:
        return PANEL_HTML.read_text()

    @mcp.tool(tags={"analysis", "measures"}, name="open_measure_panel", app=AppConfig(resource_uri=PANEL_URI))
    def open_measure_panel_tool(measure_dir: str):
        """Open an interactive sweep panel for a measure's numeric arguments.

        Hosts that support MCP Apps (Claude Desktop, VS Code) show the panel in the chat; the
        user picks values or ranges and submits, and the server checks them. Only arguments
        with a known valid range (from measure.xml or openstudio-mcp's bounds files) appear.
        Over HTTP the result also has fallback.panel_url, a single-use browser link for clients
        that can't show panels; read what was sent there with get_panel_result(link_id).
        Call list_measure_arguments first to find the measure. Example measure_dir:
        /opt/common-measures/SetCOPforSingleSpeedDXCoolingUnits

        Args:
            measure_dir: Path to the measure directory (contains measure.xml)
        """
        return open_measure_panel_op(measure_dir)

    @mcp.tool(tags={"analysis", "measures"}, name="submit_measure_sweep",
              app=AppConfig(visibility=["app", "model"]))
    def submit_measure_sweep_tool(measure_dir: str, values: dict[str, Any]):
        """Check sweep values for a measure against its valid ranges.

        Each value is a number (fixed) or [low, high, steps] (swept). On success, returns
        `next`: the openstudio_analysis_add_measure_to_osa_json arguments to use. The sweep
        panel calls this tool itself when the user submits.

        Args:
            measure_dir: Path to the measure directory
            values: Argument name -> number or [low, high, steps], e.g. {"cop": [3.0, 5.0, 5]}
        """
        return submit_measure_sweep_op(measure_dir, values)

    @mcp.tool(tags={"analysis"}, name="get_panel_result")
    def get_panel_result_tool(link_id: str):
        """Read what the user submitted on a sweep panel browser link (HTTP deployments).

        Args:
            link_id: fallback.link_id from open_measure_panel
        """
        return get_panel_result_op(link_id)

    # Browser routes exist only where an HTTP server runs; FakeMCP test doubles lack custom_route.
    if hasattr(mcp, "custom_route"):
        mcp.custom_route("/panel", methods=["GET"])(page_route)
        mcp.custom_route("/panel/schema", methods=["GET"])(schema_route)
        mcp.custom_route("/panel/submit", methods=["POST"])(submit_route)
