"""MCP tool registration for API reference skill."""
from __future__ import annotations

from .operations import search_api_op, search_wiring_patterns_op


def register(mcp):
    @mcp.tool(name="search_api", tags={"core"})
    def search_api_tool(
        class_pattern: str,
        method_pattern: str | None = None,
        max_classes: int = 10,
        include_base: bool = False,
    ) -> dict:
        """Look up OpenStudio SDK classes with full method signatures.

        IMPORTANT: call before writing measures that use SDK method calls.
        Introspects the live SDK (the openstudio root namespace, openstudio.model,
        and the non-model submodules — airflow, isomodel, gltf, measure, …) to
        verify which methods actually exist on a class, AND returns each method's
        full signature — parameter names and return type — so you can write the
        call correctly. Prevents both hallucinated method names (e.g.
        setRatedCoolingCoefficientOfPerformance) and guessed argument lists.

        Use cases:
          - "What setters does CoilCoolingFourPipeBeam have, and what args?"
          - "Does BoilerHotWater have a setEfficiency method? What does it take?"
          - "List all classes matching 'ChillerElectric'"
          - "How do I read sql output?" — SqlFile is reachable: it lives at the
            openstudio root, not in openstudio.model

        Examples:
          search_api("CoilCoolingFourPipeBeam")
          search_api("Boiler", method_pattern="Efficiency|COP")
          search_api("Chiller", max_classes=5)

        Args:
            class_pattern: Regex to match class names (e.g. "CoilCooling",
                "FourPipeBeam", "Boiler"). Case-insensitive.
            method_pattern: Optional regex to filter methods (e.g. "Rated|COP").
            max_classes: Max classes to return (default 10).
            include_base: Include inherited ModelObject methods (default False).
                Only model-module classes inherit ModelObject — non-model classes
                (SqlFile, WorkflowStepResult) are unaffected.

        Returns setters, getters, and other methods grouped per class. Each entry
        is a signature string, e.g. "setSurfaceType(surfaceType) -> Boolean", and
        each class entry carries a "module" field naming the namespace it lives in
        ("openstudio", "openstudio.model", "openstudio.airflow", ...).

        Return types are read from the SDK's C++ headers and its SWIG wrappers —
        they are sourced, never inferred from the method's name. Read them
        literally; the distinction matters in Ruby:
          - "-> Float"       a plain value. Calling .get on it raises NoMethodError.
          - "-> Float, nil"  an Optional. .get is required; check .is_initialized
                             first. e.g. nominalCapacity() -> Float, nil while
                             efficiency() -> Float on the same class.
          - "-> Array<X>"    a vector; iterate it.
          - "-> ?"           genuinely unknown — no header or annotation declares
                             it. Probe the object (print .class) before calling
                             .get. This is an admitted gap, not a hint.

        An Optional being present is not the same as it being meaningful: e.g.
        ThermalZone#thermostat may be initialized while carrying no setpoint
        schedule. Check the value the behavior depends on, not just the wrapper.
        """
        return search_api_op(
            class_pattern,
            method_pattern=method_pattern,
            max_classes=max_classes,
            include_base=include_base,
        )

    @mcp.tool(tags={"hvac"}, name="search_wiring_patterns")
    def search_wiring_patterns_tool(
        pattern: str,
        max_results: int = 3,
    ) -> dict:
        """Find Ruby code examples for connecting HVAC components to loops and zones.

        Returns working Ruby snippets from openstudio-resources showing how to
        wire coils to plant loops, terminals to air loops, zone equipment to
        thermal zones, and setpoint managers to nodes.

        24 recipes covering: four-pipe beam, cooled beam, VAV, PIU reheat,
        fan coil, baseboard, PTAC, PTHP, WSHP, DOAS, VRF, unitary systems,
        plant loop heat pumps, absorption chillers, air loop construction,
        hot water / chilled water / condenser plant loops.

        Use before authoring measures that create or modify HVAC systems.

        Examples:
          search_wiring_patterns("four pipe beam")
          search_wiring_patterns("boiler plant loop")
          search_wiring_patterns("DOAS")
          search_wiring_patterns("fan coil chilled water")

        Args:
            pattern: Component type or keyword (e.g. "four pipe beam",
                "DOAS", "boiler", "fan coil", "VRF", "PTAC", "unitary",
                "plant loop", "chiller", "heat pump")
            max_results: Max recipes to return (default 3)
        """
        return search_wiring_patterns_op(pattern, max_results=max_results)
