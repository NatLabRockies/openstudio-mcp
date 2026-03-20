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
        """Look up OpenStudio SDK classes, setter methods, and getter methods.

        Introspects the live openstudio.model module to verify which methods
        actually exist on a class. Essential for measure authoring — prevents
        calling nonexistent methods like setRatedCoolingCoefficientOfPerformance.

        Use cases:
          - "What setters does CoilCoolingFourPipeBeam have?"
          - "Does BoilerHotWater have a setEfficiency method?"
          - "List all classes matching 'ChillerElectric'"

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

        Returns setters, getters, and other methods grouped per class.
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
