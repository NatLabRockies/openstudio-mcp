"""MCP tool definitions for simulation outputs."""
from __future__ import annotations

from mcp_server.skills.simulation_outputs.operations import (
    add_output_meter,
    add_output_variable,
)


def register(mcp):
    @mcp.tool(tags={"simulation"}, name="add_output_variable")
    def add_output_variable_tool(variable_name: str, key_value: str = "*",
                                 reporting_frequency: str = "Hourly"):
        """Add an EnergyPlus output variable: zone temperature, surface heat flux, system flow rate, etc.
        Use for zone/surface-level data. For whole-building energy meters, use add_output_meter.

        Args:
            variable_name: EnergyPlus output variable name (e.g., "Zone Mean Air Temperature")
            key_value: Specific object name or "*" for all objects (default: "*")
            reporting_frequency: "Detailed", "Timestep", "Hourly", "Daily", "Monthly", "RunPeriod" (default: "Hourly")

        """
        return add_output_variable(variable_name=variable_name, key_value=key_value,
                                  reporting_frequency=reporting_frequency)

    @mcp.tool(tags={"simulation"}, name="add_output_meter")
    def add_output_meter_tool(meter_name: str, reporting_frequency: str = "Hourly"):
        """Add an EnergyPlus energy meter: Electricity:Facility, Gas:Facility, district, etc.
        Use for facility-level energy tracking. For zone/surface variables, use add_output_variable.

        Args:
            meter_name: EnergyPlus meter name (e.g., "Electricity:Facility", "Gas:Facility")
            reporting_frequency: "Detailed", "Timestep", "Hourly", "Daily", "Monthly", "RunPeriod" (default: "Hourly")

        """
        return add_output_meter(meter_name=meter_name, reporting_frequency=reporting_frequency)
