"""MCP tool definitions for OpenStudio Server analysis workflows."""
from __future__ import annotations

from typing import Any

from mcp_server.skills.analysis.operations import (
    add_measure_to_osa_json,
    create_osa_json,
    create_osa_json_from_measures,
    create_project,
    download_analysis_data,
    get_default_output_variables,
    get_foundational_analysis_measures,
    get_analysis_results_json,
    get_analysis_status,
    get_osaf_algorithms,
    prepare_analysis_package,
    preflight_seed_for_analysis_package,
    start_analysis,
    start_sampled_analysis_run,
    submit_analysis,
    submit_wait_download,
    test_server_config_single_run,
    validate_analysis_package,
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
        seed: dict[str, Any] | str | None = None,
        weather_file: dict[str, Any] | str | None = None,
        file_format_version: int = 1,
        schema_path: str | None = None,
        validate_after_create: bool = True,
    ):
        """Create an OpenStudio Server OSA JSON file.

        Produces the standard top-level `{"analysis": ...}` structure used by
        OpenStudio-analysis-gem and OpenStudio Server. Use this when the user
        asks to generate an OSA/analysis JSON file before server submission.
        The file is schema-validated after creation by default. Do not choose
        analysis_type="doe" unless the workflow has at least two measure
        variables. Use "single_run" for a single datapoint, or a
        schema-supported sampling type such as "lhs" for one-variable sampling.
        When output_variables is omitted, a foundational OpenStudio Results
        output-variable set is included, including whole-building energy,
        demand, unmet-hours, and all electricity and natural gas *_ip end-use
        categories. The workflow always includes view_model,
        openstudio_results, and generic_qaqc.
        """
        return create_osa_json(
            output_path=output_path,
            analysis_name=analysis_name,
            analysis_type=analysis_type,
            workflow=workflow,
            output_variables=output_variables,
            algorithm=algorithm,
            extra_analysis_fields=extra_analysis_fields,
            seed=seed,
            weather_file=weather_file,
            file_format_version=file_format_version,
            schema_path=schema_path,
            validate_after_create=validate_after_create,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_validate_osa_json")
    def validate_osa_json_tool(
        osa_json_path: str,
        schema_path: str | None = None,
        require_foundational_measures: bool = False,
    ):
        """Validate an OSA JSON file with the OSAF/OpenStudio Server schema.

        Checks JSON parsing, key OpenStudio Server fields, and the vendored
        OpenStudio-analysis-gem Draft 4 schema before server submission. Also
        blocks DOE analyses with fewer than two measure variables, which OSAF
        accepts initially but later fails during analysis startup. Set
        require_foundational_measures=True when validating MCP-generated
        analyses for submission readiness.
        """
        return validate_osa_json(
            osa_json_path,
            schema_path=schema_path,
            require_foundational_measures=require_foundational_measures,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_default_output_variables")
    def default_output_variables_tool():
        """Return the foundational output variables used in generated OSA JSON.

        `openstudio_analysis_create_osa_json` and
        `openstudio_analysis_create_osa_json_from_measures` include this set
        automatically when output_variables is omitted. The set includes the
        OpenStudio Results whole-building summary values and all electricity
        and natural gas *_ip end-use categories. Use this tool when a client
        wants to inspect, copy, or extend the default set explicitly.
        """
        return get_default_output_variables()

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_foundational_measures")
    def foundational_analysis_measures_tool():
        """Return the common measures that generated analyses run by default.

        These measures are appended to generated OSA workflows and copied into
        support ZIPs by openstudio_analysis_prepare_package.
        """
        return get_foundational_analysis_measures()

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_algorithms")
    def osaf_algorithms_tool(category: str | None = None):
        """List OSAF analysis algorithms and describe when to use them.

        Returns analysis_type values, categories, best-fit use cases, caveats,
        typical algorithm keys, and the correct start sequence. Optionally pass
        a category such as "sampling", "sensitivity", or "optimization", or an
        analysis_type such as "lhs" or "pso" to filter the list.
        """
        return get_osaf_algorithms(category=category)

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_validate_package")
    def validate_analysis_package_tool(
        zip_path: str,
        require_seed_qaqc: bool = True,
        require_foundational_measures: bool = True,
    ):
        """Validate an OSAF analysis support ZIP before upload.

        Requires the OpenStudio-analysis-gem package layout at the archive root:
        measures/, weather/, seeds/, scripts/, and lib/. Also checks for at
        least one seed model, EPW weather file, complete measure directory, and
        by default a lib/seed_simulation_qaqc.json manifest showing the seed
        already simulated successfully and passed basic QA/QC plus the
        foundational analysis measures view_model, openstudio_results, and
        generic_qaqc.
        """
        return validate_analysis_package(
            zip_path,
            require_seed_qaqc=require_seed_qaqc,
            require_foundational_measures=require_foundational_measures,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_preflight_seed")
    def preflight_seed_for_analysis_package_tool(
        seed_path: str,
        weather_file: str | None = None,
        manifest_path: str | None = None,
        template: str = "90.1-2019",
        force_rerun: bool = False,
        wait_timeout_seconds: int = 0,
        poll_interval_seconds: int = 30,
    ):
        """Simulate an OSAF seed model and run basic QA/QC before packaging.

        Reuses an existing completed simulation when the staged seed and weather
        file hashes match, so repeated packaging does not rerun the seed model.
        Writes lib/seed_simulation_qaqc.json when manifest_path is supplied and
        the seed passes.
        """
        return preflight_seed_for_analysis_package(
            seed_path=seed_path,
            weather_file=weather_file,
            manifest_path=manifest_path,
            template=template,
            force_rerun=force_rerun,
            wait_timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_prepare_package")
    def prepare_analysis_package_tool(
        package_dir: str,
        output_zip_path: str,
        seed_path: str | None = None,
        weather_file: str | None = None,
        template: str = "90.1-2019",
        force_rerun: bool = False,
        wait_timeout_seconds: int = 0,
        poll_interval_seconds: int = 30,
    ):
        """Create an OSAF support ZIP only after seed simulation QA/QC passes.

        The tool writes lib/seed_simulation_qaqc.json into package_dir, reusing a
        previous successful matching seed simulation when available. If no
        completed run exists, it starts one and only writes the ZIP once the run
        has completed and passed basic QA/QC. By default it also copies the
        foundational analysis measures into measures/.
        """
        return prepare_analysis_package(
            package_dir=package_dir,
            output_zip_path=output_zip_path,
            seed_path=seed_path,
            weather_file=weather_file,
            template=template,
            force_rerun=force_rerun,
            wait_timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_create_osa_json_from_measures")
    def create_osa_json_from_measures_tool(
        output_path: str,
        analysis_name: str,
        measure_specs: list[dict[str, Any]],
        analysis_type: str = "single_run",
        algorithm: dict[str, Any] | None = None,
        output_variables: list[dict[str, Any]] | None = None,
        extra_analysis_fields: dict[str, Any] | None = None,
        seed: dict[str, Any] | str | None = None,
        weather_file: dict[str, Any] | str | None = None,
        file_format_version: int = 1,
        schema_path: str | None = None,
        validate_after_create: bool = True,
    ):
        """Create an OSA JSON file from OpenStudio measures and variable parameters.

        Each measure_spec includes measure_dir plus optional static arguments and
        variables. A variable promotes one measure argument into the algorithm
        search space with a distribution such as uniform, discrete, triangle,
        normal, lognormal, or integer_sequence. Do not use analysis_type="doe"
        unless there are at least two variables; use "single_run" for a single
        datapoint or a schema-supported sampling type such as "lhs" for
        one-variable sampling. When output_variables is omitted, a foundational
        OpenStudio Results output-variable set is included. By
        the workflow always includes view_model, openstudio_results, and
        generic_qaqc.
        """
        return create_osa_json_from_measures(
            output_path=output_path,
            analysis_name=analysis_name,
            measure_specs=measure_specs,
            analysis_type=analysis_type,
            algorithm=algorithm,
            output_variables=output_variables,
            extra_analysis_fields=extra_analysis_fields,
            seed=seed,
            weather_file=weather_file,
            file_format_version=file_format_version,
            schema_path=schema_path,
            validate_after_create=validate_after_create,
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
        schema_path: str | None = None,
        require_foundational_measures: bool = True,
    ):
        """Submit an OSA JSON file to an OpenStudio Server project.

        Validates against the OSAF/OpenStudio Server schema first, then uses
        POST /projects/{project_id}/analyses.json. If upload_zip_path is
        supplied, also uploads the support archive to /analyses/{analysis_id}/upload.json.
        Submission is blocked when analysis_type="doe" has fewer than two
        measure variables or when the OSA JSON omits foundational analysis
        measures by default.
        """
        return submit_analysis(
            project_id=project_id,
            osa_json_path=osa_json_path,
            server_url=server_url,
            analysis_name=analysis_name,
            upload_zip_path=upload_zip_path,
            schema_path=schema_path,
            require_foundational_measures=require_foundational_measures,
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

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_start")
    def start_analysis_tool(
        analysis_id: str,
        server_url: str | None = None,
        analysis_type: str = "single_run",
        without_delay: bool = False,
    ):
        """Start an existing OpenStudio Server analysis.

        Uses POST /analyses/{analysis_id}/action.json with
        analysis_action=start. For a smoke test, start "single_run" first to
        create the datapoint, then "batch_run" to queue the simulation. For
        sampled analyses such as "lhs", start the sampler first to generate
        datapoints, then start "batch_run" to run them.
        """
        return start_analysis(
            analysis_id=analysis_id,
            server_url=server_url,
            analysis_type=analysis_type,
            without_delay=without_delay,
        )

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_start_sampled_run")
    def start_sampled_analysis_run_tool(
        analysis_id: str,
        server_url: str | None = None,
        sampler_analysis_type: str = "lhs",
        without_delay: bool = False,
    ):
        """Start a sampled analysis in the required OSAF order.

        Calls the sampler action first, such as "lhs", to generate datapoints,
        then calls "batch_run" to queue the generated datapoints. Use this for
        one-variable LHS sweeps and other sampled analyses.
        """
        return start_sampled_analysis_run(
            analysis_id=analysis_id,
            server_url=server_url,
            sampler_analysis_type=sampler_analysis_type,
            without_delay=without_delay,
        )

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

    @mcp.tool(tags={"analysis"}, name="openstudio_analysis_test_server_config")
    def test_server_config_single_run_tool(
        upload_zip_path: str,
        server_url: str | None = "http://localhost:8080",
        output_dir: str | None = None,
        project_name: str = "OpenStudio Server Config Smoke Test",
        wait_timeout_seconds: int = 600,
        poll_interval_seconds: int = 10,
        schema_path: str | None = None,
    ):
        """Smoke-test OpenStudio Server configuration with a single-run analysis.

        First checks GET /status.json, then creates a project, submits a
        single_run OSA JSON using the seed/weather and every measure from
        upload_zip_path. Measure arguments are set to their measure.xml
        default_value so the smoke test exercises the packaged workflow without
        sweeping. The submitted analysis disables verbose/debug CLI logging and
        report/OSW/model/ZIP downloads to avoid Mongo BSON limits from large
        smoke-test artifacts. It uploads the package ZIP, starts single_run to
        create one datapoint, starts batch_run to simulate it, and polls until
        the datapoint completes or fails.
        """
        return test_server_config_single_run(
            upload_zip_path=upload_zip_path,
            server_url=server_url,
            output_dir=output_dir,
            project_name=project_name,
            wait_timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            schema_path=schema_path,
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
        schema_path: str | None = None,
        analysis_type: str | None = None,
        poll_interval_seconds: int = 60,
        timeout_seconds: int = 86400,
        download_format: str = "csv",
        require_foundational_measures: bool = True,
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
            schema_path=schema_path,
            analysis_type=analysis_type,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
            download_format=download_format,
            require_foundational_measures=require_foundational_measures,
        )
