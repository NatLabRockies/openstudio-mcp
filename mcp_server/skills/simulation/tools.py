"""MCP tool definitions for OSW simulation workflow."""
from __future__ import annotations

from mcp_server.skills.simulation.operations import (
    cancel_run,
    get_run_artifacts,
    get_run_logs,
    get_run_status,
    run_osw,
    run_simulation,
    validate_model_op,
    validate_osw,
)


def register(mcp):
    @mcp.tool(tags={"simulation"}, name="validate_osw")
    def validate_osw_tool(osw_path: str, epw_path: str | None = None):
        """Validate OSW JSON and referenced files (best-effort).

        If an `epw_path` override is supplied, the OSW's `weather_file` is treated
        as optional during validation (the override path must exist).
        """
        return validate_osw(osw_path, epw_path=epw_path)

    @mcp.tool(tags={"simulation"}, name="run_osw")
    def run_osw_tool(
        osw_path: str,
        epw_path: str | None = None,
        name: str | None = None,
        validate_first: bool = True,
    ):
        """Start an OpenStudio workflow (OSW) run asynchronously.

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

    @mcp.tool(tags={"core", "simulation"}, name="run_simulation")
    def run_simulation_tool(
        osm_path: str,
        epw_path: str | None = None,
        name: str | None = None,
    ):
        """Run an EnergyPlus annual or design-day simulation from an OSM file.

        IMPORTANT: requires weather file (EPW) and design days set on the model
        first (via change_building_location), or pass epw_path here. Without
        design days, HVAC sizing fails.

        Workflow: run_simulation → get_run_status (poll) → extract_summary_metrics.
        """
        return run_simulation(osm_path=osm_path, epw_path=epw_path, name=name)

    @mcp.tool(tags={"core", "simulation"}, name="get_run_status")
    def get_run_status_tool(run_id: str):
        """Get current status of an EnergyPlus simulation run: queued, running,
        completed, or failed. Returns progress percentage and elapsed time.

        Poll no more than once per minute. For long simulations (>2 min),
        poll every 2-3 minutes.
        """
        return get_run_status(run_id)

    @mcp.tool(tags={"simulation"}, name="get_run_logs")
    def get_run_logs_tool(run_id: str, tail: int | None = None, stream: str = "openstudio"):
        """Return tail of OpenStudio or EnergyPlus log output for a simulation
        run. Use to diagnose simulation failures, warnings, or errors.
        """
        return get_run_logs(run_id, tail=tail, stream=stream)

    @mcp.tool(tags={"simulation"}, name="get_run_artifacts")
    def get_run_artifacts_tool(run_id: str):
        """List simulation output files: eplusout.sql, eplusout.err, HTML
        report, OSM/IDF snapshots, measure output. Returns file paths and sizes.
        """
        return get_run_artifacts(run_id)

    @mcp.tool(tags={"simulation"}, name="cancel_run")
    def cancel_run_tool(run_id: str):
        """Cancel a running EnergyPlus simulation. Only works while status is
        'running' or 'queued'.
        """
        return cancel_run(run_id)

    @mcp.tool(tags={"simulation"}, name="validate_model")
    def validate_model_tool():
        """Pre-simulation validation: weather file, design days, HVAC, constructions.
        Use before run_simulation to catch common issues early.
        For post-simulation QA/QC with ASHRAE compliance checks, use run_qaqc_checks instead.
        """
        return validate_model_op()
