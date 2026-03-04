"""MCP tool definitions for simulation outputs."""
from __future__ import annotations

from mcp_server.skills.simulation_outputs.operations import (
    add_output_meter,
    add_output_variable,
)


def register(mcp):
    @mcp.tool(name="add_output_variable")
    def add_output_variable_tool(variable_name: str, key_value: str = "*",
                                 reporting_frequency: str = "Hourly"):
        """Add an EnergyPlus output variable to the model.

        Args:
            variable_name: EnergyPlus output variable name (e.g., "Zone Mean Air Temperature")
            key_value: Specific object name or "*" for all objects (default: "*")
            reporting_frequency: "Detailed", "Timestep", "Hourly", "Daily", "Monthly", "RunPeriod" (default: "Hourly")

        """
        return add_output_variable(variable_name=variable_name, key_value=key_value,
                                  reporting_frequency=reporting_frequency)

    @mcp.tool(name="add_output_meter")
    def add_output_meter_tool(meter_name: str, reporting_frequency: str = "Hourly"):
        """Add an EnergyPlus output meter to the model.

        Args:
            meter_name: EnergyPlus meter name (e.g., "Electricity:Facility", "Gas:Facility")
            reporting_frequency: "Detailed", "Timestep", "Hourly", "Daily", "Monthly", "RunPeriod" (default: "Hourly")

        """
        return add_output_meter(meter_name=meter_name, reporting_frequency=reporting_frequency)
