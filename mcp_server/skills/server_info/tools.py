"""MCP tool definitions for server info."""
from __future__ import annotations

from mcp_server.skills.server_info.operations import get_server_status, get_versions


def register(mcp):
    @mcp.tool(name="get_server_status")
    def get_server_status_tool():
        """Return basic server health and configuration."""
        return get_server_status()

    @mcp.tool(name="get_versions")
    def get_versions_tool():
        """Return OpenStudio and EnergyPlus versions detected in this container."""
        return get_versions()
