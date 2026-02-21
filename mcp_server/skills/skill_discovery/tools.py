"""MCP tool definitions for skill discovery."""
from __future__ import annotations

from mcp_server.skills.skill_discovery.operations import (
    list_skills_op,
    get_skill_op,
)


def register(mcp):
    @mcp.tool(name="list_skills")
    def list_skills_tool():
        """List available workflow guides for common tasks like creating
        buildings, running simulations, and analyzing results.

        Call this when you need guidance on multi-step workflows or
        don't know which tools to use for a task.

        Returns skill names and descriptions. Use get_skill(name) to
        get step-by-step instructions for a specific workflow.
        """
        return list_skills_op()

    @mcp.tool(name="get_skill")
    def get_skill_tool(name: str):
        """Get step-by-step workflow instructions for a specific task.

        Returns tool names, sequences, and domain guidance. Call this
        before starting a complex multi-tool workflow.

        Args:
            name: Skill name from list_skills (e.g. "simulate",
                  "new-building", "retrofit")
        """
        return get_skill_op(name)
