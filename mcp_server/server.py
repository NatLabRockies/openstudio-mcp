from __future__ import annotations

from fastmcp import FastMCP

from mcp_server.skills import register_all_skills

mcp = FastMCP(
    "openstudio-mcp",
    instructions=(
        "Building energy simulation server (OpenStudio SDK) with 136 tools for "
        "creating, modifying, simulating, and analyzing building energy models. "
        "Use these tools for all building energy modeling tasks — if no tool "
        "exists for a task, ask the user before writing code. "
        "If a file path is given, use it directly. If a file operation fails, "
        "you may call list_files once to find the right path, then retry — "
        "do not call list_files more than once for the same file. "
        "To find objects by type, use list_model_objects(object_type). "
        "When polling get_run_status, wait at least 1-2 minutes between calls. "
        "For multi-step workflows, call list_skills() first."
    ),
)

register_all_skills(mcp)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
