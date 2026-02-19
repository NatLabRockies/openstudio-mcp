"""MCP tool definitions for OSW simulation workflow."""
from __future__ import annotations

from mcp_server.skills.simulation.operations import (
    validate_osw,
    run_osw,
    run_simulation,
    get_run_status,
    get_run_logs,
    get_run_artifacts,
    cancel_run,
)


def register(mcp):
    @mcp.tool(name="validate_osw")
    def validate_osw_tool(osw_path: str, epw_path: str | None = None):
        """Validate OSW JSON and referenced files (best-effort).

        If an `epw_path` override is supplied, the OSW's `weather_file` is treated
        as optional during validation (the override path must exist).
        """
        return validate_osw(osw_path, epw_path=epw_path)

    @mcp.tool(name="run_osw")
    def run_osw_tool(
        osw_path: str,
        epw_path: str | None = None,
        name: str | None = None,
        validate_first: bool = True,
    ):
        """Start an OpenStudio run asynchronously.

        By default, this performs the same checks as `validate_osw_tool` before
        starting a run. Set `validate_first=False` to skip validation.
        """
        if validate_first:
            v = validate_osw(osw_path, epw_path=epw_path)
            if not v.get("ok"):
                return {
                    "ok": False,
                    "error": v.get("error") or "Validation failed",
                    "issues": v.get("issues") or [],
                    "osw_dir": v.get("osw_dir"),
                    "osw": v.get("osw"),
                }

        return run_osw(osw_path=osw_path, epw_path=epw_path, name=name)

    @mcp.tool(name="run_simulation")
    def run_simulation_tool(
        osm_path: str,
        epw_path: str | None = None,
        name: str | None = None,
    ):
        """Run an EnergyPlus simulation from an OSM model file.

        Creates a minimal OSW workflow automatically and starts the simulation.
        This is the simplest way to run a simulation — just provide an OSM path
        and optionally an EPW weather file.

        Use `get_run_status_tool` to poll for completion, then
        `extract_summary_metrics_tool` to get results.
        """
        return run_simulation(osm_path=osm_path, epw_path=epw_path, name=name)

    @mcp.tool(name="get_run_status")
    def get_run_status_tool(run_id: str):
        """Get current status for a run."""
        return get_run_status(run_id)

    @mcp.tool(name="get_run_logs")
    def get_run_logs_tool(run_id: str, tail: int | None = None, stream: str = "openstudio"):
        """Return tail of logs for a run (openstudio/energyplus)."""
        return get_run_logs(run_id, tail=tail, stream=stream)

    @mcp.tool(name="get_run_artifacts")
    def get_run_artifacts_tool(run_id: str):
        """List important output artifacts for a run."""
        return get_run_artifacts(run_id)

    @mcp.tool(name="cancel_run")
    def cancel_run_tool(run_id: str):
        """Attempt to cancel a running job."""
        return cancel_run(run_id)
