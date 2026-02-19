from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.skills import register_all_skills

mcp = FastMCP("openstudio-mcp")

register_all_skills(mcp)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
