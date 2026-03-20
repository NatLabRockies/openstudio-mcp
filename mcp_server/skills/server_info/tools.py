"""MCP tool definitions for server info."""
from __future__ import annotations

from mcp_server.skills.server_info.operations import get_server_status, get_versions


def register(mcp):
    @mcp.tool(name="get_server_status", tags={"meta"})
    def get_server_status_tool():
        """Server health check: run root path, max concurrency, loaded model status."""
        return get_server_status()

    @mcp.tool(name="get_versions", tags={"meta"})
    def get_versions_tool():
        """OpenStudio SDK, EnergyPlus, and Ruby interpreter versions in the container."""
        return get_versions()
