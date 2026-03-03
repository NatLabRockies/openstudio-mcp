"""MCP tool definitions for simulation results analysis."""
from __future__ import annotations

from mcp_server.skills.results.operations import (
    copy_run_artifact,
    extract_component_sizing_op,
    extract_end_use_breakdown_op,
    extract_envelope_summary_op,
    extract_hvac_sizing_op,
    extract_summary_metrics,
    extract_zone_summary_op,
    query_timeseries_op,
    read_run_artifact,
)


def register(mcp):
    @mcp.tool(name="read_run_artifact")
    def read_run_artifact_tool(run_id: str, path: str, max_bytes: int | None = None, offset: int = 0):
        """Read a run artifact file (text or base64 for binary).

        Args:
            run_id: Run identifier
            path: Relative path within the run directory
            max_bytes: Max bytes to read (default 400KB)
            offset: Byte offset for chunked reading (default 0)
        """
        try:
            mb = int(max_bytes) if max_bytes is not None else 400_000
        except (ValueError, TypeError):
            mb = 400_000
        return read_run_artifact(run_id=run_id, path=path, max_bytes=mb, offset=offset)

    @mcp.tool(name="extract_summary_metrics")
    def extract_summary_metrics_tool(run_id: str):
        """Extract summary metrics (EUI + unmet hours) from outputs."""
        return extract_summary_metrics(run_id)

    @mcp.tool(name="copy_run_artifact")
    def copy_run_artifact_tool(run_id: str, path: str, destination: str = "/runs/exports"):
        """Copy a run artifact to an accessible path, bypassing the MCP size limit.

        Args:
            run_id: Run identifier
            path: Relative path within the run directory
            destination: Target directory (default /runs/exports/)
        """
        return copy_run_artifact(run_id=run_id, path=path, destination=destination)

    # --- Tier 1: Tabular report extraction ---

    @mcp.tool(name="extract_end_use_breakdown")
    def extract_end_use_breakdown_tool(run_id: str, units: str = "IP"):
        """Extract end-use energy breakdown by fuel type (heating, cooling, lighting, etc.).

        Args:
            run_id: Run identifier
            units: "IP" (kBtu) or "SI" (GJ). Default "IP".
        """
        return extract_end_use_breakdown_op(run_id=run_id, units=units)

    @mcp.tool(name="extract_envelope_summary")
    def extract_envelope_summary_tool(run_id: str):
        """Extract envelope U-values and areas (opaque + fenestration)."""
        return extract_envelope_summary_op(run_id=run_id)

    @mcp.tool(name="extract_hvac_sizing")
    def extract_hvac_sizing_tool(run_id: str):
        """Extract autosized zone and system HVAC capacities/airflows."""
        return extract_hvac_sizing_op(run_id=run_id)

    @mcp.tool(name="extract_zone_summary")
    def extract_zone_summary_tool(run_id: str):
        """Extract per-zone areas, conditions, and multipliers."""
        return extract_zone_summary_op(run_id=run_id)

    @mcp.tool(name="extract_component_sizing")
    def extract_component_sizing_tool(run_id: str, component_type: str | None = None):
        """Extract autosized values for HVAC components (coils, fans, pumps, etc.).

        Args:
            run_id: Run identifier
            component_type: Optional filter (e.g. "Coil", "Fan", "Pump", "Chiller")
        """
        return extract_component_sizing_op(run_id=run_id, component_type=component_type)

    # --- Tier 2: Time-series ---

    @mcp.tool(name="query_timeseries")
    def query_timeseries_tool(
        run_id: str,
        variable_name: str,
        key_value: str = "*",
        start_month: int | None = None,
        start_day: int | None = None,
        end_month: int | None = None,
        end_day: int | None = None,
        frequency: str | None = None,
        max_points: int = 10000,
    ):
        """Query time-series output variable data for a date range.

        Requires output variables added via add_output_variable before simulation.

        Args:
            run_id: Run identifier
            variable_name: Variable name (e.g. "Electricity:Facility")
            key_value: Key filter ("*" for all, or zone/surface name)
            start_month: Start month (1-12)
            start_day: Start day (1-31)
            end_month: End month (1-12)
            end_day: End day (1-31)
            frequency: "Zone Timestep", "Hourly", "Daily", "Monthly"
            max_points: Cap on returned data points (default 10000)
        """
        return query_timeseries_op(
            run_id=run_id, variable_name=variable_name, key_value=key_value,
            start_month=start_month, start_day=start_day,
            end_month=end_month, end_day=end_day,
            frequency=frequency, max_points=int(max_points or 10000),
        )
