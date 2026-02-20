"""MCP tool definitions for schedules."""

from __future__ import annotations

from mcp_server.skills.schedules.operations import (
    create_schedule_ruleset,
    get_schedule_details,
    list_schedule_rulesets,
)


def register(mcp):
    @mcp.tool(name="list_schedule_rulesets")
    def list_schedule_rulesets_tool():
        """List all schedule rulesets in the currently loaded model.

        Returns array of schedule ruleset objects with:
        - Name, handle
        - Schedule type limits
        - Default day schedule
        - Summer and winter design day schedules
        - Number of schedule rules

        Schedule rulesets define time-varying values (temperatures,
        occupancy, lighting levels, etc.) with day-of-week and
        date-range rules.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return list_schedule_rulesets()

    @mcp.tool(name="get_schedule_details")
    def get_schedule_details_tool(schedule_name: str):
        """Get detailed information about a specific schedule ruleset.

        Args:
            schedule_name: Name of the schedule ruleset to retrieve

        Returns detailed schedule attributes including:
        - Basic info (type limits, default schedules)
        - All schedule rules with day-of-week applicability
        - Date ranges for each rule

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return get_schedule_details(schedule_name=schedule_name)

    @mcp.tool(name="create_schedule_ruleset")
    def create_schedule_ruleset_tool(name: str, schedule_type: str = "Fractional", default_value: float = 1.0):
        """Create a new schedule ruleset with a constant default day schedule.

        Args:
            name: Name for the new schedule
            schedule_type: Type of schedule - "Fractional" (0-1), "Temperature", or "OnOff" (default: "Fractional")
            default_value: Constant value for all hours of the day (default: 1.0)

        Returns the created schedule with appropriate type limits and
        default day/design day schedules set to the constant value.

        Useful for creating always-on schedules, constant setpoints,
        or simple baseline schedules that can be refined with rules later.

        Use save_osm_model_tool to persist changes.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return create_schedule_ruleset(name=name, schedule_type=schedule_type, default_value=default_value)
