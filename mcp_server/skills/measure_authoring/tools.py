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
    @mcp.tool(name="list_custom_measures")
    def list_custom_measures_tool():
        """List all custom measures created with create_measure.

        Returns name, language, and measure_dir for each measure in
        /runs/custom_measures/. Use measure_dir with test_measure or
        apply_measure. Use name with edit_measure.

        Typical workflow: create_measure → test_measure → apply_measure.
        """
        return list_custom_measures_op()

    @mcp.tool(name="create_measure")
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
        """Create a new custom OpenStudio measure with user-provided code.

        Scaffolds via SDK, then injects arguments() and run() body. Output
        dir: /runs/custom_measures/<name>/. Idempotent — overwrites if exists.

        Workflow: create_measure → test_measure → apply_measure.

        ARGUMENT STRATEGY — Make measures reusable:
        - Parameterize anything model-specific: zone/space names, setpoint values,
          schedule names, material properties, thresholds, equipment names
        - Hard-code only measure logic (traversal patterns, formulas, output structure)
        - Use descriptive display_names so users understand each argument
        - Always include description for every argument (units, purpose, behavior)
        - Always provide sensible default_value for optional arguments
        - Common argument patterns:
            Setpoints/thresholds → Double with default (e.g. R-value, watts/m2)
            Object names/filters → String (zone name, space type, schedule name)
            Enable/disable features → Boolean with default true
            Predefined options → Choice with values list
            Counts/hours/limits → Integer with default (e.g. max_zones, setback_hours)
        - Example: a wall insulation measure should parameterize target_r_value (Double),
          surface_filter (String, default ""), and construction_name (String) rather
          than hard-coding R-19 for "Exterior Wall" surfaces

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
                    behavior — ALWAYS include this for every argument
                values: (Choice only) list of allowed values, e.g. ["low", "medium", "high"]
                NOTE: argument extraction code (runner.get*ArgumentValue) is auto-generated
                above the `# --- begin user logic ---` marker. run_body should NOT
                include these calls — just reference variables by argument name.
            taxonomy_tag: BCL taxonomy (default: Whole Building.Space Types)
            modeler_description: Technical description for modelers
            measure_type: "ModelMeasure" (default) or "ReportingMeasure".
                ReportingMeasures run after simulation, accessing SQL results.
                run() receives (runner, user_arguments) — no model param.
                Model and SQL are available via runner.lastOpenStudioModel
                and runner.lastEnergyPlusSqlFilePath (boilerplate auto-generated).

        Ruby common patterns for run_body:
          CRITICAL — error/applicability handling:
            runner.registerError("msg") — MUST follow with `return false` (does NOT halt)
            runner.registerAsNotApplicable("msg") + return true — guard clause when
              measure doesn't apply (e.g. no windows found, already at target)
            runner.registerInitialCondition("before summary")
            runner.registerFinalCondition("after summary with counts")
            runner.registerInfo("progress message")
            runner.registerWarning("non-fatal issue")
          CRITICAL — .name returns OptionalString:
            obj.name.to_s — safe string comparison (returns "" if uninitialized)
            WRONG: obj.name == "Foo" — crashes on OptionalString comparison
            RIGHT: obj.name.to_s == "Foo" or obj.name.to_s.include?("Foo")
          ModelMeasure:
            model.getSurfaces.each { |s| ... }
            model.getSubSurfaces.each { |ss| ... } — windows/doors
            model.getThermalZones.each { |z| ... }
            model.getSpaces.each { |space| ... }
            model.getBuilding.setName(name)
            surface.outsideBoundaryCondition == "Outdoors" — exterior filter
            ss.subSurfaceType — "FixedWindow", "OperableWindow", "Door", etc.
            opt = surface.construction; if opt.is_initialized then c = opt.get end
            OpenStudio.convert(val, "W/m^2", "Btu/hr*ft^2").get — unit conversion
              Common: W/m^2↔Btu/hr*ft^2, m^2*K/W↔ft^2*hr*R/Btu, kWh/m^2↔kBtu/ft^2
              See SKILL.md "Unit Conversion" table for full list
            model.alwaysOnDiscreteSchedule — reusable schedule for constructors
          HVAC traversal (Ruby):
            model.getAirLoopHVACs.each { |loop| ... }
            loop.supplyComponents.each { |c| ... }
            loop.demandComponents.each { |c| ... }
            loop.thermalZones.each { |z| ... }
            model.getPlantLoops.each { |pl| ... }
            pl.supplyComponents.each { |c| ... }
            zone.equipment.each { |eq| ... }
            node = loop.supplyOutletNode
            c.to_CoilHeatingWater.is_initialized → c.to_CoilHeatingWater.get
          ReportingMeasure (model & sql already loaded in boilerplate):
            total_site = sql.totalSiteEnergy; runner.registerValue("total_site_energy", total_site.get)
            query = "SELECT Value FROM TabularDataWithStrings WHERE ..."
            val = sql.execAndReturnFirstDouble(query)
            runner.registerInfo("EUI: #{val.get} kBtu/ft2") if val.is_initialized

        Python common patterns for run_body:
          CRITICAL — same error/applicability rules as Ruby:
            runner.registerError("msg") — MUST follow with `return False`
            runner.registerAsNotApplicable("msg") then return True
          CRITICAL — .name() returns OptionalString:
            str(obj.name()) or obj.name().get() — not bare obj.name()
          ModelMeasure:
            for s in model.getSurfaces(): ...
            for ss in model.getSubSurfaces(): ...
            for z in model.getThermalZones(): ...
            model.getBuilding().setName(name)
            s.outsideBoundaryCondition() == "Outdoors"
            opt = surface.construction(); if opt.is_initialized(): c = opt.get()
            openstudio.convert(val, "W/m^2", "Btu/hr*ft^2").get()
            model.alwaysOnDiscreteSchedule()
          HVAC traversal (Python):
            for loop in model.getAirLoopHVACs(): ...
            for c in loop.supplyComponents(): ...
            for c in loop.demandComponents(): ...
            for z in loop.thermalZones(): ...
            for pl in model.getPlantLoops(): ...
            node = loop.supplyOutletNode()
            if c.to_CoilHeatingWater().is_initialized(): coil = c.to_CoilHeatingWater().get()
          Air terminal types (via air_loop.addBranchForZone, NOT addToThermalZone):
            CooledBeam (2-pipe):
              coil = CoilCoolingCooledBeam.new(model)
              terminal = AirTerminalSingleDuctConstantVolumeCooledBeam.new(model, sch, coil)
            FourPipeBeam (4-pipe):
              cc = CoilCoolingFourPipeBeam.new(model)
              hc = CoilHeatingFourPipeBeam.new(model)
              terminal = AirTerminalSingleDuctConstantVolumeFourPipeBeam.new(model, cc, hc)
          WARNING: Beams are AIR TERMINALS, NOT zone equipment.
          Plant loop wiring: chw_loop.addDemandBranchForComponent(coil)
          Zone equipment priority:
            model.getZoneHVACEquipmentLists.setCoolingPriority(equip, n)
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

    @mcp.tool(name="test_measure")
    def test_measure_tool(
        measure_dir: str,
        arguments: dict[str, Any] | None = None,
        model_path: str | None = None,
        run_id: str | None = None,
    ):
        """Run tests for a custom OpenStudio measure.

        Auto-detects language: Python → pytest, Ruby → minitest.
        Tests run against a real model (not an empty model) so measures
        that depend on HVAC, plant loops, zones, etc. can be tested.

        Model priority: explicit model_path > currently loaded model >
        built-in SystemD_baseline.osm (44 zones, DOAS, CHW/HW/SWH loops).

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

    @mcp.tool(name="edit_measure")
    def edit_measure_tool(
        measure_name: str,
        run_body: str | None = None,
        arguments: list[dict] | str | None = None,
        description: str | None = None,
    ):
        """Edit an existing custom measure's code, arguments, or description.

        Looks up /runs/custom_measures/<measure_name>/. Replaces run() body
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
