from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.skills import register_all_skills
from mcp_server.stdout_suppression import redirect_c_stdout_to_stderr

mcp = FastMCP("openstudio-mcp")

register_all_skills(mcp)


def main():
    redirect_c_stdout_to_stderr()
    mcp.run()


if __name__ == "__main__":
    main()
