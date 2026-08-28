"""MCP tool definitions for skill discovery."""
from __future__ import annotations

from mcp_server.skills.skill_discovery.operations import (
    get_skill_file_op,
    get_skill_op,
    list_skills_op,
)


def register(mcp):
    @mcp.tool(name="list_skills", tags={"core"})
    def list_skills_tool():
        """IMPORTANT: Call this FIRST before starting any multi-step building
        energy modeling workflow. Lists step-by-step guides for creating
        buildings, adding HVAC, running simulations, extracting results,
        and QA/QC. Each guide specifies the exact tool sequence to follow.

        Returns skill names and descriptions. Use get_skill(name) to
        get step-by-step instructions for a specific workflow.
        """
        return list_skills_op()

    @mcp.tool(name="get_skill", tags={"core"})
    def get_skill_tool(name: str):
        """Get step-by-step instructions for a workflow including exact tool
        names, parameter values, and execution order. Call before starting
        complex tasks like creating a building, adding HVAC systems, or
        running simulations. Returns the proven tool sequence to avoid errors.

        Args:
            name: Skill name from list_skills (e.g. "simulate",
                  "new-building", "retrofit", "add-hvac", "qaqc")
        """
        return get_skill_op(name)

    @mcp.tool(name="get_skill_file", tags={"core"})
    def get_skill_file_tool(skill_name: str, filename: str):
        """Fetch a supporting file advertised by get_skill (its
        supporting_files list) — reference tables and catalogs that back a
        workflow guide, e.g. get_skill_file(skill_name="retrofit",
        filename="ecm-catalog.md").

        Args:
            skill_name: Skill name from list_skills
            filename: File name from get_skill's supporting_files
        """
        return get_skill_file_op(skill_name, filename)
