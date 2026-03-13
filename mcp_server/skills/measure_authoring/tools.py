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
    ):
        """Create a new custom OpenStudio ModelMeasure with user-provided code.

        Scaffolds via SDK, then injects arguments() and run() body. Output
        dir: /runs/custom_measures/<name>/. Idempotent — overwrites if exists.

        Workflow: create_measure → test_measure → apply_measure.

        Args:
            name: snake_case measure name (becomes dir name + class name)
            description: What the measure does (plain English)
            run_body: Code for the run() method body. Indentation matters:
                Ruby: 4 spaces (e.g. "    model.getBuilding.setName('X')")
                Python: 8 spaces (e.g. "        model.getBuilding().setName('X')")
            language: "Ruby" or "Python" (required — user chooses)
            arguments: List of argument dicts [{name, display_name, type, required, default_value}].
                type: Boolean | Double | Integer | String | Choice
            taxonomy_tag: BCL taxonomy (default: Whole Building.Space Types)
            modeler_description: Technical description for modelers

        Ruby common patterns for run_body:
            model.getSurfaces.each { |s| ... }
            model.getThermalZones.each { |z| ... }
            model.getSpaces.each { |space| ... }
            model.getBuilding.setName(name)
            opt = surface.construction; if opt.is_initialized then c = opt.get end
            runner.registerInfo/Warning/Error("msg")
            runner.registerInitialCondition/FinalCondition("msg")
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

        Python common patterns for run_body:
            for s in model.getSurfaces(): ...
            for z in model.getThermalZones(): ...
            model.getBuilding().setName(name)
            opt = surface.construction(); if opt.is_initialized(): c = opt.get()
            runner.registerInfo/registerWarning/registerError("msg")
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
        )

    @mcp.tool(name="test_measure")
    def test_measure_tool(
        measure_dir: str,
        arguments: dict[str, Any] | None = None,
        model_path: str | None = None,
    ):
        """Run tests for a custom OpenStudio measure.

        Auto-detects language: Python → pytest, Ruby → minitest.
        Tests run against a real model (not an empty model) so measures
        that depend on HVAC, plant loops, zones, etc. can be tested.

        Model priority: explicit model_path > currently loaded model >
        built-in SystemD_baseline.osm (44 zones, DOAS, CHW/HW/SWH loops).

        Workflow: create_measure → test_measure → apply_measure.

        Args:
            measure_dir: Path to the measure directory (from create_measure result)
            arguments: Optional test argument values (for good-args test)
            model_path: Optional path to OSM file to test against (default: current model)
        """
        return test_measure_op(
            measure_dir=measure_dir, arguments=arguments, model_path=model_path,
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

        Args:
            measure_name: Name of existing custom measure (snake_case dir name)
            run_body: New run() method body (replaces between markers).
                Ruby: indent 4 spaces. Python: indent 8 spaces.
            arguments: New argument spec [{name, display_name, type, required, default_value}]
            description: Updated description
        """
        if isinstance(arguments, str):
            import json
            arguments = json.loads(arguments)
        return edit_measure_op(
            measure_name=measure_name, run_body=run_body,
            arguments=arguments, description=description,
        )
