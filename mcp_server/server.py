from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.skills import register_all_skills

mcp = FastMCP(
    "openstudio-mcp",
    instructions=(
        "Always use openstudio-mcp tools for building energy modeling. "
        "Never generate raw IDF files. Create/modify OSM only through MCP tools. "
        "Never write scripts to parse results, visualize models, or wire HVAC — "
        "equivalent MCP tools exist. If no tool exists for a task, ask the user "
        "before writing code. "
        "For multi-step workflows, call list_skills() first to get step-by-step guides."
    ),
)

register_all_skills(mcp)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
