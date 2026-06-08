"""MCP tool definitions for OpenStudio Server analysis workflows."""
from __future__ import annotations

from typing import Any

from mcp_server.skills.analysis.operations import (
    add_measure_to_osa_json,
    create_osa_json,
    create_osa_json_from_measures,
    create_project,
    download_analysis_data,
    get_analysis_results_json,
    get_analysis_status,
    submit_analysis,
    submit_wait_download,
    validate_osa_json,
    wait_for_analysis,
)


def register(mcp):
    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_create_osa_json")
    def create_osa_json_tool(
        output_path: str,
        analysis_name: str,
        analysis_type: str = "single_run",
        workflow: list[dict[str, Any]] | None = None,
        output_variables: list[dict[str, Any]] | None = None,
        algorithm: dict[str, Any] | None = None,
        extra_analysis_fields: dict[str, Any] | None = None,
    ):
        """Create an OpenStudio Server OSA JSON file.

        Produces the standard top-level `{"analysis": ...}` structure used by
        OpenStudio-analysis-gem and OpenStudio Server. Use this when the user
        asks to generate an OSA/analysis JSON file before server submission.
        """
        return create_osa_json(
            output_path=output_path,
            analysis_name=analysis_name,
            analysis_type=analysis_type,
            workflow=workflow,
            output_variables=output_variables,
            algorithm=algorithm,
            extra_analysis_fields=extra_analysis_fields,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_validate_osa_json")
    def validate_osa_json_tool(osa_json_path: str):
        """Validate an OSA JSON file with local structural checks.

        Checks JSON parsing and key OpenStudio Server fields such as
        analysis.name, analysis.uuid, problem.analysis_type, workflow, and
        output_variables. Server-side validation may still reject the file.
        """
        return validate_osa_json(osa_json_path)

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_create_osa_json_from_measures")
    def create_osa_json_from_measures_tool(
        output_path: str,
        analysis_name: str,
        measure_specs: list[dict[str, Any]],
        analysis_type: str = "batch_run",
        algorithm: dict[str, Any] | None = None,
        output_variables: list[dict[str, Any]] | None = None,
        extra_analysis_fields: dict[str, Any] | None = None,
    ):
        """Create an OSA JSON file from OpenStudio measures and variable parameters.

        Each measure_spec includes measure_dir plus optional static arguments and
        variables. A variable promotes one measure argument into the algorithm
        search space with a distribution such as uniform, discrete, triangle,
        normal, lognormal, or integer_sequence.
        """
        return create_osa_json_from_measures(
            output_path=output_path,
            analysis_name=analysis_name,
            measure_specs=measure_specs,
            analysis_type=analysis_type,
            algorithm=algorithm,
            output_variables=output_variables,
            extra_analysis_fields=extra_analysis_fields,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_add_measure_to_osa_json")
    def add_measure_to_osa_json_tool(
        osa_json_path: str,
        measure_dir: str,
        arguments: dict[str, Any] | None = None,
        variables: list[dict[str, Any]] | None = None,
        instance_name: str | None = None,
        display_name: str | None = None,
    ):
        """Append a measure step to an existing OSA JSON workflow.

        Use arguments for fixed measure parameters. Use variables for parameters
        the analysis algorithm should change; each variable references an
        argument_name and includes a distribution.
        """
        return add_measure_to_osa_json(
            osa_json_path=osa_json_path,
            measure_dir=measure_dir,
            arguments=arguments,
            variables=variables,
            instance_name=instance_name,
            display_name=display_name,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_create_project")
    def create_project_tool(project_name: str, server_url: str | None = None):
        """Create an OpenStudio Server project and return its project ID.

        Uses POST /projects.json. If server_url is omitted, set
        OPENSTUDIO_SERVER_URL or OS_SERVER_URL in the MCP environment.
        """
        return create_project(project_name=project_name, server_url=server_url)

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_submit")
    def submit_analysis_tool(
        project_id: str,
        osa_json_path: str,
        server_url: str | None = None,
        analysis_name: str | None = None,
        upload_zip_path: str | None = None,
    ):
        """Submit an OSA JSON file to an OpenStudio Server project.

        Uses POST /projects/{project_id}/analyses.json. If upload_zip_path is
        supplied, also uploads the support archive to
        /analyses/{analysis_id}/upload.json.
        """
        return submit_analysis(
            project_id=project_id,
            osa_json_path=osa_json_path,
            server_url=server_url,
            analysis_name=analysis_name,
            upload_zip_path=upload_zip_path,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_status")
    def get_analysis_status_tool(
        analysis_id: str,
        server_url: str | None = None,
        analysis_type: str | None = None,
    ):
        """Get current OpenStudio Server analysis status.

        Uses GET /analyses/{analysis_id}/status.json. Poll no more than once per
        minute for long-running analyses.
        """
        return get_analysis_status(analysis_id=analysis_id, server_url=server_url, analysis_type=analysis_type)

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_wait")
    def wait_for_analysis_tool(
        analysis_id: str,
        server_url: str | None = None,
        analysis_type: str | None = None,
        poll_interval_seconds: int = 60,
        timeout_seconds: int = 86400,
    ):
        """Poll OpenStudio Server until an analysis completes, fails, or times out."""
        return wait_for_analysis(
            analysis_id=analysis_id,
            server_url=server_url,
            analysis_type=analysis_type,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_download_data")
    def download_analysis_data_tool(
        analysis_id: str,
        output_dir: str,
        server_url: str | None = None,
        file_format: str = "csv",
    ):
        """Download exported analysis data from OpenStudio Server.

        Uses GET /analyses/{analysis_id}/download_data.{file_format}?export=true
        and writes the returned file into output_dir.
        """
        return download_analysis_data(
            analysis_id=analysis_id,
            output_dir=output_dir,
            server_url=server_url,
            file_format=file_format,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_results_json")
    def get_analysis_results_json_tool(analysis_id: str, server_url: str | None = None):
        """Return analysis result data as JSON from OpenStudio Server.

        Uses GET /analyses/{analysis_id}/analysis_data.json.
        """
        return get_analysis_results_json(analysis_id=analysis_id, server_url=server_url)

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_submit_wait_download")
    def submit_wait_download_tool(
        project_id: str,
        osa_json_path: str,
        output_dir: str,
        server_url: str | None = None,
        analysis_name: str | None = None,
        upload_zip_path: str | None = None,
        analysis_type: str | None = None,
        poll_interval_seconds: int = 60,
        timeout_seconds: int = 86400,
        download_format: str = "csv",
    ):
        """Submit an OSA JSON file, wait for completion, and download results.

        This is the main workflow tool for: generate/choose an osa.json, submit
        to server, wait for results, and download them to a local directory.
        """
        return submit_wait_download(
            project_id=project_id,
            osa_json_path=osa_json_path,
            output_dir=output_dir,
            server_url=server_url,
            analysis_name=analysis_name,
            upload_zip_path=upload_zip_path,
            analysis_type=analysis_type,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
            download_format=download_format,
        )
