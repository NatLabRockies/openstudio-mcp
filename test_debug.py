import asyncio
import json
import os
import shlex
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def test_load():
    server_cmd = os.environ.get("MCP_SERVER_CMD", "openstudio-mcp")
    server_args_env = os.environ.get("MCP_SERVER_ARGS", "").strip()
    server_args = shlex.split(server_args_env) if server_args_env else []

    server_params = StdioServerParameters(
        command=server_cmd,
        args=server_args,
        env=os.environ.copy()
    )

    name = "test_debug"
    runs_dir = Path(os.getenv("MCP_RUNS_HOST_DIR", "runs"))
    osm_path = runs_dir / f"{name}.osm"

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Create
            create_resp = await session.call_tool("create_example_osm", {"name": name})
            print("CREATE TEXT:")
            print(create_resp.content[0].text if create_resp.content else "NO CONTENT")

            # Load
            load_resp = await session.call_tool("load_osm_model", {"osm_path": str(osm_path), "load_weather_file": False})
            if load_resp.content:
                print("\nLOAD TEXT RAW:")
                print(repr(load_resp.content[0].text))

asyncio.run(test_load())
