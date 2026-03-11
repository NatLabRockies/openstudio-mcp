"""MCP tool definitions for schedules."""
from __future__ import annotations

from mcp_server.skills.schedules.operations import (
    create_schedule_ruleset,
    get_schedule_details,
    list_schedule_rulesets,
)


def register(mcp):
    @mcp.tool(name="list_schedule_rulesets")
    def list_schedule_rulesets_tool(max_results: int = 10):
        """List schedule rulesets. Default 10 results.

        Args:
            max_results: Max items (default 10, 0=unlimited)
        """
        mr = None if max_results == 0 else max_results
        return list_schedule_rulesets(max_results=mr)

    @mcp.tool(name="get_schedule_details")
    def get_schedule_details_tool(schedule_name: str):
        """Get detailed information about a specific schedule ruleset.

        Args:
            schedule_name: Name of the schedule ruleset to retrieve

        """
        return get_schedule_details(schedule_name=schedule_name)

    @mcp.tool(name="create_schedule_ruleset")
    def create_schedule_ruleset_tool(name: str, schedule_type: str = "Fractional",
                                    default_value: float = 1.0):
        """Create a new schedule ruleset with a constant default day schedule.

        Args:
            name: Name for the new schedule
            schedule_type: Type of schedule - "Fractional" (0-1), "Temperature", or "OnOff" (default: "Fractional")
            default_value: Constant value for all hours of the day (default: 1.0)

        """
        return create_schedule_ruleset(name=name, schedule_type=schedule_type,
                                      default_value=default_value)
