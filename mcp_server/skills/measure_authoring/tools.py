"""MCP tool definitions for measure authoring (Phase 9)."""
from __future__ import annotations

from typing import Any

from mcp_server.skills.measure_authoring.operations import (
    create_measure_op,
    edit_measure_op,
    list_custom_measures_op,
    test_measure_op,
)


def register(mcp):
    @mcp.tool(tags={"measures"}, name="list_custom_measures")
    def list_custom_measures_tool():
        """List custom measures in your per-user custom measures dir, created with create_measure.

        Returns name, language, and measure_dir for each. Use measure_dir
        with test_measure or apply_measure. Use name with edit_measure.

        Typical workflow: create_measure -> test_measure -> apply_measure.
        """
        return list_custom_measures_op()

    @mcp.tool(tags={"measures"}, name="create_measure")
    def create_measure_tool(
        name: str,
        description: str,
        run_body: str,
        language: str,
        arguments: list[dict] | str | None = None,
        taxonomy_tag: str = "Whole Building.Space Types",
        modeler_description: str = "",
        measure_type: str = "ModelMeasure",
    ):
        """Create an OpenStudio measure (Ruby or Python; ModelMeasure or
        ReportingMeasure) from a run() body and an argument list. Use this
        rather than writing measure.rb/.py/.xml files directly: it scaffolds via
        the SDK, so measure.xml, checksums and OS App compatibility come out right.

        Call get_skill('measure-authoring') for templates and pitfalls, and
        get_skill_file(skill_name="measure-authoring", filename="run-body-reference.md")
        for the run_body pattern catalog (Ruby and Python). For HVAC measures,
        call search_api to verify methods exist and search_wiring_patterns for
        working connection code.

        Scaffolds via SDK, then injects arguments() and run() body. Output
        dir: your per-user custom measures dir by default. Idempotent — overwrites if exists.

        Workflow: create_measure → test_measure → apply_measure.

        run_body rules that decide whether the measure runs:
          runner.registerError("msg") does not halt; follow it with
            `return false` (Ruby) / `return False` (Python).
          .name returns OptionalString: compare obj.name.to_s (Ruby) or
            str(obj.name()) (Python), not the bare value.
          Parameterize model-specific values (names, setpoints, thresholds) as
            arguments with a description and default; hard-code only the logic.

        Args:
            name: snake_case measure name (becomes dir name + class name)
            description: What the measure does (plain English)
            run_body: Code for the run() method body. Indentation matters:
                Ruby: 4 spaces (e.g. "    model.getBuilding.setName('X')")
                Python: 8 spaces (e.g. "        model.getBuilding().setName('X')")
            language: "Ruby" or "Python" (required — user chooses)
            arguments: List of argument dicts [{name, display_name, description, type,
                required, default_value, values}].
                type: Boolean | Double | Integer | String | Choice
                description: help text explaining the argument's purpose, units, and
                    behavior; give one for every argument
                values: (Choice only) list of allowed values, e.g. ["low", "medium", "high"]
                NOTE: argument extraction code (runner.get*ArgumentValue) is auto-generated
                above the `# --- begin user logic ---` marker. run_body should not
                include these calls — just reference variables by argument name.
            taxonomy_tag: BCL taxonomy (default: Whole Building.Space Types)
            modeler_description: Technical description for modelers
            measure_type: "ModelMeasure" (default) or "ReportingMeasure".
                ReportingMeasures run after simulation, accessing SQL results.
                run() receives (runner, user_arguments) — no model param.
                Model and SQL are available via runner.lastOpenStudioModel
                and runner.lastEnergyPlusSqlFile (boilerplate auto-generated).
        """
        if isinstance(arguments, str):
            import json
            arguments = json.loads(arguments)
        return create_measure_op(
            name=name, description=description, run_body=run_body,
            language=language, arguments=arguments,
            taxonomy_tag=taxonomy_tag, modeler_description=modeler_description,
            measure_type=measure_type,
        )

    @mcp.tool(tags={"measures"}, name="test_measure")
    def test_measure_tool(
        measure_dir: str,
        arguments: dict[str, Any] | None = None,
        model_path: str | None = None,
        run_id: str | None = None,
    ):
        """Run measure tests against a real model; auto-detect Ruby (minitest) or Python (pytest).

        Auto-detects language: Python -> pytest, Ruby -> minitest.
        Tests run against a real model (not an empty model) so measures
        that depend on HVAC, plant loops, zones, etc. can be tested.

        Model priority: explicit model_path > currently loaded model >
        built-in SystemD_baseline.osm (44 zones, DOAS, CHW/HW/SWH loops).
        The model's resources (companion <model>/files/: Schedule:File CSVs,
        plugin scripts) are staged so runner.workflow.findFile sees them.
        Tests run on a private copy; for your own measure tests/test_model.osm
        is copied back and measure.xml is regenerated in your measure dir.

        For ReportingMeasures, provide run_id of a completed simulation.
        The measure will be tested via `openstudio run --postprocess_only`
        against that run's SQL results. Without run_id, only argument
        validation tests run (no run() execution).

        Workflow: create_measure → test_measure → apply_measure.

        Args:
            measure_dir: Path to the measure directory (from create_measure result)
            arguments: Optional test argument values (for good-args test)
            model_path: Optional path to OSM file to test against (default: current model)
            run_id: Optional completed simulation run_id (required for full
                ReportingMeasure testing — provides SQL artifacts)
        """
        return test_measure_op(
            measure_dir=measure_dir, arguments=arguments,
            model_path=model_path, run_id=run_id,
        )

    @mcp.tool(tags={"measures"}, name="edit_measure")
    def edit_measure_tool(
        measure_name: str,
        run_body: str | None = None,
        arguments: list[dict] | str | None = None,
        description: str | None = None,
    ):
        """Modify run() body, arguments, or description of an existing custom measure.

        TIP: call get_skill('measure-authoring') first for templates, API patterns, and common pitfalls.

        Looks up <measure_name> in your per-user custom measures dir. Replaces run() body
        between markers, regenerates arguments() method, updates test file.
        Use list_custom_measures to find available measure names.

        After editing, run test_measure to verify, then apply_measure to use.

        Tip: use this to add arguments to an existing measure that hard-codes
        values — makes it reusable across different models and scenarios.

        Args:
            measure_name: Name of existing custom measure (snake_case dir name)
            run_body: New run() method body (replaces between markers).
                Ruby: indent 4 spaces. Python: indent 8 spaces.
            arguments: New argument spec [{name, display_name, description, type,
                required, default_value, values}]. values is for Choice type only.
            description: Updated description
        """
        if isinstance(arguments, str):
            import json
            arguments = json.loads(arguments)
        return edit_measure_op(
            measure_name=measure_name, run_body=run_body,
            arguments=arguments, description=description,
        )
