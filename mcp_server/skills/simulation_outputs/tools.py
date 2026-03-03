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

        Output variables extract specific simulation results for objects in the
        model. Common examples:
        - "Zone Mean Air Temperature" - zone temperatures
        - "Surface Outside Face Temperature" - surface temps
        - "Zone Air System Sensible Heating Rate" - heating loads

        Results appear in the SQL output file after simulation.

        Use save_osm_model_tool to persist changes before running simulation.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return add_output_variable(variable_name=variable_name, key_value=key_value,
                                  reporting_frequency=reporting_frequency)

    @mcp.tool(name="add_output_meter")
    def add_output_meter_tool(meter_name: str, reporting_frequency: str = "Hourly"):
        """Add an EnergyPlus output meter to the model.

        Args:
            meter_name: EnergyPlus meter name (e.g., "Electricity:Facility", "Gas:Facility")
            reporting_frequency: "Detailed", "Timestep", "Hourly", "Daily", "Monthly", "RunPeriod" (default: "Hourly")

        Output meters aggregate energy use across categories. Common examples:
        - "Electricity:Facility" - total electricity consumption
        - "Gas:Facility" - total gas consumption
        - "Heating:Electricity" - electric heating energy
        - "Cooling:Electricity" - electric cooling energy

        Results appear in the SQL output file and meter CSV files after simulation.

        Use save_osm_model_tool to persist changes before running simulation.

        Requires a model to be loaded via load_osm_model_tool first.
        """
        return add_output_meter(meter_name=meter_name, reporting_frequency=reporting_frequency)
