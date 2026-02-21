#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import shlex

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> int:
    # Allow overriding the server command (useful in CI or dev)
    # Examples:
    #   MCP_SERVER_CMD=openstudio-mcp
    #   MCP_SERVER_CMD="openstudio-mcp --log-level debug"
    cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    parts = shlex.split(cmd)

    server_params = StdioServerParameters(
        command=parts[0],
        args=parts[1:],
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read, write), ClientSession(read, write) as session:
        # MCP handshake
        await session.initialize()

        # Discover tools
        tools = await session.list_tools()
        tool_names = sorted(t.name for t in tools.tools)

        # Basic contract assertions
        required = {"get_server_status", "get_versions"}
        missing = required - set(tool_names)
        if missing:
            raise RuntimeError(
                f"Missing expected tools: {sorted(missing)}; available tools: {tool_names}",
            )

        # Call a couple of cheap, deterministic tools
        status = await session.call_tool("get_server_status", {})
        versions = await session.call_tool("get_versions", {})

        # Emit stable JSON (nice for CI logs / debugging)
        output = {
            "tools": tool_names,
            "server_status": status.content,
            "versions": versions.content,
        }
        print(json.dumps(output, indent=2, sort_keys=True, default=str))

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
