"""MCP tool definitions for simulation results analysis."""
from __future__ import annotations

from mcp_server.skills.results.operations import (
    compare_runs_op,
    copy_file,
    extract_component_sizing_op,
    extract_end_use_breakdown_op,
    extract_envelope_summary_op,
    extract_hvac_sizing_op,
    extract_simulation_errors_op,
    extract_summary_metrics,
    extract_zone_summary_op,
    list_output_variables_op,
    query_timeseries_op,
    read_file,
)


def register(mcp):
    @mcp.tool(name="read_file")
    def read_file_tool(file_path: str, max_bytes: int | None = None, offset: int = 0):
        """Read any file by absolute path (works across all mounts: /runs, /inputs, /repo, etc.).

        Default 50KB. Use offset+max_bytes for chunked reading of large files.

        Args:
            file_path: Absolute path to the file (e.g. /runs/my_run/run/eplusout.err)
            max_bytes: Max bytes to read (default 50KB)
            offset: Byte offset for chunked reading (default 0)
        """
        try:
            mb = int(max_bytes) if max_bytes is not None else 50_000
        except (ValueError, TypeError):
            mb = 50_000
        return read_file(file_path=file_path, max_bytes=mb, offset=offset)

    @mcp.tool(name="extract_summary_metrics")
    def extract_summary_metrics_tool(run_id: str, include_raw: bool = False):
        """Extract summary metrics (EUI + unmet hours) from outputs.

        Args:
            run_id: Run identifier
            include_raw: Include full raw extraction dicts (default False)
        """
        return extract_summary_metrics(run_id, include_raw=include_raw)

    @mcp.tool(name="copy_file")
    def copy_file_tool(file_path: str, destination: str = "/runs/exports"):
        """Copy a file or directory to an accessible path.

        Supports both individual files and entire directories (e.g. measure dirs).
        Bypasses the MCP size limit for large files like HTML reports.

        Args:
            file_path: Absolute path to the source file or directory
            destination: Target directory (default /runs/exports/)
        """
        return copy_file(file_path=file_path, destination=destination)

    @mcp.tool(name="extract_simulation_errors")
    def extract_simulation_errors_tool(run_id: str):
        """Parse simulation errors from eplusout.err into categorized Fatal/Severe/Warning lists.
        Use after a failed simulation to diagnose what went wrong.

        Args:
            run_id: Run identifier
        """
        return extract_simulation_errors_op(run_id=run_id)

    @mcp.tool(name="list_output_variables")
    def list_output_variables_tool(run_id: str):
        """List available output variables and meters from a completed simulation.
        Use this to discover what timeseries data you can query with query_timeseries.

        Args:
            run_id: Run identifier
        """
        return list_output_variables_op(run_id=run_id)

    @mcp.tool(name="compare_runs")
    def compare_runs_tool(baseline_run_id: str, retrofit_run_id: str):
        """Compare two simulation runs: EUI delta, unmet hours delta, and per-end-use breakdown.
        Use after running baseline + retrofit simulations to quantify the impact.
        Includes full end-use breakdown for both runs — no need to call
        extract_end_use_breakdown separately.

        Args:
            baseline_run_id: Run identifier for the baseline simulation
            retrofit_run_id: Run identifier for the retrofit simulation
        """
        return compare_runs_op(baseline_run_id=baseline_run_id, retrofit_run_id=retrofit_run_id)

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
    def extract_component_sizing_tool(
        run_id: str, component_type: str | None = None, max_results: int = 50,
    ):
        """Extract autosized values for HVAC components (coils, fans, pumps, etc.).

        Default 50 results. Use component_type filter (e.g. "Coil", "Fan") to narrow.

        Args:
            run_id: Run identifier
            component_type: Filter by type (e.g. "Coil", "Fan", "Pump", "Chiller")
            max_results: Cap on results (default 50, 0=unlimited)
        """
        mr = 0 if max_results == 0 else max_results
        return extract_component_sizing_op(
            run_id=run_id, component_type=component_type, max_results=mr,
        )

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
        max_points: int = 2000,
    ):
        """Query time-series output variable data for a date range.

        Default 2000 points. Use start_month/end_month to narrow time range,
        or increase max_points for finer resolution.

        Args:
            run_id: Run identifier
            variable_name: Variable name (e.g. "Electricity:Facility")
            key_value: Key filter ("*" for all, or zone/surface name)
            start_month: Start month (1-12)
            start_day: Start day (1-31)
            end_month: End month (1-12)
            end_day: End day (1-31)
            frequency: "Zone Timestep", "Hourly", "Daily", "Monthly"
            max_points: Cap on returned data points (default 2000)
        """
        return query_timeseries_op(
            run_id=run_id, variable_name=variable_name, key_value=key_value,
            start_month=start_month, start_day=start_day,
            end_month=end_month, end_day=end_day,
            frequency=frequency, max_points=int(max_points or 2000),
        )
