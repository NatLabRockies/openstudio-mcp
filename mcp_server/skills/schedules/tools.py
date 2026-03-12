"""MCP tool definitions for schedules."""
from __future__ import annotations

from mcp_server.skills.schedules.operations import (
    create_schedule_ruleset,
    get_schedule_details,
)


def register(mcp):
    # list_schedule_rulesets removed — use list_model_objects("ScheduleRuleset")

    @mcp.tool(name="get_schedule_details")
    def get_schedule_details_tool(schedule_name: str):
        """Get detailed information about a specific schedule ruleset.

        Returns all schedule rules. For schedules with many rules, use
        list_model_objects("ScheduleRuleset") first to check num_rules.

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
