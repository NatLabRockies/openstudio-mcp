"""Simulation outputs operations — add output variables and meters.

These tools configure EnergyPlus outputs for simulation results.
"""
from __future__ import annotations

from typing import Any

import openstudio

from mcp_server.model_manager import get_model


def add_output_variable(variable_name: str, key_value: str = "*",
                       reporting_frequency: str = "Hourly") -> dict[str, Any]:
    """Add an output variable to the model for simulation results.

    Args:
        variable_name: EnergyPlus output variable name (e.g., "Zone Mean Air Temperature")
        key_value: Specific object name or "*" for all objects (default: "*")
        reporting_frequency: "Detailed", "Timestep", "Hourly", "Daily", "Monthly", "RunPeriod" (default: "Hourly")

    Returns:
        dict with ok=True and output_variable details, or ok=False and error message
    """
    try:
        model = get_model()

        # Create OutputVariable
        output_var = openstudio.model.OutputVariable(variable_name, model)
        output_var.setKeyValue(key_value)
        output_var.setReportingFrequency(reporting_frequency)

        return {
            "ok": True,
            "output_variable": {
                "handle": str(output_var.handle()),
                "variable_name": output_var.variableName(),
                "key_value": output_var.keyValue(),
                "reporting_frequency": output_var.reportingFrequency(),
            }
        }

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add output variable: {e}"}


def add_output_meter(meter_name: str, reporting_frequency: str = "Hourly") -> dict[str, Any]:
    """Add an output meter to the model for simulation results.

    Args:
        meter_name: EnergyPlus meter name (e.g., "Electricity:Facility", "Gas:Facility")
        reporting_frequency: "Detailed", "Timestep", "Hourly", "Daily", "Monthly", "RunPeriod" (default: "Hourly")

    Returns:
        dict with ok=True and output_meter details, or ok=False and error message
    """
    try:
        model = get_model()

        # Create OutputMeter
        output_meter = openstudio.model.OutputMeter(model)
        output_meter.setName(meter_name)
        output_meter.setReportingFrequency(reporting_frequency)

        return {
            "ok": True,
            "output_meter": {
                "handle": str(output_meter.handle()),
                "name": output_meter.nameString(),
                "reporting_frequency": output_meter.reportingFrequency(),
            }
        }

    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"Failed to add output meter: {e}"}
